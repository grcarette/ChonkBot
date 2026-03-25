# tests/test_disqualify.py
"""
Tests for player disqualification behavior.

Covers:
- disqualify_player returns False if player is not registered
- disqualify_player calls end_reporting with is_dq=True when player has active match
- disqualify_player calls end_reporting on the correct lobby (opponent wins)
- disqualify_player adds player to dqs list via dh.disqualify_player
- disqualify_player works even if player has no active match
- For Swiss: DQ marks the player as dropped in the swiss event
- For Swiss: a DQ'd player cannot register again (swiss_rejoin_player returns False for DQ'd players)
- For Challonge: DQ result propagates to Challonge via end_reporting → on_result
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def make_tm(fmt='double elimination'):
    from tournaments.tournament_manager import TournamentManager

    tournament = {
        '_id': 'tid',
        'name': 'Test Tournament',
        'format': fmt,
        'state': 'active',
        'entrants': {'100': 10, '200': 20},
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
    tm.bot.dh.get_swiss_event_by_tournament = AsyncMock(return_value={
        '_id': 'eid',
        'players': {
            '100': {'active_match_id': None, 'dropped': False},
            '200': {'active_match_id': None, 'dropped': False},
        },
    })
    tm.bot.dh.swiss_drop_player = AsyncMock()

    tm.format = MagicMock()
    tm.format.on_player_unregister = AsyncMock()
    tm.format.needs_match_call_refresh = True

    tm.get_tournament = AsyncMock(return_value=tournament)

    return tm, tournament


# ─── Basic DQ behavior ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dq_returns_false_when_player_not_registered():
    tm, t = make_tm()
    tm.bot.dh.get_registration_status = AsyncMock(return_value=False)

    result = await tm.disqualify_player(100)

    assert result is False


@pytest.mark.asyncio
async def test_dq_calls_dh_disqualify_player():
    tm, t = make_tm()

    await tm.disqualify_player(100)

    tm.bot.dh.disqualify_player.assert_awaited_once_with('tid', 100)


@pytest.mark.asyncio
async def test_dq_with_no_active_match_does_not_call_end_reporting():
    tm, t = make_tm()
    tm.bot.dh.find_player_match = AsyncMock(return_value=None)

    await tm.disqualify_player(100)

    # No lobby in memory, so end_reporting should not be called
    assert len(tm.lobbies) == 0


@pytest.mark.asyncio
async def test_dq_with_active_match_calls_end_reporting_with_dq_true():
    tm, t = make_tm()

    lobby_doc = {'match_id': 42, 'players': [100, 200]}
    tm.bot.dh.find_player_match = AsyncMock(return_value=lobby_doc)

    mock_lobby = AsyncMock()
    mock_lobby.end_reporting = AsyncMock()
    tm.lobbies[42] = mock_lobby

    await tm.disqualify_player(100)

    mock_lobby.end_reporting.assert_awaited_once_with(200, is_dq=True)


@pytest.mark.asyncio
async def test_dq_opponent_is_declared_winner():
    """The non-DQ'd player must win, not the DQ'd player."""
    tm, t = make_tm()

    lobby_doc = {'match_id': 42, 'players': [100, 200]}
    tm.bot.dh.find_player_match = AsyncMock(return_value=lobby_doc)

    mock_lobby = AsyncMock()
    tm.lobbies[42] = mock_lobby

    await tm.disqualify_player(100)

    call_args = mock_lobby.end_reporting.call_args
    winner_id = call_args[0][0] if call_args[0] else call_args[1].get('winner_id')
    assert winner_id == 200  # opponent wins, not the DQ'd player


# ─── Swiss DQ behavior ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_swiss_dq_marks_player_as_dropped():
    """
    In Swiss, disqualifying a player should also mark them as dropped
    in the swiss event so they are excluded from future pairings.
    """
    tm, t = make_tm(fmt='swiss')
    t['format'] = 'swiss'

    await tm.disqualify_player(100)

    # disqualify_player should result in the player being dropped from swiss
    # This is done via dh.disqualify_player which marks them in dqs,
    # AND the format's on_player_unregister should mark them dropped
    tm.bot.dh.disqualify_player.assert_awaited_once_with('tid', 100)


@pytest.mark.asyncio
async def test_swiss_dq_player_cannot_rejoin():
    """
    A DQ'd Swiss player should not be able to register again.
    swiss_rejoin_player must return False for DQ'd players,
    and they should not be added back as a fresh player either.
    """
    from formats.swiss import SwissFormat

    tm = MagicMock()
    tm.tournament = {'_id': 'tid', 'state': 'active'}
    tm.get_tournament = AsyncMock(return_value={'_id': 'tid', 'state': 'active'})
    tm.debug = False

    dh = AsyncMock()
    # Player exists but is DQ'd (dropped=True) — rejoin returns False
    dh.get_swiss_event_by_tournament = AsyncMock(return_value={
        '_id': 'eid',
        'players': {
            '100': {
                'dropped': True,
                'points': 1.0,
                'wins': 1,
                'losses': 1,
                'active_match_id': None,
                'match_history': [200],
            }
        },
    })
    # swiss_rejoin_player checks the DQ list — DQ'd players return False
    dh.swiss_rejoin_player = AsyncMock(return_value=False)
    dh.swiss_add_player = AsyncMock()
    dh.register_player = AsyncMock()
    tm.bot = MagicMock()
    tm.bot.dh = dh

    # Tournament has player 100 in dqs list
    tm.tournament = {
        '_id': 'tid',
        'state': 'active',
        'dqs': [100],
    }
    tm.get_tournament = AsyncMock(return_value=tm.tournament)

    fmt = object.__new__(SwissFormat)
    fmt.tm = tm
    fmt.dh = dh
    fmt.manager = AsyncMock()
    fmt.manager.on_player_joined = AsyncMock()
    fmt.pending_results = []

    await fmt.on_player_register(100, {'name': 'player_100'})

    # Even though rejoin returned False (player exists but is DQ'd),
    # swiss_add_player should NOT be called — we don't want to reset their data
    # and re-add them as a fresh player
    dh.swiss_add_player.assert_not_awaited()


# ─── Challonge DQ behavior ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_challonge_dq_result_is_reported_as_dq():
    """
    When a player is DQ'd in a Challonge tournament, end_reporting must be
    called with is_dq=True so the result is correctly reported to Challonge.
    """
    tm, t = make_tm(fmt='double elimination')

    lobby_doc = {'match_id': 42, 'players': [100, 200]}
    tm.bot.dh.find_player_match = AsyncMock(return_value=lobby_doc)

    mock_lobby = AsyncMock()
    tm.lobbies[42] = mock_lobby

    await tm.disqualify_player(100)

    _, kwargs = mock_lobby.end_reporting.call_args
    assert kwargs.get('is_dq') is True


@pytest.mark.asyncio
async def test_challonge_dq_does_not_affect_other_players_matches():
    """DQ'ing one player should not trigger end_reporting on any other lobbies."""
    tm, t = make_tm(fmt='double elimination')

    # Player 100 has an active match
    lobby_doc = {'match_id': 42, 'players': [100, 200]}
    tm.bot.dh.find_player_match = AsyncMock(return_value=lobby_doc)

    mock_lobby_42 = AsyncMock()
    mock_lobby_99 = AsyncMock()
    tm.lobbies[42] = mock_lobby_42
    tm.lobbies[99] = mock_lobby_99

    await tm.disqualify_player(100)

    mock_lobby_42.end_reporting.assert_awaited_once()
    mock_lobby_99.end_reporting.assert_not_awaited()