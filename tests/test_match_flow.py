"""
tests/test_match_flow.py

Tests for the match lobby lifecycle: from initialization through result reporting.

Covers:
- end_reporting calls the right chain of methods
- DQ matches close the lobby immediately
- end_reporting without a MatchService falls back to tournament_manager.report_match
- end_reporting with a MatchService calls match_service.record_result instead
- stage_bans with 0 stages skips straight to reporting
- format_handler.on_result routing: DE calls Challonge, Swiss calls swiss_record_result
- Swiss result triggers on_match_complete
- Swiss result does NOT call Challonge
- DE result does NOT call swiss_record_result
- DQ skips the UCH Ranked API
- report_match_from_result delegates to format_handler
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, call


def make_lobby(bracket='Winners', is_swiss=False, results=None, num_winners=1):
    """
    Build a minimal MatchLobby-like object without hitting Discord or DB.
    match_service defaults to None (rehydrated lobby path).
    """
    from tournaments.match_lobby import MatchLobby

    format = 'swiss' if is_swiss else 'double elimination'

    lobby = object.__new__(MatchLobby)
    lobby.match_id = 10
    lobby.lobby_name = 'wr1-Player1 vs Player2'
    lobby.bracket = bracket
    lobby.players = [100, 200]
    lobby.remaining_players = {100, 200}
    lobby.stages = ['stage1', 'stage2', 'stage3']
    lobby.num_winners = num_winners
    lobby.channel = AsyncMock()
    lobby.guild = MagicMock()
    lobby.prereq_matches = []
    lobby.match_service = None  # default: rehydrated lobby, no service

    tournament = {
        '_id': 'tid',
        'name': 'Test Tournament',
        'format': format,
        'entrants': {'100': 10, '200': 20},
        'dqs': [],
        'challonge_data': {'url': 'test-url', 'id': 'chid'},
    }
    lobby.tournament = tournament

    tm = MagicMock()
    tm.tournament = tournament
    tm.report_match = AsyncMock()
    lobby.tournament_manager = tm

    lobby.dh = AsyncMock()
    lobby.dh.get_lobby = AsyncMock(return_value={
        'results': [100],       # ← only the winner, matching num_winners=1
        'players': [100, 200],
        'picked_stage': 'stage1',
    })
    lobby.dh.report_match = AsyncMock()
    lobby.dh.report_dq = AsyncMock()
    lobby.dh.update_lobby_state = AsyncMock()
    lobby.dh.end_match = AsyncMock()
    lobby.dh.get_stage = AsyncMock(return_value={'name': 'Stage One', 'code': 'stage1'})
    lobby.dh.pick_lobby_stage = AsyncMock()

    lobby.organizer_role = 'Test Tournament TO'

    return lobby


def make_tm_for_report(format='double elimination'):
    from tournaments.tournament_manager import TournamentManager
    from formats import make_format

    tournament = {
        '_id': 'tid',
        'name': 'Test',
        'format': format,
        'entrants': {'100': 10, '200': 20},
        'challonge_data': {'url': 'test-url', 'id': 'chid'},
        'debug': False,
        'dqs': [],
    }

    tm = object.__new__(TournamentManager)
    tm.tournament = tournament
    tm.debug = False
    tm.tournament_reset = False
    tm.lobbies = {}
    tm.match_calls = {}
    tm.swiss_manager = None
    tm.guild = MagicMock()

    tm.bot = MagicMock()
    tm.bot.dh = AsyncMock()
    tm.bot.dh.get_tournament_by_id = AsyncMock(return_value=tournament)
    tm.bot.dh.swiss_record_result = AsyncMock()
    tm.bot.dh.get_swiss_event_by_tournament = AsyncMock(return_value={'_id': 'eid'})
    tm.bot.uchranked_api = AsyncMock()
    tm.bot.uchranked_api.report_match = AsyncMock(return_value={'success': True})

    tm.ch = AsyncMock()
    tm.ch.report_match = AsyncMock()
    tm.ch.check_tournament_status = AsyncMock(return_value='underway')

    tm.get_tournament = AsyncMock(return_value=tournament)
    tm.close_prereqs = AsyncMock()
    tm.call_matches = AsyncMock()
    tm.prompt_end_tournament = AsyncMock()

    tm.format = make_format(tm)

    if format in ('double elimination', 'single elimination'):
        tm.format.ch = tm.ch
    elif format == 'swiss':
        mock_manager = AsyncMock()
        tm.format.manager = mock_manager
        tm.swiss_manager = mock_manager

    return tm


# ─── end_reporting — rehydrated lobby (no MatchService) ──────────────────────

@pytest.mark.asyncio
async def test_end_reporting_calls_dh_report_match():
    """MatchLobby.report_match always writes the result to the DB regardless of path."""
    lobby = make_lobby()
    lobby.send_player_instructions = AsyncMock()
    lobby.close_lobby = AsyncMock()

    lobby.dh.get_lobby = AsyncMock(return_value={
        'results': [100],       # ← only the winner, matching num_winners=1
        'players': [100, 200],
        'picked_stage': 'stage1',
    })

    await lobby.end_reporting(winner_id=100)
    lobby.dh.report_match.assert_awaited_once_with(10, 100)


@pytest.mark.asyncio
async def test_end_reporting_without_service_calls_tournament_manager_report():
    """
    Rehydrated lobbies (match_service=None) fall back to
    tournament_manager.report_match for format-specific result handling.
    """
    lobby = make_lobby()
    lobby.match_service = None
    lobby.send_player_instructions = AsyncMock()
    lobby.close_lobby = AsyncMock()

    lobby.dh.get_lobby = AsyncMock(return_value={
        'results': [100],       # ← only the winner, matching num_winners=1
        'players': [100, 200],
        'picked_stage': 'stage1',
    })

    await lobby.end_reporting(winner_id=100)
    lobby.tournament_manager.report_match.assert_awaited_once()


@pytest.mark.asyncio
async def test_end_reporting_with_service_calls_record_result():
    """
    New matches (with a MatchService) call match_service.record_result,
    not tournament_manager.report_match directly.
    """
    lobby = make_lobby()
    lobby.match_service = AsyncMock()
    lobby.send_player_instructions = AsyncMock()
    lobby.close_lobby = AsyncMock()

    lobby.dh.get_lobby = AsyncMock(return_value={
        'results': [100],       # ← only the winner, matching num_winners=1
        'players': [100, 200],
        'picked_stage': 'stage1',
    })

    await lobby.end_reporting(winner_id=100)
    lobby.match_service.record_result.assert_awaited_once_with(100, 200, False)
    lobby.tournament_manager.report_match.assert_not_awaited()


@pytest.mark.asyncio
async def test_end_reporting_with_service_passes_is_dq():
    """is_dq is forwarded correctly through the MatchService path."""
    lobby = make_lobby()
    lobby.match_service = AsyncMock()
    lobby.send_player_instructions = AsyncMock()
    lobby.close_lobby = AsyncMock()

    lobby.dh.get_lobby = AsyncMock(return_value={
        'results': [100],       # ← only the winner, matching num_winners=1
        'players': [100, 200],
        'picked_stage': 'stage1',
    })

    await lobby.end_reporting(winner_id=100, is_dq=True)
    lobby.match_service.record_result.assert_awaited_once_with(100, 200, True)


# ─── end_reporting — DQ handling ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_end_reporting_dq_closes_lobby():
    lobby = make_lobby()
    lobby.send_player_instructions = AsyncMock()
    lobby.close_lobby = AsyncMock()

    lobby.dh.get_lobby = AsyncMock(return_value={
        'results': [100],       # ← only the winner, matching num_winners=1
        'players': [100, 200],
        'picked_stage': 'stage1',
    })

    await lobby.end_reporting(winner_id=100, is_dq=True)
    lobby.close_lobby.assert_awaited_once()


@pytest.mark.asyncio
async def test_end_reporting_non_dq_does_not_close_lobby():
    lobby = make_lobby()
    lobby.send_player_instructions = AsyncMock()
    lobby.close_lobby = AsyncMock()

    lobby.dh.get_lobby = AsyncMock(return_value={
        'results': [100],       # ← only the winner, matching num_winners=1
        'players': [100, 200],
        'picked_stage': 'stage1',
    })

    await lobby.end_reporting(winner_id=100, is_dq=False)
    lobby.close_lobby.assert_not_awaited()


# ─── Stage bans ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_zero_stage_bans_skips_to_reporting():
    """With only 1 stage available, no bans happen — jump straight to reporting."""
    lobby = make_lobby()
    lobby.stages = ['stage1']
    lobby.start_reporting = AsyncMock()

    with MagicMock() as mock_view_cls:
        mock_view = MagicMock()
        mock_view.calculate_num_stage_bans = MagicMock(return_value=0)
        mock_view_cls.return_value = mock_view

        import tournaments.match_lobby as ml
        original = ml.BanStagesButton
        ml.BanStagesButton = mock_view_cls
        try:
            await lobby.start_stage_bans()
        finally:
            ml.BanStagesButton = original

    lobby.start_reporting.assert_awaited_once()


@pytest.mark.asyncio
async def test_end_stage_bans_picks_from_remaining_stages():
    """Banned stages must be excluded from the pool before picking."""
    lobby = make_lobby()
    lobby.stages = ['s1', 's2', 's3']
    lobby.start_reporting = AsyncMock()

    await lobby.end_stage_bans(banned_stages=['s1', 's3'])

    # Only s2 remains — it must be picked
    lobby.dh.pick_lobby_stage.assert_awaited_once_with(10, 's2')


# ─── format_handler.on_result routing via report_match ───────────────────────
#
# report_match is now the rehydration fallback: it builds a result dict and
# delegates to format_handler.on_result. These tests verify the routing inside
# DEFormatHandler and SwissFormatHandler by using the real format_handler.

@pytest.mark.asyncio
async def test_de_report_match_calls_challonge():
    tm = make_tm_for_report(format='double elimination')

    mock_lobby = AsyncMock()
    mock_lobby.get_lobby = AsyncMock(return_value={
        'match_id': 10,
        'results': [100, 200],
    })

    await tm.report_match(mock_lobby)

    tm.ch.report_match.assert_awaited_once()


@pytest.mark.asyncio
async def test_de_report_match_does_not_call_swiss_record():
    tm = make_tm_for_report(format='double elimination')

    mock_lobby = AsyncMock()
    mock_lobby.get_lobby = AsyncMock(return_value={
        'match_id': 10,
        'results': [100, 200],
    })

    await tm.report_match(mock_lobby)

    tm.bot.dh.swiss_record_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_swiss_report_match_calls_swiss_record_result():
    tm = make_tm_for_report(format='swiss')

    mock_lobby = AsyncMock()
    mock_lobby.get_lobby = AsyncMock(return_value={
        'match_id': 10,
        'results': [100, 200],
    })

    await tm.report_match(mock_lobby)

    tm.bot.dh.swiss_record_result.assert_awaited_once()


@pytest.mark.asyncio
async def test_swiss_report_match_does_not_call_challonge():
    tm = make_tm_for_report(format='swiss')

    mock_lobby = AsyncMock()
    mock_lobby.get_lobby = AsyncMock(return_value={
        'match_id': 10,
        'results': [100, 200],
    })

    await tm.report_match(mock_lobby)

    tm.ch.report_match.assert_not_awaited()


@pytest.mark.asyncio
async def test_swiss_report_match_triggers_on_match_complete():
    tm = make_tm_for_report(format='swiss')

    mock_lobby = AsyncMock()
    mock_lobby.get_lobby = AsyncMock(return_value={
        'match_id': 10,
        'results': [100, 200],
    })

    await tm.report_match(mock_lobby)

    tm.swiss_manager.on_match_complete.assert_awaited_once_with(10, 100, 200)


@pytest.mark.asyncio
async def test_swiss_report_match_dq_skips_ranked_api():
    """DQ results should not be reported to the UCH Ranked API."""
    tm = make_tm_for_report(format='swiss')

    mock_lobby = AsyncMock()
    mock_lobby.get_lobby = AsyncMock(return_value={
        'match_id': 10,
        'results': [100, 200],
    })

    await tm.report_match(mock_lobby, is_dq=True)

    tm.bot.uchranked_api.report_match.assert_not_awaited()


@pytest.mark.asyncio
async def test_swiss_report_match_non_dq_calls_ranked_api():
    tm = make_tm_for_report(format='swiss')

    mock_lobby = AsyncMock()
    mock_lobby.get_lobby = AsyncMock(return_value={
        'match_id': 10,
        'results': [100, 200],
    })

    await tm.report_match(mock_lobby, is_dq=False)

    tm.bot.uchranked_api.report_match.assert_awaited_once()


# ─── report_match_from_result ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_report_match_from_result_delegates_to_format_handler():
    tm = make_tm_for_report(format='double elimination')
    tm.format = AsyncMock()          # ← was tm.format_handler
    tm.format.on_result = AsyncMock()

    mock_lobby = AsyncMock()
    tm.lobbies = {10: mock_lobby}

    result = {'match_id': 10, 'winner_id': 100, 'loser_id': 200, 'is_dq': False}
    await tm.report_match_from_result(result)

    tm.format.on_result.assert_awaited_once_with(result, mock_lobby)


@pytest.mark.asyncio
async def test_report_match_from_result_silent_if_lobby_missing():
    tm = make_tm_for_report()
    tm.format = AsyncMock()          # ← was tm.format_handler
    tm.format.on_result = AsyncMock()
    tm.lobbies = {}

    result = {'match_id': 99, 'winner_id': 100, 'loser_id': 200, 'is_dq': False}
    await tm.report_match_from_result(result)

    tm.format.on_result.assert_not_awaited()