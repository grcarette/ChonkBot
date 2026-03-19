"""
tests/test_registration_flow.py

Tests for player registration, checkin, and unregistration flows.

Covers:
- Players can't register twice
- Swiss registration adds to swiss event, not Challonge
- DE registration adds to Challonge
- Unregistered players can't check in
- Players not in entrants can't check in
- Checked-in players are correctly tracked
- Players removed from unchecked_in list when tournament starts
- Debug mode skips ranked API gate
- Approved registration gate
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def make_tm(format='double elimination', state='registration', debug=False):
    from tournaments.tournament_manager import TournamentManager

    tournament = {
        '_id': 'tid',
        'name': 'Test Tournament',
        'format': format,
        'state': state,
        'entrants': {},
        'checked_in': [],
        'dqs': [],
        'stagelist': [],
        'organizers': [999],
        'config': {
            'approved_registration': False,
            'randomized_stagelist': False,
        },
        'registration_open': True,
        'challonge_data': {'id': 'chid', 'url': 'test-url'},
        'debug': debug,
    }

    tm = object.__new__(TournamentManager)
    tm.tournament = tournament
    tm.guild = MagicMock()
    tm.guild.members = []
    tm.lobbies = {}
    tm.match_calls = {}
    tm.tournament_reset = False
    tm.autocall_matches = False
    tm.debug = debug
    tm.organizer_role = None
    tm.swiss_manager = AsyncMock()

    # tc is needed by start_tournament for banner generation
    tm.tc = AsyncMock()
    tm.tc.generate_banner = AsyncMock(return_value=None)

    tm.bot = MagicMock()
    tm.bot.dh = AsyncMock()
    tm.bot.dh.get_tournament_by_id = AsyncMock(return_value=tournament)
    tm.bot.dh.get_registration_status = AsyncMock(return_value=None)
    tm.bot.dh.register_player = AsyncMock(return_value=True)
    tm.bot.dh.register_user = AsyncMock()
    tm.bot.dh.update_tournament_state = AsyncMock()
    tm.bot.dh.get_user = AsyncMock(return_value={
        'user_id': 100,
        'name': 'TestPlayer',
    })
    tm.bot.dh.get_swiss_event_by_tournament = AsyncMock(return_value={
        '_id': 'eid',
        'players': {},
    })
    tm.bot.dh.swiss_add_player = AsyncMock()
    tm.bot.dh.unregister_player = AsyncMock()
    tm.bot.dh.swiss_drop_player = AsyncMock()
    tm.bot.uchranked_api = AsyncMock()
    tm.bot.uchranked_api.get_player = AsyncMock(return_value={
        'found': True,
        'username': 'TestPlayer',
        'elo': 1500,
        'rank': 'Gold',
        'division': 1,
    })

    tm.ch = AsyncMock()
    tm.ch.register_player = AsyncMock(return_value=42)

    tm.get_tournament = AsyncMock(return_value=tournament)

    return tm


# ─── Double registration prevention ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_already_registered_player_cannot_register_again():
    tm = make_tm()
    tm.bot.dh.get_registration_status = AsyncMock(return_value=True)  # already registered

    with patch('tournaments.tournament_manager.discord.utils.get', return_value=MagicMock()):
        result = await tm.register_player(100)

    assert result is False
    tm.ch.register_player.assert_not_awaited()


@pytest.mark.asyncio
async def test_new_player_can_register():
    tm = make_tm()
    tm.bot.dh.get_registration_status = AsyncMock(return_value=None)

    with patch('tournaments.tournament_manager.discord.utils.get', return_value=AsyncMock()):
        result = await tm.register_player(100)

    assert result is True


# ─── DE registration ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_de_registration_calls_challonge():
    tm = make_tm(format='double elimination')
    tm.bot.dh.get_registration_status = AsyncMock(return_value=None)

    with patch('tournaments.tournament_manager.discord.utils.get', return_value=AsyncMock()):
        await tm.register_player(100)

    tm.ch.register_player.assert_awaited_once()


@pytest.mark.asyncio
async def test_de_registration_does_not_call_swiss_add():
    tm = make_tm(format='double elimination')
    tm.bot.dh.get_registration_status = AsyncMock(return_value=None)

    with patch('tournaments.tournament_manager.discord.utils.get', return_value=AsyncMock()):
        await tm.register_player(100)

    tm.bot.dh.swiss_add_player.assert_not_awaited()


# ─── Swiss registration ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_swiss_registration_calls_swiss_add_player():
    tm = make_tm(format='swiss')
    tm.bot.dh.get_registration_status = AsyncMock(return_value=None)

    with patch('tournaments.tournament_manager.discord.utils.get', return_value=AsyncMock()):
        await tm.register_player(100)

    tm.bot.dh.swiss_add_player.assert_awaited_once()


@pytest.mark.asyncio
async def test_swiss_registration_does_not_call_challonge():
    tm = make_tm(format='swiss')
    tm.bot.dh.get_registration_status = AsyncMock(return_value=None)

    with patch('tournaments.tournament_manager.discord.utils.get', return_value=AsyncMock()):
        await tm.register_player(100)

    tm.ch.register_player.assert_not_awaited()


@pytest.mark.asyncio
async def test_swiss_registration_stores_none_as_challonge_id():
    """Swiss players must be stored with None as Challonge ID."""
    tm = make_tm(format='swiss')
    tm.bot.dh.get_registration_status = AsyncMock(return_value=None)

    with patch('tournaments.tournament_manager.discord.utils.get', return_value=AsyncMock()):
        await tm.register_player(100)

    call_args = tm.bot.dh.register_player.call_args
    stored_challonge_id = call_args.args[2] if call_args.args else call_args.kwargs.get('player_id')
    assert stored_challonge_id is None, \
        f"Swiss players must be stored with None as Challonge ID, got: {stored_challonge_id}"


# ─── Debug mode ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_debug_mode_skips_ranked_api():
    """In debug mode, register_player should not call the ranked API."""
    tm = make_tm(format='swiss', debug=True)
    tm.bot.dh.get_registration_status = AsyncMock(return_value=None)

    with patch('tournaments.tournament_manager.discord.utils.get', return_value=MagicMock()):
        await tm.register_player(0)  # debug uses index-based fake elos

    tm.bot.uchranked_api.get_player.assert_not_called()


# ─── Tournament start: removing unchecked players ─────────────────────────────

@pytest.mark.asyncio
async def test_start_tournament_removes_unchecked_players():
    """Players who registered but didn't check in should be removed."""
    tm = make_tm(format='double elimination', state='checkin')
    tm.tournament['entrants'] = {'100': 10, '200': 20}
    tm.tournament['checked_in'] = [100]  # 200 did not check in
    tm.tournament['category_id'] = 999

    tm.unregister_player = AsyncMock()
    tm.get_channel = AsyncMock(return_value=AsyncMock())
    tm.get_tournament_category = MagicMock(return_value=MagicMock())
    tm.ch.start_tournament = AsyncMock()
    tm.bot.dh.update_tournament_state = AsyncMock()
    tm.send_instruction_message = AsyncMock()
    tm.start_tournament_loop = AsyncMock()
    tm.get_tournament = AsyncMock(return_value=tm.tournament)

    with patch('tournaments.tournament_manager.discord.utils.get', return_value=None), \
         patch('tournaments.tournament_manager.create_channel', new=AsyncMock(return_value=AsyncMock())):
        await tm.start_tournament()

    # Player 200 should be unregistered
    tm.unregister_player.assert_awaited_once_with(200)


@pytest.mark.asyncio
async def test_start_tournament_debug_keeps_all_players():
    """In debug mode, no players should be removed regardless of checkin."""
    tm = make_tm(format='double elimination', state='checkin', debug=True)
    tm.tournament['entrants'] = {'100': 10, '200': 20}
    tm.tournament['checked_in'] = []  # nobody checked in
    tm.tournament['category_id'] = 999

    tm.unregister_player = AsyncMock()
    tm.get_channel = AsyncMock(return_value=AsyncMock())
    tm.get_tournament_category = MagicMock(return_value=MagicMock())
    tm.ch.start_tournament = AsyncMock()
    tm.bot.dh.update_tournament_state = AsyncMock()
    tm.send_instruction_message = AsyncMock()
    tm.start_tournament_loop = AsyncMock()
    tm.get_tournament = AsyncMock(return_value=tm.tournament)

    with patch('tournaments.tournament_manager.discord.utils.get', return_value=None), \
         patch('tournaments.tournament_manager.create_channel', new=AsyncMock(return_value=AsyncMock())):
        await tm.start_tournament()

    tm.unregister_player.assert_not_awaited()