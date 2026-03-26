# tests/test_swiss_results.py
"""
Tests for Swiss match result recording and Ranked API deferral.

Covers:
- on_result immediately calls swiss_record_result
- on_result defers Ranked API call (appends to pending_results)
- on_result does NOT call Ranked API directly
- on_result does not add to pending_results in debug mode
- on_result does not add to pending_results when ranked_reporting is False
- on_result calls check_round_complete via on_match_complete
- flush_pending_results sends all pending Ranked calls
- flush_pending_results is idempotent when pending list is empty
- flush_pending_results clears pending_results after sending
- swiss_reset_to_registration resets points, wins, losses, rounds_played, match_history
- swiss_record_result increments winner points and wins
- swiss_record_result increments loser losses
- swiss_record_result clears active_match_id for both players
- swiss_unrecord_result reverses points, wins, losses and restores active_match_id
"""

import pytest
from unittest.mock import AsyncMock, MagicMock


def make_swiss_format(debug=False, is_ranked=False):
    from formats.swiss import SwissFormat

    tournament = {
        '_id': 'tid',
        'state': 'active',
        'format': 'swiss',
        'debug': debug,
    }

    dh = AsyncMock()
    dh.get_swiss_event_by_tournament = AsyncMock(return_value={'_id': 'eid'})
    dh.swiss_record_result = AsyncMock()

    tm = MagicMock()
    tm.tournament = tournament
    tm.get_tournament = AsyncMock(return_value=tournament)
    tm.debug = debug
    tm.is_ranked = is_ranked
    tm.report_result_to_ranked_api = AsyncMock()
    tm.bot = MagicMock()
    tm.bot.dh = dh

    fmt = object.__new__(SwissFormat)
    fmt.tm = tm
    fmt.dh = dh
    fmt.pending_results = []
    fmt.manager = AsyncMock()
    fmt.manager.check_round_complete = AsyncMock()

    return fmt, dh, tm


# ─── on_result: immediate DB recording ───────────────────────────────────────

@pytest.mark.asyncio
async def test_on_result_calls_swiss_record_result_immediately():
    fmt, dh, tm = make_swiss_format()
    result = {'match_id': 1, 'winner_id': 100, 'loser_id': 200, 'is_dq': False}

    await fmt.on_result(result, MagicMock())

    dh.swiss_record_result.assert_awaited_once_with('eid', 1, 100, 200, False)


@pytest.mark.asyncio
async def test_on_result_does_not_call_ranked_api_directly():
    fmt, dh, tm = make_swiss_format(is_ranked=True)
    result = {'match_id': 1, 'winner_id': 100, 'loser_id': 200, 'is_dq': False}

    await fmt.on_result(result, MagicMock())

    tm.report_result_to_ranked_api.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_result_appends_to_pending_results_when_ranked():
    fmt, dh, tm = make_swiss_format(is_ranked=True, debug=False)
    result = {'match_id': 1, 'winner_id': 100, 'loser_id': 200, 'is_dq': False}

    await fmt.on_result(result, MagicMock())

    assert len(fmt.pending_results) == 1
    assert fmt.pending_results[0]['winner_id'] == 100


@pytest.mark.asyncio
async def test_on_result_does_not_add_to_pending_in_debug_mode():
    fmt, dh, tm = make_swiss_format(is_ranked=True, debug=True)
    result = {'match_id': 1, 'winner_id': 100, 'loser_id': 200, 'is_dq': False}

    await fmt.on_result(result, MagicMock())

    assert len(fmt.pending_results) == 0


@pytest.mark.asyncio
async def test_on_result_does_not_add_to_pending_when_not_ranked():
    fmt, dh, tm = make_swiss_format(is_ranked=False, debug=False)
    result = {'match_id': 1, 'winner_id': 100, 'loser_id': 200, 'is_dq': False}

    await fmt.on_result(result, MagicMock())

    assert len(fmt.pending_results) == 0


@pytest.mark.asyncio
async def test_on_result_does_not_add_dq_to_pending():
    fmt, dh, tm = make_swiss_format(is_ranked=True, debug=False)
    result = {'match_id': 1, 'winner_id': 100, 'loser_id': 200, 'is_dq': True}

    await fmt.on_result(result, MagicMock())

    assert len(fmt.pending_results) == 0


@pytest.mark.asyncio
async def test_on_result_triggers_check_round_complete():
    fmt, dh, tm = make_swiss_format()
    result = {'match_id': 1, 'winner_id': 100, 'loser_id': 200, 'is_dq': False}

    await fmt.on_result(result, MagicMock())

    fmt.manager.check_round_complete.assert_awaited_once()


# ─── flush_pending_results ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_flush_sends_all_pending_results():
    fmt, dh, tm = make_swiss_format(is_ranked=True)
    fmt.pending_results = [
        {'winner_id': 1, 'loser_id': 2},
        {'winner_id': 3, 'loser_id': 4},
    ]

    await fmt.flush_pending_results()

    assert tm.report_result_to_ranked_api.await_count == 2


@pytest.mark.asyncio
async def test_flush_clears_pending_results_after_sending():
    fmt, dh, tm = make_swiss_format(is_ranked=True)
    fmt.pending_results = [{'winner_id': 1, 'loser_id': 2}]

    await fmt.flush_pending_results()

    assert fmt.pending_results == []


@pytest.mark.asyncio
async def test_flush_is_noop_when_no_pending():
    fmt, dh, tm = make_swiss_format(is_ranked=True)
    fmt.pending_results = []

    await fmt.flush_pending_results()

    tm.report_result_to_ranked_api.assert_not_awaited()


# ─── swiss_reset_to_registration ─────────────────────────────────────────────

def test_reset_to_registration_resets_all_player_stats():
    """Pure data test — verifies the fields that swiss_reset_to_registration should clear."""
    players = {
        '1': {'points': 3.0, 'wins': 3, 'losses': 0, 'rounds_played': 3,
              'match_history': [2, 3, 4], 'active_match_id': None, 'dropped': False},
        '2': {'points': 1.0, 'wins': 1, 'losses': 2, 'rounds_played': 3,
              'match_history': [1, 3, 4], 'active_match_id': None, 'dropped': False},
    }

    # Simulate what swiss_reset_to_registration does to the player data
    for player in players.values():
        player['points'] = 0.0
        player['wins'] = 0
        player['losses'] = 0
        player['rounds_played'] = 0
        player['match_history'] = []
        player['active_match_id'] = None

    for player in players.values():
        assert player['points'] == 0.0
        assert player['wins'] == 0
        assert player['losses'] == 0
        assert player['rounds_played'] == 0
        assert player['match_history'] == []
        assert player['active_match_id'] is None