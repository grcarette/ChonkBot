# tests/test_tournament_lifecycle.py
"""
Tests for tournament state progression.

Covers:
- Each state transitions to the correct next state
- Pre-transition tasks run before the DB commit
- Revert from checkin → registration
- Revert from active → checkin clears lobbies and lobby DB records
- Delete removes all lobby DB records
- Delete on a finished tournament is a no-op
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call


def make_tm(state='setup', fmt='double elimination', debug=False):
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
        },
        'registration_open': False,
        'challonge_data': {'id': 'chid', 'url': 'test-url'},
        'debug': debug,
        'category_id': 12345,
    }

    tm = object.__new__(TournamentManager)
    tm.tournament = tournament
    tm.guild = MagicMock()
    tm.guild.members = []
    tm.lobbies = {}
    tm.tournament_reset = False
    tm.debug = debug
    tm.organizer_role = None
    tm.format = MagicMock()
    tm.format.on_tournament_start = AsyncMock()
    tm.format.on_tournament_end = AsyncMock()
    tm.format.on_reset = AsyncMock()
    tm.format.on_tournament_delete = AsyncMock()
    tm.format.needs_match_call_refresh = True
    tm.format.invalidate_pending_cache = MagicMock()
    tm.format.called_match_ids = set()

    tm.bot = MagicMock()
    tm.bot.dh = AsyncMock()
    tm.bot.dh.get_tournament_by_id = AsyncMock(return_value=tournament)
    tm.bot.dh.update_tournament_state = AsyncMock()
    tm.bot.dh.clear_lobbies = AsyncMock()
    tm.bot.dh.delete_tournament = AsyncMock()
    tm.bot.dh.clear_checkin = AsyncMock()
    tm.bot.dh.open_registration = AsyncMock()
    tm.bot.dh.get_swiss_event_by_tournament = AsyncMock(return_value=None)

    tm.bot.th = MagicMock()
    tm.bot.th.tournaments = {}

    # Stub heavy methods
    tm.publish_tournament = AsyncMock()
    tm.open_registration = AsyncMock()
    tm.start_checkin = AsyncMock()
    tm.start_tournament = AsyncMock()
    tm.end_tournament = AsyncMock()
    tm.finalize_tournament = AsyncMock()
    tm.remove_tournament_from_discord = AsyncMock()
    tm.get_channel = AsyncMock(return_value=None)
    tm.set_registration_visibility = AsyncMock()
    tm.send_checkin_message = AsyncMock()
    tm.stop_checkin_reminder_loop = MagicMock()

    return tm, tournament


# ─── State transitions ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_initialize_transitions_to_setup():
    tm, t = make_tm(state='initialize')
    await tm.progress_tournament()
    tm.bot.dh.update_tournament_state.assert_awaited_once_with('tid', 'setup')


@pytest.mark.asyncio
async def test_setup_transitions_to_registration():
    tm, t = make_tm(state='setup')
    await tm.progress_tournament()
    tm.bot.dh.update_tournament_state.assert_awaited_once_with('tid', 'registration')


@pytest.mark.asyncio
async def test_registration_transitions_to_checkin():
    tm, t = make_tm(state='registration')
    await tm.progress_tournament()
    tm.bot.dh.update_tournament_state.assert_awaited_once_with('tid', 'checkin')


@pytest.mark.asyncio
async def test_checkin_transitions_to_active():
    tm, t = make_tm(state='checkin')
    await tm.progress_tournament()
    tm.bot.dh.update_tournament_state.assert_awaited_once_with('tid', 'active')


@pytest.mark.asyncio
async def test_active_transitions_to_finished():
    tm, t = make_tm(state='active')
    await tm.progress_tournament()
    tm.bot.dh.update_tournament_state.assert_awaited_once_with('tid', 'finished')


@pytest.mark.asyncio
async def test_finished_transitions_to_finalized():
    tm, t = make_tm(state='finished')
    await tm.progress_tournament()
    tm.bot.dh.update_tournament_state.assert_awaited_once_with('tid', 'finalized')


# ─── Pre-transition task ordering ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_publish_and_open_reg_run_before_db_commit_on_setup():
    tm, t = make_tm(state='setup')
    order = []
    tm.publish_tournament = AsyncMock(side_effect=lambda: order.append('publish'))
    tm.open_registration = AsyncMock(side_effect=lambda: order.append('open_reg'))
    tm.bot.dh.update_tournament_state = AsyncMock(side_effect=lambda *a: order.append('db'))

    await tm.progress_tournament()

    assert order.index('publish') < order.index('db')
    assert order.index('open_reg') < order.index('db')


@pytest.mark.asyncio
async def test_start_tournament_runs_before_db_commit_on_checkin():
    tm, t = make_tm(state='checkin')
    order = []
    tm.start_tournament = AsyncMock(side_effect=lambda: order.append('start'))
    tm.bot.dh.update_tournament_state = AsyncMock(side_effect=lambda *a: order.append('db'))

    await tm.progress_tournament()

    assert order.index('start') < order.index('db')


# ─── Revert: checkin → registration ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_revert_checkin_deletes_checkin_channel():
    tm, t = make_tm(state='checkin')
    checkin_channel = AsyncMock()
    tm.get_channel = AsyncMock(side_effect=lambda name: checkin_channel if name == 'check-in' else None)
    tm.bot.dh.get_tournament_by_id = AsyncMock(return_value={**t, 'state': 'checkin'})

    await tm.revert_tournament()

    checkin_channel.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_revert_checkin_clears_checkin_list():
    tm, t = make_tm(state='checkin')
    tm.get_channel = AsyncMock(return_value=None)
    tm.bot.dh.get_tournament_by_id = AsyncMock(return_value={**t, 'state': 'checkin'})

    await tm.revert_tournament()

    tm.bot.dh.clear_checkin.assert_awaited_once_with('tid')


@pytest.mark.asyncio
async def test_revert_checkin_opens_registration():
    tm, t = make_tm(state='checkin')
    tm.get_channel = AsyncMock(return_value=None)
    tm.bot.dh.get_tournament_by_id = AsyncMock(return_value={**t, 'state': 'checkin'})

    await tm.revert_tournament()

    tm.bot.dh.open_registration.assert_awaited_once_with('tid')


@pytest.mark.asyncio
async def test_revert_checkin_sets_state_to_registration():
    tm, t = make_tm(state='checkin')
    tm.get_channel = AsyncMock(return_value=None)
    tm.bot.dh.get_tournament_by_id = AsyncMock(return_value={**t, 'state': 'checkin'})

    await tm.revert_tournament()

    tm.bot.dh.update_tournament_state.assert_awaited_once_with('tid', 'registration')


# ─── Revert: active → checkin ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_revert_active_clears_all_lobby_db_records():
    tm, t = make_tm(state='active')
    tm.bot.dh.get_tournament_by_id = AsyncMock(return_value={**t, 'state': 'active'})
    tm.start_checkin = AsyncMock()

    await tm.revert_tournament()

    tm.bot.dh.clear_lobbies.assert_awaited_with('tid')


@pytest.mark.asyncio
async def test_revert_active_closes_in_memory_lobbies():
    tm, t = make_tm(state='active')
    tm.bot.dh.get_tournament_by_id = AsyncMock(return_value={**t, 'state': 'active'})
    tm.start_checkin = AsyncMock()

    lobby1 = AsyncMock()
    lobby2 = AsyncMock()
    tm.lobbies = {1: lobby1, 2: lobby2}

    await tm.revert_tournament()

    lobby1.delete_lobby.assert_awaited_once()
    lobby2.delete_lobby.assert_awaited_once()


@pytest.mark.asyncio
async def test_revert_active_calls_format_on_reset():
    tm, t = make_tm(state='active')
    tm.bot.dh.get_tournament_by_id = AsyncMock(return_value={**t, 'state': 'active'})
    tm.start_checkin = AsyncMock()

    await tm.revert_tournament()

    tm.format.on_reset.assert_awaited_once()


@pytest.mark.asyncio
async def test_revert_active_sets_state_to_checkin():
    tm, t = make_tm(state='active')
    tm.bot.dh.get_tournament_by_id = AsyncMock(return_value={**t, 'state': 'active'})
    tm.start_checkin = AsyncMock()

    await tm.revert_tournament()

    tm.bot.dh.update_tournament_state.assert_awaited_once_with('tid', 'checkin')


# ─── Delete tournament ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_clears_all_lobby_db_records():
    tm, t = make_tm(state='active')
    tm.bot.dh.get_tournament_by_id = AsyncMock(return_value={**t, 'state': 'active'})

    await tm.delete_tournament()

    tm.bot.dh.clear_lobbies.assert_awaited_once_with('tid')


@pytest.mark.asyncio
async def test_delete_deletes_in_memory_lobbies():
    tm, t = make_tm(state='active')
    tm.bot.dh.get_tournament_by_id = AsyncMock(return_value={**t, 'state': 'active'})

    lobby = AsyncMock()
    tm.lobbies = {1: lobby}

    await tm.delete_tournament()

    lobby.delete_lobby.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_finished_tournament_is_noop():
    tm, t = make_tm(state='finished')
    tm.bot.dh.get_tournament_by_id = AsyncMock(return_value={**t, 'state': 'finished'})

    result = await tm.delete_tournament()

    assert result is False
    tm.bot.dh.delete_tournament.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_removes_tournament_from_db():
    tm, t = make_tm(state='active')
    tm.bot.dh.get_tournament_by_id = AsyncMock(return_value={**t, 'state': 'active'})

    await tm.delete_tournament()

    tm.bot.dh.delete_tournament.assert_awaited_once_with('tid')


@pytest.mark.asyncio
async def test_delete_calls_format_on_tournament_delete():
    tm, t = make_tm(state='active')
    tm.bot.dh.get_tournament_by_id = AsyncMock(return_value={**t, 'state': 'active'})

    await tm.delete_tournament()

    tm.format.on_tournament_delete.assert_awaited_once()