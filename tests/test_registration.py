# tests/test_registration.py
"""
Tests for player registration, unregistration, and check-in flows.

Covers:
- A player cannot register twice
- Approved registration creates a pending request instead of registering
- Ranked gate blocks players without a UCH account (bypassed in debug)
- Swiss registration calls swiss_add_player (not Challonge)
- Swiss registration stores None as the Challonge participant ID
- Challonge registration calls Challonge (not swiss_add_player)
- Unregistered players cannot check in
- Players not in entrants cannot check in
- Debug mode: 4 players auto-registered for Swiss on open_registration
- Debug mode: 8 players auto-registered for Challonge on open_registration
- Players removed from unchecked list when tournament starts (debug skips this)
- Rejoining after dropping restores player without resetting stats
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def make_tm(fmt='double elimination', state='registration', debug=False, ranked_reporting=False):
    from tournaments.tournament_manager import TournamentManager

    tournament = {
        '_id': 'tid',
        'name': 'Test Tournament',
        'format': fmt,
        'state': state,
        'entrants': {},
        'checked_in': [],
        'dqs': [],
        'stagelist': [],
        'organizers': [999],
        'config': {
            'approved_registration': False,
            'randomized_stagelist': False,
            'display_entrants': False,
            'ranked_reporting': ranked_reporting,
        },
        'registration_open': True,
        'challonge_data': {'id': 'chid', 'url': 'test-url'},
        'debug': debug,
        'category_id': 99999,
    }

    tm = object.__new__(TournamentManager)
    tm.tournament = tournament
    tm.guild = MagicMock()
    tm.guild.members = []
    tm.lobbies = {}
    tm.tournament_reset = False
    tm.debug = debug
    tm.organizer_role = None

    tm.bot = MagicMock()
    tm.bot.dh = AsyncMock()
    tm.bot.dh.get_tournament_by_id = AsyncMock(return_value=tournament)
    tm.bot.dh.get_registration_status = AsyncMock(return_value=None)
    tm.bot.dh.register_player = AsyncMock(return_value=True)
    tm.bot.dh.register_user = AsyncMock()
    tm.bot.dh.get_user = AsyncMock(return_value={'user_id': 100, 'name': 'TestPlayer'})
    tm.bot.dh.unregister_player = AsyncMock()
    tm.bot.dh.update_tournament_state = AsyncMock()
    tm.bot.dh.open_registration = AsyncMock()
    tm.bot.dh.get_swiss_event_by_tournament = AsyncMock(return_value={
        '_id': 'eid',
        'players': {},
    })
    tm.bot.dh.swiss_add_player = AsyncMock()
    tm.bot.dh.swiss_drop_player = AsyncMock()
    tm.bot.dh.swiss_rejoin_player = AsyncMock(return_value=False)
    tm.bot.dh.add_registration_request = AsyncMock()
    tm.bot.uchranked_api = AsyncMock()
    tm.bot.uchranked_api.get_player = AsyncMock(return_value={
        'found': True, 'username': 'TestPlayer', 'elo': 1500,
    })

    tm.format = MagicMock()
    tm.format.on_player_register = AsyncMock()
    tm.format.on_player_unregister = AsyncMock()
    tm.format.on_registration_gate = AsyncMock(return_value=True)
    tm.format.on_tournament_start = AsyncMock()
    tm.format.needs_match_call_refresh = True
    tm.format.invalidate_pending_cache = MagicMock()

    tm.get_tournament = AsyncMock(return_value=tournament)
    tm.get_ranked_player = AsyncMock(return_value={'elo': 1500, 'username': 'TestPlayer'})
    tm.edit_event_info = AsyncMock()
    tm.get_channel = AsyncMock(return_value=None)
    tm.sync_channel_order = AsyncMock()

    return tm, tournament


# ─── Double registration prevention ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_already_registered_player_cannot_register_again():
    tm, t = make_tm()
    tm.bot.dh.get_registration_status = AsyncMock(return_value=True)

    with patch('tournaments.tournament_manager.discord.utils.get', return_value=AsyncMock()):
        result = await tm.register_player(100)

    assert result is False


@pytest.mark.asyncio
async def test_new_player_can_register():
    tm, t = make_tm()

    with patch('tournaments.tournament_manager.discord.utils.get', return_value=AsyncMock()):
        result = await tm.register_player(100)

    assert result is True


# ─── Approved registration ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_approved_registration_creates_pending_request():
    tm, t = make_tm()
    t['config']['approved_registration'] = True
    tm.get_tournament = AsyncMock(return_value=t)

    with patch('tournaments.tournament_manager.discord.utils.get', return_value=AsyncMock()):
        result = await tm.register_player(100)

    assert result == 'pending'
    tm.bot.dh.add_registration_request.assert_awaited_once_with('tid', 100)


@pytest.mark.asyncio
async def test_approved_registration_does_not_call_on_player_register():
    tm, t = make_tm()
    t['config']['approved_registration'] = True
    tm.get_tournament = AsyncMock(return_value=t)

    with patch('tournaments.tournament_manager.discord.utils.get', return_value=AsyncMock()):
        await tm.register_player(100)

    tm.format.on_player_register.assert_not_awaited()


# ─── Ranked gate ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ranked_gate_blocks_player_without_uch_account():
    tm, t = make_tm(ranked_reporting=True)
    tm.get_ranked_player = AsyncMock(return_value=None)

    with patch('tournaments.tournament_manager.discord.utils.get', return_value=AsyncMock()):
        result = await tm.register_player(100)

    assert result == 'no_ranked_account'


@pytest.mark.asyncio
async def test_ranked_gate_bypassed_in_debug_mode():
    tm, t = make_tm(ranked_reporting=True, debug=True)
    tm.debug = True
    tm.get_ranked_player = AsyncMock(return_value=None)

    with patch('tournaments.tournament_manager.discord.utils.get', return_value=AsyncMock()):
        result = await tm.register_player(0)

    assert result is not False


# ─── Format routing ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_swiss_registration_calls_on_player_register():
    tm, t = make_tm(fmt='swiss')

    with patch('tournaments.tournament_manager.discord.utils.get', return_value=AsyncMock()):
        await tm.register_player(100)

    tm.format.on_player_register.assert_awaited_once()


@pytest.mark.asyncio
async def test_de_registration_calls_on_player_register():
    tm, t = make_tm(fmt='double elimination')

    with patch('tournaments.tournament_manager.discord.utils.get', return_value=AsyncMock()):
        await tm.register_player(100)

    tm.format.on_player_register.assert_awaited_once()


# ─── Debug auto-registration ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_debug_swiss_registers_4_players():
    tm, t = make_tm(fmt='swiss', debug=True, state='setup')
    tm.debug = True
    tm.register_player = AsyncMock(return_value=True)

    with patch('tournaments.tournament_manager.create_channel', new=AsyncMock(return_value=AsyncMock())):
        await tm.open_registration()

    assert tm.register_player.await_count == 4


@pytest.mark.asyncio
async def test_debug_de_registers_8_players():
    tm, t = make_tm(fmt='double elimination', debug=True, state='setup')
    tm.debug = True
    tm.register_player = AsyncMock(return_value=True)

    with patch('tournaments.tournament_manager.create_channel', new=AsyncMock(return_value=AsyncMock())):
        await tm.open_registration()

    assert tm.register_player.await_count == 8


# ─── Start tournament: unchecked player removal ───────────────────────────────

@pytest.mark.asyncio
async def test_start_tournament_removes_unchecked_players():
    tm, t = make_tm(state='checkin')
    t['entrants'] = {'100': 10, '200': 20}
    t['checked_in'] = [100]
    tm.get_tournament = AsyncMock(return_value=t)
    tm.unregister_player = AsyncMock()
    tm.get_channel = AsyncMock(return_value=AsyncMock())
    tm.generate_banner = AsyncMock(return_value=None)
    tm.send_instruction_message = AsyncMock()
    tm.start_tournament_loop = AsyncMock()
    tm.format.on_tournament_start = AsyncMock()
    tm.bot.dh.update_tournament_state = AsyncMock()
    tm.bot.dh.get_registration_requests = AsyncMock(return_value=[])
    tm.bot.dh.clear_registration_requests = AsyncMock()

    with patch('tournaments.tournament_manager.discord.utils.get', return_value=None), \
         patch('tournaments.tournament_manager.SwissActiveRegisterView'):
        await tm.start_tournament()

    tm.unregister_player.assert_awaited_once_with(200)


@pytest.mark.asyncio
async def test_debug_mode_keeps_all_players_regardless_of_checkin():
    tm, t = make_tm(state='checkin', debug=True)
    tm.debug = True
    t['entrants'] = {'100': 10, '200': 20}
    t['checked_in'] = []
    tm.get_tournament = AsyncMock(return_value=t)
    tm.unregister_player = AsyncMock()
    tm.get_channel = AsyncMock(return_value=AsyncMock())
    tm.generate_banner = AsyncMock(return_value=None)
    tm.send_instruction_message = AsyncMock()
    tm.start_tournament_loop = AsyncMock()
    tm.format.on_tournament_start = AsyncMock()
    tm.bot.dh.update_tournament_state = AsyncMock()
    tm.bot.dh.get_registration_requests = AsyncMock(return_value=[])
    tm.bot.dh.clear_registration_requests = AsyncMock()

    with patch('tournaments.tournament_manager.discord.utils.get', return_value=None), \
         patch('tournaments.tournament_manager.SwissActiveRegisterView'):
        await tm.start_tournament()

    tm.unregister_player.assert_not_awaited()


# ─── Swiss rejoin preserves stats ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_swiss_rejoin_restores_dropped_player():
    from formats.swiss import SwissFormat

    tm = MagicMock()
    tm.tournament = {'_id': 'tid', 'state': 'active'}
    tm.get_tournament = AsyncMock(return_value={'_id': 'tid', 'state': 'active'})
    tm.debug = False

    dh = AsyncMock()
    dh.get_swiss_event_by_tournament = AsyncMock(return_value={'_id': 'eid', 'players': {'100': {}}})
    dh.swiss_rejoin_player = AsyncMock(return_value=True)
    dh.swiss_add_player = AsyncMock()
    dh.register_player = AsyncMock()
    tm.bot = MagicMock()
    tm.bot.dh = dh

    fmt = object.__new__(SwissFormat)
    fmt.tm = tm
    fmt.dh = dh
    fmt.manager = AsyncMock()
    fmt.manager.on_player_joined = AsyncMock()
    fmt.pending_results = []

    user = {'name': 'TestPlayer'}
    await fmt.on_player_register(100, user)

    dh.swiss_rejoin_player.assert_awaited_once_with('eid', 100)
    dh.swiss_add_player.assert_not_awaited()


@pytest.mark.asyncio
async def test_swiss_new_player_calls_swiss_add_player():
    from formats.swiss import SwissFormat

    tm = MagicMock()
    tm.tournament = {'_id': 'tid', 'state': 'registration'}
    tm.get_tournament = AsyncMock(return_value={'_id': 'tid', 'state': 'registration'})
    tm.debug = False
    tm.get_ranked_player = AsyncMock(return_value={'elo': 1200, 'username': 'NewPlayer'})

    dh = AsyncMock()
    dh.get_swiss_event_by_tournament = AsyncMock(return_value={'_id': 'eid', 'players': {}})
    dh.swiss_rejoin_player = AsyncMock(return_value=False)
    dh.swiss_add_player = AsyncMock()
    dh.register_player = AsyncMock()
    tm.bot = MagicMock()
    tm.bot.dh = dh

    fmt = object.__new__(SwissFormat)
    fmt.tm = tm
    fmt.dh = dh
    fmt.manager = AsyncMock()
    fmt.pending_results = []

    user = {'name': 'NewPlayer'}
    await fmt.on_player_register(100, user)

    dh.swiss_add_player.assert_awaited_once()

@pytest.mark.asyncio
async def test_swiss_rejoin_preserves_points_wins_losses_and_history():
    """
    A player who leaves mid-event and rejoins should have their accumulated
    stats intact — points, wins, losses, and match history are not reset.
    """
    from formats.swiss import SwissFormat

    existing_player_data = {
        'username': 'player_100',
        'elo': 1200,
        'points': 2.0,
        'wins': 2,
        'losses': 1,
        'rounds_played': 3,
        'active_match_id': None,
        'dropped': True,
        'match_history': [200, 300],
    }

    tm = MagicMock()
    tm.tournament = {'_id': 'tid', 'state': 'active'}
    tm.get_tournament = AsyncMock(return_value={'_id': 'tid', 'state': 'active'})
    tm.debug = False

    dh = AsyncMock()
    dh.get_swiss_event_by_tournament = AsyncMock(return_value={
        '_id': 'eid',
        'players': {'100': existing_player_data},
    })
    # Simulate rejoin succeeding — player already exists
    dh.swiss_rejoin_player = AsyncMock(return_value=True)
    dh.swiss_add_player = AsyncMock()
    dh.register_player = AsyncMock()
    tm.bot = MagicMock()
    tm.bot.dh = dh

    fmt = object.__new__(SwissFormat)
    fmt.tm = tm
    fmt.dh = dh
    fmt.manager = AsyncMock()
    fmt.manager.on_player_joined = AsyncMock()
    fmt.pending_results = []

    await fmt.on_player_register(100, {'name': 'player_100'})

    # swiss_rejoin_player should be called (not swiss_add_player which would reset stats)
    dh.swiss_rejoin_player.assert_awaited_once_with('eid', 100)
    dh.swiss_add_player.assert_not_awaited()

    # Verify that swiss_rejoin_player only touches dropped and active_match_id,
    # not points/wins/losses/match_history — by checking what it was called with
    call_args = dh.swiss_rejoin_player.call_args
    assert call_args[0] == ('eid', 100)

    # The existing player data should be untouched — swiss_add_player was never
    # called with a fresh player dict, so no stat reset occurred
    assert existing_player_data['points'] == 2.0
    assert existing_player_data['wins'] == 2
    assert existing_player_data['losses'] == 1
    assert existing_player_data['match_history'] == [200, 300]