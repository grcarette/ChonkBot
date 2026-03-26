# tests/test_disqualify.py
"""
Tests for player disqualification behavior.

Covers all four guaranteed DQ invariants:

1. ACTIVE LOBBY: If the DQ'd player is in an active lobby, it is reported as a
   win for the opponent, and the DQ'd player's score is penalized (-1 point for Swiss).

2. FUTURE PAIRINGS: The DQ'd player is not selected for future matchups.
   For Swiss: dropped=True excludes them from swiss_get_available_players.
   For Challonge: their participant is removed from the bracket.

3. CHALLONGE AUTO-LOSE: In a Challonge bracket, if a future match becomes
   available where the DQ'd player is a participant, they automatically lose.

4. NO REJOIN: The DQ'd player cannot register back into the event.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call


# ─── Shared factories ─────────────────────────────────────────────────────────

def make_swiss_tm():
    """TournamentManager wired for a Swiss event."""
    from tournaments.tournament_manager import TournamentManager

    tournament = {
        '_id': 'tid',
        'name': 'Test Tournament',
        'format': 'swiss',
        'state': 'active',
        'entrants': {'100': None, '200': None},
        'checked_in': [100, 200],
        'dqs': [],
        'stagelist': [],
        'organizers': [999],
        'config': {'approved_registration': False, 'ranked_reporting': False},
        'registration_open': False,
        'debug': False,
        'category_id': 99999,
    }

    tm = object.__new__(TournamentManager)
    tm.tournament = tournament
    tm.guild = MagicMock()
    tm.lobbies = {}
    tm.debug = False
    tm.organizer_role = None

    tm.bot = MagicMock()
    tm.bot.dh = AsyncMock()
    tm.bot.dh.get_tournament_by_id = AsyncMock(return_value=tournament)
    tm.bot.dh.get_registration_status = AsyncMock(return_value=True)
    tm.bot.dh.find_player_match = AsyncMock(return_value=None)
    tm.bot.dh.disqualify_player = AsyncMock(return_value=True)
    tm.bot.dh.swiss_drop_player = AsyncMock()
    tm.bot.dh.get_swiss_event_by_tournament = AsyncMock(return_value={
        '_id': 'eid',
        'players': {
            '100': {'active_match_id': None, 'dropped': False, 'points': 1.0},
            '200': {'active_match_id': None, 'dropped': False, 'points': 1.0},
        },
    })

    from formats.swiss import SwissFormat
    fmt = object.__new__(SwissFormat)
    fmt.tm = tm
    fmt.dh = tm.bot.dh
    fmt.pending_results = []
    fmt.manager = AsyncMock()
    fmt.manager.on_player_dropped = AsyncMock()
    tm.format = fmt

    tm.get_tournament = AsyncMock(return_value=tournament)

    return tm, tournament


def make_challonge_tm():
    """TournamentManager wired for a Challonge (double elimination) event."""
    from tournaments.tournament_manager import TournamentManager

    tournament = {
        '_id': 'tid',
        'name': 'Test Tournament',
        'format': 'double elimination',
        'state': 'active',
        'entrants': {'100': 10, '200': 20},   # discord_id: challonge_id
        'checked_in': [100, 200],
        'dqs': [],
        'stagelist': [],
        'organizers': [999],
        'config': {'approved_registration': False, 'ranked_reporting': False},
        'registration_open': False,
        'challonge_data': {'id': 'chid', 'url': 'test-url'},
        'debug': False,
        'category_id': 99999,
    }

    tm = object.__new__(TournamentManager)
    tm.tournament = tournament
    tm.guild = MagicMock()
    tm.lobbies = {}
    tm.debug = False
    tm.organizer_role = None

    tm.bot = MagicMock()
    tm.bot.dh = AsyncMock()
    tm.bot.dh.get_tournament_by_id = AsyncMock(return_value=tournament)
    tm.bot.dh.get_registration_status = AsyncMock(return_value=True)
    tm.bot.dh.find_player_match = AsyncMock(return_value=None)
    tm.bot.dh.disqualify_player = AsyncMock(return_value=True)

    from formats.challonge import ChallongeFormat
    fmt = object.__new__(ChallongeFormat)
    fmt.tm = tm
    fmt.dh = tm.bot.dh
    fmt.ch = AsyncMock()
    fmt.called_match_ids = set()
    fmt.autocall_matches = False
    fmt.hold_when_ready = set()
    fmt._pending_cache = None
    tm.format = fmt

    tm.get_tournament = AsyncMock(return_value=tournament)

    return tm, tournament


# ═══════════════════════════════════════════════════════════════════════════════
# INVARIANT 1 — Active lobby is reported as opponent win, DQ'd player penalized
# ═══════════════════════════════════════════════════════════════════════════════

class TestDQActiveLobby:

    @pytest.mark.asyncio
    async def test_swiss_dq_with_active_lobby_calls_end_reporting_with_opponent_as_winner(self):
        """Opponent must be declared winner when a Swiss player is DQ'd mid-match."""
        tm, _ = make_swiss_tm()
        lobby_doc = {'match_id': 42, 'players': [100, 200]}
        tm.bot.dh.find_player_match = AsyncMock(return_value=lobby_doc)

        mock_lobby = AsyncMock()
        tm.lobbies[42] = mock_lobby

        await tm.disqualify_player(100)

        mock_lobby.end_reporting.assert_awaited_once()
        args, kwargs = mock_lobby.end_reporting.call_args
        winner_id = args[0] if args else kwargs.get('winner_id')
        assert winner_id == 200, "Opponent (200) must be the winner, not the DQ'd player"

    @pytest.mark.asyncio
    async def test_challonge_dq_with_active_lobby_calls_end_reporting_with_opponent_as_winner(self):
        """Opponent must be declared winner when a Challonge player is DQ'd mid-match."""
        tm, _ = make_challonge_tm()
        lobby_doc = {'match_id': 42, 'players': [100, 200]}
        tm.bot.dh.find_player_match = AsyncMock(return_value=lobby_doc)

        mock_lobby = AsyncMock()
        tm.lobbies[42] = mock_lobby

        await tm.disqualify_player(100)

        mock_lobby.end_reporting.assert_awaited_once()
        args, kwargs = mock_lobby.end_reporting.call_args
        winner_id = args[0] if args else kwargs.get('winner_id')
        assert winner_id == 200

    @pytest.mark.asyncio
    async def test_dq_end_reporting_is_flagged_as_dq(self):
        """end_reporting must be called with is_dq=True so formats handle it correctly."""
        tm, _ = make_challonge_tm()
        lobby_doc = {'match_id': 42, 'players': [100, 200]}
        tm.bot.dh.find_player_match = AsyncMock(return_value=lobby_doc)

        mock_lobby = AsyncMock()
        tm.lobbies[42] = mock_lobby

        await tm.disqualify_player(100)

        _, kwargs = mock_lobby.end_reporting.call_args
        assert kwargs.get('is_dq') is True

    @pytest.mark.asyncio
    async def test_swiss_dq_player_receives_negative_point_penalty(self):
        """
        In Swiss, the DQ'd player's points must go to -1 (not just stay unchanged).
        swiss_record_result must apply a -1 penalty to the loser when is_dq=True.
        """
        from formats.swiss import SwissFormat

        swiss_event = {
            '_id': 'eid',
            'players': {
                '100': {
                    'discord_id': 100,
                    'points': 0.0,
                    'wins': 0,
                    'losses': 0,
                    'rounds_played': 0,
                    'active_match_id': 42,
                    'dropped': False,
                    'match_history': [],
                },
                '200': {
                    'discord_id': 200,
                    'points': 0.0,
                    'wins': 0,
                    'losses': 0,
                    'rounds_played': 0,
                    'active_match_id': 42,
                    'dropped': False,
                    'match_history': [],
                },
            },
            'matches': [
                {'match_id': 42, 'player_1': 100, 'player_2': 200, 'winner': None, 'state': 'active'}
            ],
        }

        dh = AsyncMock()
        dh.get_swiss_event = AsyncMock(return_value=swiss_event)
        dh.swiss_collection = AsyncMock()
        dh.swiss_collection.update_one = AsyncMock()

        # Call swiss_record_result with is_dq=True
        from data.swiss import SwissMethodsMixin
        mixin = object.__new__(SwissMethodsMixin)
        mixin.swiss_collection = dh.swiss_collection
        mixin.get_swiss_event = dh.get_swiss_event

        with patch('data.swiss.ObjectId', side_effect=lambda x: x):
            await mixin.swiss_record_result('eid', 42, winner_id=200, loser_id=100, is_dq=True)

        update_call = dh.swiss_collection.update_one.call_args
        set_ops = update_call[0][1]['$set']

        assert set_ops['players.100.points'] == -1.0, (
            "DQ'd player must receive -1 points, not 0"
        )
        assert set_ops['players.200.points'] == 1.0, (
            "Winner must still receive +1 point"
        )

    @pytest.mark.asyncio
    async def test_dq_without_active_lobby_does_not_call_end_reporting(self):
        """DQ with no active match should not try to report a result."""
        tm, _ = make_swiss_tm()
        tm.bot.dh.find_player_match = AsyncMock(return_value=None)

        await tm.disqualify_player(100)

        for lobby in tm.lobbies.values():
            lobby.end_reporting.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_dq_only_affects_the_dqd_players_lobby(self):
        """DQ'ing player 100 must not call end_reporting on a lobby they're not in."""
        tm, _ = make_challonge_tm()

        # Player 100 is in match 42, player 300 vs 400 are in match 99
        tm.bot.dh.find_player_match = AsyncMock(
            return_value={'match_id': 42, 'players': [100, 200]}
        )

        lobby_42 = AsyncMock()
        lobby_99 = AsyncMock()
        tm.lobbies[42] = lobby_42
        tm.lobbies[99] = lobby_99

        await tm.disqualify_player(100)

        lobby_42.end_reporting.assert_awaited_once()
        lobby_99.end_reporting.assert_not_awaited()


