"""
tests/test_tournament_lifecycle.py

Tests for the full tournament state machine — from initialize through finalized.

These tests focus on:
- State transitions happening in the correct order
- Pre-transition tasks running BEFORE state is committed to DB (the bug we fixed)
- Each state only calling the side effects appropriate to it
- Swiss and DE following the same state machine but with different side effects

All Discord and DB calls are mocked. These tests verify orchestration logic,
not the internals of each individual method.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, call, patch


# ─── Shared factory ───────────────────────────────────────────────────────────

def make_tm(format='double elimination', state='initialize'):
    """Build a TournamentManager with all external dependencies mocked."""
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
        'organizers': [],
        'config': {'approved_registration': False, 'randomized_stagelist': False},
        'registration_open': False,
        'challonge_data': {'id': 'chid', 'url': 'test-url'},
        'debug': False,
    }

    tm = object.__new__(TournamentManager)
    tm.tournament = tournament
    tm.guild = MagicMock()
    tm.lobbies = {}
    tm.match_calls = {}
    tm.tournament_reset = False
    tm.autocall_matches = False
    tm.debug = False
    tm.organizer_role = None
    tm.swiss_manager = AsyncMock()

    tm.bot = MagicMock()
    tm.bot.dh = AsyncMock()
    tm.bot.dh.get_tournament_by_id = AsyncMock(return_value=tournament)
    tm.bot.dh.update_tournament_state = AsyncMock()
    tm.bot.dh.clear_lobbies = AsyncMock()

    tm.ch = AsyncMock()

    # tc (TournamentControl) — just needs update_tournament_state
    tm.tc = AsyncMock()

    # format_handler — stub so report_match and report_match_from_result work
    # without pulling in real DEFormatHandler / SwissFormatHandler
    tm.format_handler = MagicMock()
    tm.format_handler.on_result = AsyncMock()

    # Stub out the heavy lifecycle methods so we can assert they're called
    tm.publish_tournament = AsyncMock()
    tm.open_registration = AsyncMock()
    tm.start_checkin = AsyncMock()
    tm.start_tournament = AsyncMock()
    tm.end_tournament = AsyncMock()
    tm.finalize_tournament = AsyncMock()

    # get_tournament returns the tournament dict
    tm.get_tournament = AsyncMock(return_value=tournament)

    return tm


def advance_state(tm, state):
    """Helper: set the tournament's current state so progress_tournament transitions from it."""
    tm.tournament['state'] = state
    tm.get_tournament = AsyncMock(return_value=tm.tournament)


# ─── State transition ordering ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_initialize_transitions_to_setup():
    tm = make_tm(state='initialize')
    await tm.progress_tournament()
    tm.bot.dh.update_tournament_state.assert_awaited_once_with('tid', 'setup')


@pytest.mark.asyncio
async def test_setup_transitions_to_registration():
    tm = make_tm(state='setup')
    await tm.progress_tournament()
    tm.bot.dh.update_tournament_state.assert_awaited_once_with('tid', 'registration')


@pytest.mark.asyncio
async def test_registration_transitions_to_checkin():
    tm = make_tm(state='registration')
    await tm.progress_tournament()
    tm.bot.dh.update_tournament_state.assert_awaited_once_with('tid', 'checkin')


@pytest.mark.asyncio
async def test_checkin_transitions_to_active():
    tm = make_tm(state='checkin')
    await tm.progress_tournament()
    tm.bot.dh.update_tournament_state.assert_awaited_once_with('tid', 'active')


@pytest.mark.asyncio
async def test_active_transitions_to_finished():
    tm = make_tm(state='active')
    await tm.progress_tournament()
    tm.bot.dh.update_tournament_state.assert_awaited_once_with('tid', 'finished')


@pytest.mark.asyncio
async def test_finished_transitions_to_finalized():
    tm = make_tm(state='finished')
    await tm.progress_tournament()
    tm.bot.dh.update_tournament_state.assert_awaited_once_with('tid', 'finalized')


# ─── Pre-transition tasks run BEFORE DB commit ────────────────────────────────

@pytest.mark.asyncio
async def test_setup_tasks_run_before_db_commit():
    """
    publish_tournament and open_registration must complete before
    update_tournament_state is called. This was the ordering bug we fixed.
    """
    tm = make_tm(state='setup')
    call_order = []

    async def track_publish(): call_order.append('publish')
    async def track_open_reg(): call_order.append('open_reg')
    async def track_db(*args): call_order.append('db')

    tm.publish_tournament = track_publish
    tm.open_registration = track_open_reg
    tm.bot.dh.update_tournament_state = track_db

    await tm.progress_tournament()

    assert call_order.index('publish') < call_order.index('db')
    assert call_order.index('open_reg') < call_order.index('db')


@pytest.mark.asyncio
async def test_start_tournament_runs_before_db_commit():
    """start_tournament must complete before the state is committed."""
    tm = make_tm(state='checkin')
    call_order = []

    async def track_start(): call_order.append('start')
    async def track_db(*args): call_order.append('db')

    tm.start_tournament = track_start
    tm.bot.dh.update_tournament_state = track_db

    await tm.progress_tournament()

    assert call_order.index('start') < call_order.index('db')


