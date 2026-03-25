# tests/test_swiss_dashboard_state.py
"""
Tests for SwissFormat.get_dashboard_state() — the data the web server
exposes to the dashboard on every poll.

Covers:
- round_ready is True when: active, no active matches, >1 player, not final round
- round_ready is False when there are active matches
- round_ready is False when only 1 player remains
- round_ready is False when current_round == round_limit (final round active)
- round_ready is False when tournament is not active
- final_round_active is False before the final round starts
- final_round_active is True as soon as current_round reaches round_limit
- final_round_active is True when current_round exceeds round_limit (shouldn't happen, but safe)
- active_matches counts correctly (each match shared by 2 players, divided by 2)
- active_matches excludes dropped players
- players_remaining excludes dropped players
- current_round and round_limit are passed through correctly
"""

import pytest
from unittest.mock import AsyncMock, MagicMock


def make_swiss_format(current_round=0, round_limit=3, players=None, tournament_state='active'):
    from formats.swiss import SwissFormat

    if players is None:
        players = {
            '1': {'active_match_id': None, 'dropped': False},
            '2': {'active_match_id': None, 'dropped': False},
            '3': {'active_match_id': None, 'dropped': False},
            '4': {'active_match_id': None, 'dropped': False},
        }

    swiss_event = {
        '_id': 'eid',
        'current_round': current_round,
        'round_limit': round_limit,
        'players': players,
        'state': 'active',
    }

    tournament = {
        '_id': 'tid',
        'state': tournament_state,
        'round_limit': round_limit,
    }

    dh = AsyncMock()
    dh.get_swiss_event_by_tournament = AsyncMock(return_value=swiss_event)

    tm = MagicMock()
    tm.tournament = tournament
    tm.get_tournament = AsyncMock(return_value=tournament)
    tm.bot = MagicMock()
    tm.bot.dh = dh

    fmt = object.__new__(SwissFormat)
    fmt.tm = tm
    fmt.dh = dh
    fmt.manager = MagicMock()
    fmt.pending_results = []

    return fmt, swiss_event, tournament


# ─── round_ready ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_round_ready_true_between_rounds():
    fmt, _, _ = make_swiss_format(current_round=1, round_limit=3)
    state = await fmt.get_dashboard_state()
    assert state['round_ready'] is True


@pytest.mark.asyncio
async def test_round_ready_false_when_active_matches():
    players = {
        '1': {'active_match_id': 99, 'dropped': False},
        '2': {'active_match_id': 99, 'dropped': False},
        '3': {'active_match_id': None, 'dropped': False},
        '4': {'active_match_id': None, 'dropped': False},
    }
    fmt, _, _ = make_swiss_format(current_round=1, round_limit=3, players=players)
    state = await fmt.get_dashboard_state()
    assert state['round_ready'] is False


@pytest.mark.asyncio
async def test_round_ready_false_when_only_one_player_remains():
    players = {
        '1': {'active_match_id': None, 'dropped': False},
        '2': {'active_match_id': None, 'dropped': True},
        '3': {'active_match_id': None, 'dropped': True},
        '4': {'active_match_id': None, 'dropped': True},
    }
    fmt, _, _ = make_swiss_format(current_round=1, round_limit=3, players=players)
    state = await fmt.get_dashboard_state()
    assert state['round_ready'] is False


@pytest.mark.asyncio
async def test_round_ready_false_on_final_round():
    """Once the final round has started, round_ready must be False — no more rounds to start."""
    fmt, _, _ = make_swiss_format(current_round=3, round_limit=3)
    state = await fmt.get_dashboard_state()
    assert state['round_ready'] is False


@pytest.mark.asyncio
async def test_round_ready_false_when_tournament_not_active():
    fmt, _, _ = make_swiss_format(current_round=1, round_limit=3, tournament_state='checkin')
    state = await fmt.get_dashboard_state()
    assert state['round_ready'] is False


# ─── final_round_active ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_final_round_active_false_before_final_round():
    """Round 1 of a 3-round event — final round not yet active."""
    fmt, _, _ = make_swiss_format(current_round=1, round_limit=3)
    state = await fmt.get_dashboard_state()
    assert state['final_round_active'] is False


@pytest.mark.asyncio
async def test_final_round_active_false_at_round_zero():
    """Before any rounds have started, final_round_active must be False."""
    fmt, _, _ = make_swiss_format(current_round=0, round_limit=3)
    state = await fmt.get_dashboard_state()
    assert state['final_round_active'] is False


