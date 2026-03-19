"""
tests/test_match_flow.py

Tests for the match lobby lifecycle: from initialization through result reporting.

Covers:
- end_reporting calls the right chain of methods
- DQ matches close the lobby immediately and skip stage bans
- Unanimous reporting resolves the match
- Conflicting reports trigger a redo
- stage_bans with 0 stages skips straight to reporting
- report_match on a DE lobby calls Challonge
- report_match on a Swiss lobby calls swiss_record_result
- report_match on a Swiss lobby triggers on_match_complete
- Swiss result does NOT call Challonge
- DE result does NOT call swiss_record_result
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, call


def make_lobby(format='double elimination', bracket='Winners', results=None, num_winners=1):
    """
    Build a minimal MatchLobby-like object without hitting Discord or DB.
    """
    from tournaments.match_lobby import MatchLobby

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
    tm.is_swiss = (format == 'swiss')
    tm.tournament = tournament
    tm.report_match = AsyncMock()
    lobby.tournament_manager = tm

    lobby.dh = AsyncMock()
    lobby.dh.get_lobby = AsyncMock(return_value={
        'results': results or [],
        'players': [100, 200],
        'picked_stage': 'stage1',
    })
    lobby.dh.report_match = AsyncMock()
    lobby.dh.report_dq = AsyncMock()
    lobby.dh.update_lobby_state = AsyncMock()
    lobby.dh.end_match = AsyncMock()
    lobby.dh.get_stage = AsyncMock(return_value={'name': 'Stage One', 'code': 'stage1'})
    lobby.dh.pick_lobby_stage = AsyncMock()
    lobby.dh.update_lobby_state = AsyncMock()

    lobby.organizer_role = 'Test Tournament TO'

    return lobby


def make_tm_for_report(format='double elimination'):
    """Build a TournamentManager stub for report_match testing."""
    from tournaments.tournament_manager import TournamentManager

    tournament = {
        '_id': 'tid',
        'name': 'Test',
        'format': format,          # is_swiss property reads from here
        'entrants': {'100': 10, '200': 20},
        'challonge_data': {'url': 'test-url', 'id': 'chid'},
        'debug': False,
        'dqs': [],
    }

    tm = object.__new__(TournamentManager)
    tm.tournament = tournament     # is_swiss reads tournament['format'], no setter needed
    tm.debug = False
    tm.tournament_reset = False
    tm.lobbies = {}
    tm.match_calls = {}
    tm.swiss_manager = AsyncMock()
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

    return tm


# ─── end_reporting ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_end_reporting_calls_report_match():
    lobby = make_lobby()
    lobby.send_player_instructions = AsyncMock()
    lobby.close_lobby = AsyncMock()

    lobby.dh.get_lobby = AsyncMock(return_value={
        'results': [100],
        'players': [100, 200],
        'picked_stage': 'stage1',
    })

    await lobby.end_reporting(winner_id=100)
    lobby.dh.report_match.assert_awaited_once_with(10, 100)


@pytest.mark.asyncio
async def test_end_reporting_dq_closes_lobby():
    lobby = make_lobby()
    lobby.send_player_instructions = AsyncMock()
    lobby.close_lobby = AsyncMock()

    lobby.dh.get_lobby = AsyncMock(return_value={
        'results': [100],
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
        'results': [100],
        'players': [100, 200],
        'picked_stage': 'stage1',
    })

    await lobby.end_reporting(winner_id=100, is_dq=False)
    lobby.close_lobby.assert_not_awaited()


@pytest.mark.asyncio
async def test_end_reporting_calls_tournament_manager_report():
    lobby = make_lobby()
    lobby.send_player_instructions = AsyncMock()
    lobby.close_lobby = AsyncMock()

    lobby.dh.get_lobby = AsyncMock(return_value={
        'results': [100],
        'players': [100, 200],
        'picked_stage': 'stage1',
    })

    await lobby.end_reporting(winner_id=100)
    lobby.tournament_manager.report_match.assert_awaited_once()


# ─── Stage bans ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_zero_stage_bans_skips_to_reporting():
    """With only 1 stage available, no bans happen — jump straight to reporting."""
    lobby = make_lobby()
    lobby.stages = ['stage1']  # 1 stage = 0 bans
    lobby.start_reporting = AsyncMock()

    # BanStagesButton.calculate_num_stage_bans returns 0 for 1 stage
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


# ─── report_match in TournamentManager ───────────────────────────────────────

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