@pytest.mark.asyncio
async def test_end_tournament_runs_before_db_commit():
    tm = make_tm(state='active')
    call_order = []

    async def track_end(): call_order.append('end')
    async def track_db(*args): call_order.append('db')

    tm.end_tournament = track_end
    tm.bot.dh.update_tournament_state = track_db

    await tm.progress_tournament()

    assert call_order.index('end') < call_order.index('db')


# ─── Correct side effects per transition ─────────────────────────────────────

@pytest.mark.asyncio
async def test_setup_to_registration_calls_publish_and_open_reg():
    tm = make_tm(state='setup')
    await tm.progress_tournament()
    tm.publish_tournament.assert_awaited_once()
    tm.open_registration.assert_awaited_once()


@pytest.mark.asyncio
async def test_setup_to_registration_does_not_call_start_tournament():
    tm = make_tm(state='setup')
    await tm.progress_tournament()
    tm.start_tournament.assert_not_awaited()


@pytest.mark.asyncio
async def test_checkin_to_active_calls_start_tournament():
    tm = make_tm(state='checkin')
    await tm.progress_tournament()
    tm.start_tournament.assert_awaited_once()


@pytest.mark.asyncio
async def test_checkin_to_active_does_not_call_end_tournament():
    tm = make_tm(state='checkin')
    await tm.progress_tournament()
    tm.end_tournament.assert_not_awaited()


@pytest.mark.asyncio
async def test_active_to_finished_calls_end_tournament():
    tm = make_tm(state='active')
    await tm.progress_tournament()
    tm.end_tournament.assert_awaited_once()


# ─── Reset tournament ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reset_tournament_de_calls_challonge_reset():
    tm = make_tm(format='double elimination', state='active')
    tm.purge_match_calls = AsyncMock()
    tm.progress_tournament = AsyncMock()
    await tm.reset_tournament({})
    tm.ch.reset_tournament.assert_awaited_once_with('chid')


@pytest.mark.asyncio
async def test_reset_tournament_swiss_does_not_call_challonge():
    tm = make_tm(format='swiss', state='active')
    tm.purge_match_calls = AsyncMock()
    tm.progress_tournament = AsyncMock()
    await tm.reset_tournament({})
    tm.ch.reset_tournament.assert_not_awaited()


@pytest.mark.asyncio
async def test_reset_tournament_clears_all_lobbies():
    tm = make_tm(state='active')
    lobby_a = AsyncMock()
    lobby_b = AsyncMock()
    tm.lobbies = {'m1': lobby_a, 'm2': lobby_b}
    tm.purge_match_calls = AsyncMock()
    tm.progress_tournament = AsyncMock()

    await tm.reset_tournament({})

    lobby_a.delete_lobby.assert_awaited_once()
    lobby_b.delete_lobby.assert_awaited_once()


@pytest.mark.asyncio
async def test_reset_tournament_resets_db_lobbies():
    tm = make_tm(state='active')
    tm.lobbies = {}
    tm.purge_match_calls = AsyncMock()
    tm.progress_tournament = AsyncMock()

    await tm.reset_tournament({})

    tm.bot.dh.clear_lobbies.assert_awaited_once_with('tid')


@pytest.mark.asyncio
async def test_reset_tournament_returns_state_to_registration():
    tm = make_tm(state='active')
    tm.lobbies = {}
    tm.purge_match_calls = AsyncMock()
    tm.progress_tournament = AsyncMock()

    await tm.reset_tournament({})

    tm.bot.dh.update_tournament_state.assert_awaited_once_with('tid', 'registration')


# ─── DQ handling ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_disqualify_unregistered_player_returns_false():
    tm = make_tm(state='active')
    tm.bot.dh.get_registration_status = AsyncMock(return_value=None)
    result = await tm.disqualify_player(999)
    assert result is False


@pytest.mark.asyncio
async def test_disqualify_player_with_active_lobby_ends_match():
    tm = make_tm(state='active')
    tm.bot.dh.get_registration_status = AsyncMock(return_value=True)

    lobby_doc = {'match_id': 5, 'players': [100, 200]}
    tm.bot.dh.find_player_match = AsyncMock(return_value=lobby_doc)
    tm.bot.dh.disqualify_player = AsyncMock(return_value=True)

    mock_lobby = AsyncMock()
    tm.lobbies = {5: mock_lobby}

    await tm.disqualify_player(100)

    # end_reporting should be called with the OTHER player as winner
    mock_lobby.end_reporting.assert_awaited_once_with(200, is_dq=True)


@pytest.mark.asyncio
async def test_disqualify_player_with_no_active_lobby_still_marks_dq():
    tm = make_tm(state='active')
    tm.bot.dh.get_registration_status = AsyncMock(return_value=True)
    tm.bot.dh.find_player_match = AsyncMock(return_value=None)
    tm.bot.dh.disqualify_player = AsyncMock(return_value=True)

    await tm.disqualify_player(100)

    tm.bot.dh.disqualify_player.assert_awaited_once_with('tid', 100)