# ═══════════════════════════════════════════════════════════════════════════════
# INVARIANT 2 — DQ'd player is excluded from future pairings
# ═══════════════════════════════════════════════════════════════════════════════

class TestDQExcludedFromPairings:

    @pytest.mark.asyncio
    async def test_swiss_dq_calls_on_player_unregister_to_set_dropped(self):
        """
        disqualify_player must call format.on_player_unregister so Swiss sets
        dropped=True in the swiss event, excluding the player from future rounds.
        """
        tm, _ = make_swiss_tm()
        tm.format.on_player_unregister = AsyncMock()

        await tm.disqualify_player(100)

        tm.format.on_player_unregister.assert_awaited_once_with(100)

    @pytest.mark.asyncio
    async def test_swiss_on_player_unregister_calls_swiss_drop_player(self):
        """on_player_unregister must write dropped=True to the DB via swiss_drop_player."""
        from formats.swiss import SwissFormat

        dh = AsyncMock()
        dh.get_swiss_event_by_tournament = AsyncMock(return_value={'_id': 'eid'})
        dh.swiss_drop_player = AsyncMock()

        tm = MagicMock()
        tm.tournament = {'_id': 'tid', 'state': 'active'}
        tm.get_tournament = AsyncMock(return_value={'_id': 'tid', 'state': 'active'})
        tm.bot = MagicMock()
        tm.bot.dh = dh

        fmt = object.__new__(SwissFormat)
        fmt.tm = tm
        fmt.dh = dh
        fmt.manager = AsyncMock()
        fmt.manager.on_player_dropped = AsyncMock()

        await fmt.on_player_unregister(100)

        dh.swiss_drop_player.assert_awaited_once_with('eid', 100)

    @pytest.mark.asyncio
    async def test_swiss_dropped_player_not_in_available_players(self):
        """
        swiss_get_available_players must exclude players with dropped=True.
        This is the gating function used by the pairing cycle.
        """
        from data.swiss import SwissMethodsMixin

        event = {
            '_id': 'eid',
            'players': {
                '100': {'dropped': True,  'active_match_id': None, 'points': 0.0},
                '200': {'dropped': False, 'active_match_id': None, 'points': 0.0},
                '300': {'dropped': False, 'active_match_id': None, 'points': 0.0},
            }
        }

        mixin = object.__new__(SwissMethodsMixin)
        mixin.get_swiss_event = AsyncMock(return_value=event)

        available = await mixin.swiss_get_available_players('eid')
        available_ids = [p['discord_id'] for p in available]

        assert 100 not in available_ids, "DQ'd (dropped) player must not be available for pairing"
        assert 200 in available_ids
        assert 300 in available_ids

    @pytest.mark.asyncio
    async def test_challonge_dq_unregisters_participant_from_bracket(self):
        """
        For Challonge, on_player_unregister must destroy the participant from
        the bracket so they cannot be matched in future rounds.
        """
        tm, t = make_challonge_tm()
        tm.format.on_player_unregister = AsyncMock()

        await tm.disqualify_player(100)

        tm.format.on_player_unregister.assert_awaited_once_with(100)

    @pytest.mark.asyncio
    async def test_challonge_on_player_unregister_calls_ch_unregister(self):
        """ChallongeFormat.on_player_unregister must call ch.unregister_player."""
        from formats.challonge import ChallongeFormat

        tournament = {
            '_id': 'tid',
            'entrants': {'100': 10},
            'challonge_data': {'id': 'chid', 'url': 'test-url'},
        }

        dh = AsyncMock()
        tm = MagicMock()
        tm.bot = MagicMock()
        tm.bot.dh = dh
        tm.get_tournament = AsyncMock(return_value=tournament)

        fmt = object.__new__(ChallongeFormat)
        fmt.tm = tm
        fmt.dh = dh
        fmt.ch = AsyncMock()
        fmt.ch.unregister_player = AsyncMock()

        await fmt.on_player_unregister(100)

        fmt.ch.unregister_player.assert_awaited_once_with('chid', 10)