@pytest.mark.asyncio
async def test_final_round_active_true_when_current_equals_round_limit():
    """As soon as round 3 starts in a 3-round event, final_round_active is True."""
    fmt, _, _ = make_swiss_format(current_round=3, round_limit=3)
    state = await fmt.get_dashboard_state()
    assert state['final_round_active'] is True


@pytest.mark.asyncio
async def test_final_round_active_true_when_current_exceeds_round_limit():
    """Defensive: if somehow current > limit, still treat as final round active."""
    fmt, _, _ = make_swiss_format(current_round=4, round_limit=3)
    state = await fmt.get_dashboard_state()
    assert state['final_round_active'] is True


@pytest.mark.asyncio
async def test_final_round_active_true_with_matches_still_running():
    """Final round active even while matches are still in progress."""
    players = {
        '1': {'active_match_id': 99, 'dropped': False},
        '2': {'active_match_id': 99, 'dropped': False},
    }
    fmt, _, _ = make_swiss_format(current_round=3, round_limit=3, players=players)
    state = await fmt.get_dashboard_state()
    assert state['final_round_active'] is True


# ─── active_matches ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_active_matches_counts_pairs_not_players():
    """Two players sharing the same match_id = 1 active match, not 2."""
    players = {
        '1': {'active_match_id': 99, 'dropped': False},
        '2': {'active_match_id': 99, 'dropped': False},
        '3': {'active_match_id': None, 'dropped': False},
        '4': {'active_match_id': None, 'dropped': False},
    }
    fmt, _, _ = make_swiss_format(players=players)
    state = await fmt.get_dashboard_state()
    assert state['active_matches'] == 1


@pytest.mark.asyncio
async def test_active_matches_zero_when_all_done():
    fmt, _, _ = make_swiss_format()
    state = await fmt.get_dashboard_state()
    assert state['active_matches'] == 0


@pytest.mark.asyncio
async def test_active_matches_excludes_dropped_players():
    """A dropped player with a stale active_match_id should not be counted."""
    players = {
        '1': {'active_match_id': 99, 'dropped': True},   # dropped, ignore
        '2': {'active_match_id': None, 'dropped': False},
    }
    fmt, _, _ = make_swiss_format(players=players)
    state = await fmt.get_dashboard_state()
    assert state['active_matches'] == 0


# ─── players_remaining ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_players_remaining_excludes_dropped():
    players = {
        '1': {'active_match_id': None, 'dropped': False},
        '2': {'active_match_id': None, 'dropped': True},
        '3': {'active_match_id': None, 'dropped': False},
        '4': {'active_match_id': None, 'dropped': True},
    }
    fmt, _, _ = make_swiss_format(players=players)
    state = await fmt.get_dashboard_state()
    assert state['players_remaining'] == 2


@pytest.mark.asyncio
async def test_players_remaining_counts_all_when_none_dropped():
    fmt, _, _ = make_swiss_format()
    state = await fmt.get_dashboard_state()
    assert state['players_remaining'] == 4


# ─── current_round and round_limit passthrough ────────────────────────────────

@pytest.mark.asyncio
async def test_current_round_passed_through():
    fmt, _, _ = make_swiss_format(current_round=2, round_limit=5)
    state = await fmt.get_dashboard_state()
    assert state['current_round'] == 2


@pytest.mark.asyncio
async def test_round_limit_passed_through():
    fmt, _, _ = make_swiss_format(current_round=1, round_limit=5)
    state = await fmt.get_dashboard_state()
    assert state['round_limit'] == 5


@pytest.mark.asyncio
async def test_returns_empty_dict_when_no_swiss_event():
    """If the swiss event doesn't exist yet, get_dashboard_state returns {}."""
    from formats.swiss import SwissFormat

    dh = AsyncMock()
    dh.get_swiss_event_by_tournament = AsyncMock(return_value=None)

    tm = MagicMock()
    tm.tournament = {'_id': 'tid', 'state': 'registration'}
    tm.get_tournament = AsyncMock(return_value=tm.tournament)
    tm.bot = MagicMock()
    tm.bot.dh = dh

    fmt = object.__new__(SwissFormat)
    fmt.tm = tm
    fmt.dh = dh

    state = await fmt.get_dashboard_state()
    assert state == {}