# ═══════════════════════════════════════════════════════════════════════════════
# INVARIANT 3 — Challonge: DQ'd player auto-loses any newly available match
# ═══════════════════════════════════════════════════════════════════════════════

class TestChallongeDQAutoLose:

    @pytest.mark.asyncio
    async def test_call_match_auto_resolves_if_player1_is_dqd(self):
        """
        When a match is called and player 1 is in tournament.dqs,
        end_reporting must be called immediately with player 2 as winner.
        """
        from formats.challonge import ChallongeFormat

        tournament = {
            '_id': 'tid',
            'entrants': {'100': 10, '200': 20},
            'dqs': [100],   # player 100 is DQ'd
            'stagelist': [],
            'challonge_data': {'id': 'chid', 'url': 'test-url'},
            'format': 'double elimination',
        }

        dh = AsyncMock()
        dh.find_match = AsyncMock(return_value=None)

        tm = MagicMock()
        tm.tournament = tournament
        tm.bot = MagicMock()
        tm.bot.dh = dh
        tm.get_tournament = AsyncMock(return_value=tournament)
        tm.lobbies = {}
        tm.guild = MagicMock()

        player_1 = {'user_id': 100, 'name': 'DQ Player'}
        player_2 = {'user_id': 200, 'name': 'Opponent'}

        fmt = object.__new__(ChallongeFormat)
        fmt.tm = tm
        fmt.dh = dh
        fmt.ch = AsyncMock()
        fmt.called_match_ids = set()
        fmt.hold_when_ready = set()
        fmt._pending_cache = None

        match_data = {
            'match_id': 99,
            'player_1_id': 100,
            'player_2_id': 200,
            'round': 1,
            'bracket': 'Winners',
            'prereq_matches': [],
        }

        mock_lobby = AsyncMock()
        mock_lobby.end_reporting = AsyncMock()

        with patch('formats.challonge.MatchLobby') as MockLobby, \
             patch('formats.challonge.MatchService'):
            MockLobby.create = AsyncMock(return_value=mock_lobby)
            fmt.get_players_from_match = AsyncMock(return_value=(player_1, player_2))
            fmt.get_lobby_name = AsyncMock(return_value='wr1-DQ Player vs Opponent')

            await fmt.call_match(match_data)
            # Allow background task to run
            import asyncio
            await asyncio.sleep(0)

        mock_lobby.end_reporting.assert_awaited_once()
        _, kwargs = mock_lobby.end_reporting.call_args
        assert kwargs.get('winner_id') == 200
        assert kwargs.get('is_dq') is True

    @pytest.mark.asyncio
    async def test_call_match_auto_resolves_if_player2_is_dqd(self):
        """
        When a match is called and player 2 is in tournament.dqs,
        end_reporting must be called immediately with player 1 as winner.
        """
        from formats.challonge import ChallongeFormat

        tournament = {
            '_id': 'tid',
            'entrants': {'100': 10, '200': 20},
            'dqs': [200],   # player 200 is DQ'd
            'stagelist': [],
            'challonge_data': {'id': 'chid', 'url': 'test-url'},
            'format': 'double elimination',
        }

        dh = AsyncMock()
        dh.find_match = AsyncMock(return_value=None)

        tm = MagicMock()
        tm.tournament = tournament
        tm.bot = MagicMock()
        tm.bot.dh = dh
        tm.get_tournament = AsyncMock(return_value=tournament)
        tm.lobbies = {}
        tm.guild = MagicMock()

        player_1 = {'user_id': 100, 'name': 'Player 1'}
        player_2 = {'user_id': 200, 'name': 'DQ Player'}

        fmt = object.__new__(ChallongeFormat)
        fmt.tm = tm
        fmt.dh = dh
        fmt.ch = AsyncMock()
        fmt.called_match_ids = set()
        fmt.hold_when_ready = set()
        fmt._pending_cache = None

        match_data = {
            'match_id': 99,
            'player_1_id': 100,
            'player_2_id': 200,
            'round': 1,
            'bracket': 'Winners',
            'prereq_matches': [],
        }

        mock_lobby = AsyncMock()
        mock_lobby.end_reporting = AsyncMock()

        with patch('formats.challonge.MatchLobby') as MockLobby, \
             patch('formats.challonge.MatchService'):
            MockLobby.create = AsyncMock(return_value=mock_lobby)
            fmt.get_players_from_match = AsyncMock(return_value=(player_1, player_2))
            fmt.get_lobby_name = AsyncMock(return_value='wr1-Player 1 vs DQ Player')

            await fmt.call_match(match_data)
            import asyncio
            await asyncio.sleep(0)

        mock_lobby.end_reporting.assert_awaited_once()
        _, kwargs = mock_lobby.end_reporting.call_args
        assert kwargs.get('winner_id') == 100
        assert kwargs.get('is_dq') is True

    @pytest.mark.asyncio
    async def test_non_dqd_match_is_not_auto_resolved(self):
        """A match where neither player is DQ'd must not be auto-resolved."""
        from formats.challonge import ChallongeFormat

        tournament = {
            '_id': 'tid',
            'entrants': {'100': 10, '200': 20},
            'dqs': [],  # nobody DQ'd
            'stagelist': [],
            'challonge_data': {'id': 'chid', 'url': 'test-url'},
            'format': 'double elimination',
        }

        dh = AsyncMock()
        dh.find_match = AsyncMock(return_value=None)

        tm = MagicMock()
        tm.tournament = tournament
        tm.bot = MagicMock()
        tm.bot.dh = dh
        tm.get_tournament = AsyncMock(return_value=tournament)
        tm.lobbies = {}
        tm.guild = MagicMock()

        player_1 = {'user_id': 100, 'name': 'Player 1'}
        player_2 = {'user_id': 200, 'name': 'Player 2'}

        fmt = object.__new__(ChallongeFormat)
        fmt.tm = tm
        fmt.dh = dh
        fmt.ch = AsyncMock()
        fmt.called_match_ids = set()
        fmt.hold_when_ready = set()
        fmt._pending_cache = None

        match_data = {
            'match_id': 99,
            'player_1_id': 100,
            'player_2_id': 200,
            'round': 1,
            'bracket': 'Winners',
            'prereq_matches': [],
        }

        mock_lobby = AsyncMock()
        mock_lobby.end_reporting = AsyncMock()
        mock_lobby.initialize_match = AsyncMock()

        with patch('formats.challonge.MatchLobby') as MockLobby, \
             patch('formats.challonge.MatchService'):
            MockLobby.create = AsyncMock(return_value=mock_lobby)
            fmt.get_players_from_match = AsyncMock(return_value=(player_1, player_2))
            fmt.get_lobby_name = AsyncMock(return_value='wr1-Player 1 vs Player 2')

            await fmt.call_match(match_data)
            import asyncio
            await asyncio.sleep(0)

        mock_lobby.end_reporting.assert_not_awaited()
        mock_lobby.initialize_match.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════════════════════
# INVARIANT 4 — DQ'd player cannot register back into the event
# ═══════════════════════════════════════════════════════════════════════════════

class TestDQCannotRejoin:

    @pytest.mark.asyncio
    async def test_swiss_dqd_player_blocked_at_registration_gate(self):
        """
        SwissFormat.on_player_register must refuse to add a player who is in
        tournament.dqs, even if swiss_rejoin_player returns False (no record found).
        """
        from formats.swiss import SwissFormat

        tournament = {
            '_id': 'tid',
            'state': 'active',
            'dqs': [100],
        }

        dh = AsyncMock()
        dh.get_swiss_event_by_tournament = AsyncMock(return_value={'_id': 'eid'})
        dh.swiss_rejoin_player = AsyncMock(return_value=False)
        dh.swiss_add_player = AsyncMock()
        dh.register_player = AsyncMock()

        tm = MagicMock()
        tm.tournament = tournament
        tm.get_tournament = AsyncMock(return_value=tournament)
        tm.bot = MagicMock()
        tm.bot.dh = dh
        tm.get_ranked_player = AsyncMock(return_value=None)

        fmt = object.__new__(SwissFormat)
        fmt.tm = tm
        fmt.dh = dh
        fmt.manager = AsyncMock()
        fmt.manager.on_player_joined = AsyncMock()
        fmt.pending_results = []

        await fmt.on_player_register(100, {'name': 'DQ Player'})

        dh.swiss_add_player.assert_not_awaited()
        dh.register_player.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_swiss_dqd_player_with_dropped_record_cannot_rejoin(self):
        """
        A DQ'd player who has a swiss event record (dropped=True) must not
        be restored via swiss_rejoin_player — rejoin must refuse DQ'd players.
        """
        from formats.swiss import SwissFormat

        tournament = {
            '_id': 'tid',
            'state': 'active',
            'dqs': [100],
        }

        dh = AsyncMock()
        dh.get_swiss_event_by_tournament = AsyncMock(return_value={
            '_id': 'eid',
            'players': {
                '100': {'dropped': True, 'points': 0.0, 'active_match_id': None}
            }
        })
        # Rejoin returns False for DQ'd players
        dh.swiss_rejoin_player = AsyncMock(return_value=False)
        dh.swiss_add_player = AsyncMock()
        dh.register_player = AsyncMock()

        tm = MagicMock()
        tm.tournament = tournament
        tm.get_tournament = AsyncMock(return_value=tournament)
        tm.bot = MagicMock()
        tm.bot.dh = dh
        tm.get_ranked_player = AsyncMock(return_value=None)

        fmt = object.__new__(SwissFormat)
        fmt.tm = tm
        fmt.dh = dh
        fmt.manager = AsyncMock()
        fmt.pending_results = []

        await fmt.on_player_register(100, {'name': 'DQ Player'})

        dh.swiss_add_player.assert_not_awaited()
        dh.register_player.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_dqd_dropped_player_can_rejoin(self):
        """
        A player who dropped voluntarily (dropped=True but not in dqs) must
        still be able to rejoin via swiss_rejoin_player.
        """
        from formats.swiss import SwissFormat

        tournament = {
            '_id': 'tid',
            'state': 'active',
            'dqs': [],  # not DQ'd
        }

        dh = AsyncMock()
        dh.get_swiss_event_by_tournament = AsyncMock(return_value={'_id': 'eid'})
        dh.swiss_rejoin_player = AsyncMock(return_value=True)  # found and rejoined
        dh.swiss_add_player = AsyncMock()
        dh.register_player = AsyncMock()

        tm = MagicMock()
        tm.tournament = tournament
        tm.get_tournament = AsyncMock(return_value=tournament)
        tm.bot = MagicMock()
        tm.bot.dh = dh

        fmt = object.__new__(SwissFormat)
        fmt.tm = tm
        fmt.dh = dh
        fmt.manager = AsyncMock()
        fmt.manager.on_player_joined = AsyncMock()
        fmt.pending_results = []

        await fmt.on_player_register(100, {'name': 'Player'})

        dh.swiss_rejoin_player.assert_awaited_once_with('eid', 100)
        dh.swiss_add_player.assert_not_awaited()  # rejoin succeeded, no fresh add

    @pytest.mark.asyncio
    async def test_dq_adds_player_to_tournament_dqs_list(self):
        """disqualify_player must persist the DQ to tournament.dqs in the DB."""
        tm, _ = make_swiss_tm()

        await tm.disqualify_player(100)

        tm.bot.dh.disqualify_player.assert_awaited_once_with('tid', 100)

    @pytest.mark.asyncio
    async def test_dq_returns_false_for_unregistered_player(self):
        """disqualify_player must return False if the player is not registered."""
        tm, _ = make_swiss_tm()
        tm.bot.dh.get_registration_status = AsyncMock(return_value=False)

        result = await tm.disqualify_player(100)

        assert result is False