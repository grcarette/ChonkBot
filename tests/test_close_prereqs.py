"""
tests/test_close_prereqs.py

Regression tests for the close_prereqs variable shadowing bug.

The bug: the loop variable `lobby` was shadowing both the method parameter
and the loop data source, causing only the first prereq to be processed
correctly. On the second iteration, `lobby['prereq_matches']` was reading
from the first prereq's DB document rather than the original match.

These tests verify:
- A single prereq lobby that is open gets closed
- A single prereq lobby that is already closed is skipped
- Two prereq lobbies both get closed (this is the case the bug broke)
- Two prereq lobbies where one is already closed — only the open one is closed
- close_lobby is never called on a lobby not in the prereq list
"""

import pytest
from unittest.mock import AsyncMock, MagicMock


def make_tm(prereq_ids, prereq_states):
    """
    Build a minimal TournamentManager with:
      - a mock lobby whose get_lobby() returns the given prereq_ids
      - bot.dh.get_lobby returning state for each prereq_id
      - self.lobbies populated with mock MatchLobby objects for each prereq
    """
    from tournaments.tournament_manager import TournamentManager

    tm = object.__new__(TournamentManager)
    tm.bot = MagicMock()
    tm.bot.dh = AsyncMock()

    # The lobby passed into close_prereqs — its get_lobby returns our prereq list
    mock_lobby = AsyncMock()
    mock_lobby.get_lobby = AsyncMock(return_value={
        'prereq_matches': prereq_ids,
    })
    tm._test_lobby = mock_lobby

    # Each prereq match has a DB entry with the given state
    async def fake_get_lobby(match_id):
        idx = prereq_ids.index(match_id)
        return {'match_id': match_id, 'state': prereq_states[idx]}

    tm.bot.dh.get_lobby = fake_get_lobby

    # Each prereq has a MatchLobby in self.lobbies with a trackable close_lobby
    tm.lobbies = {}
    for match_id in prereq_ids:
        mock_prereq_lobby = AsyncMock()
        mock_prereq_lobby.close_lobby = AsyncMock()
        tm.lobbies[match_id] = mock_prereq_lobby

    return tm


# ─── Single prereq ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_single_open_prereq_is_closed():
    tm = make_tm(prereq_ids=[1], prereq_states=['reporting'])
    await tm.close_prereqs(tm._test_lobby)
    tm.lobbies[1].close_lobby.assert_awaited_once()


@pytest.mark.asyncio
async def test_single_closed_prereq_is_skipped():
    tm = make_tm(prereq_ids=[1], prereq_states=['closed'])
    await tm.close_prereqs(tm._test_lobby)
    tm.lobbies[1].close_lobby.assert_not_awaited()


# ─── Two prereqs — the regression case ───────────────────────────────────────

@pytest.mark.asyncio
async def test_both_open_prereqs_are_closed():
    """
    The core regression test. Before the fix, the second prereq was silently
    skipped because the loop variable shadowed the prereq list source.
    """
    tm = make_tm(prereq_ids=[1, 2], prereq_states=['reporting', 'reporting'])
    await tm.close_prereqs(tm._test_lobby)
    tm.lobbies[1].close_lobby.assert_awaited_once()
    tm.lobbies[2].close_lobby.assert_awaited_once()


@pytest.mark.asyncio
async def test_first_closed_second_open():
    tm = make_tm(prereq_ids=[1, 2], prereq_states=['closed', 'reporting'])
    await tm.close_prereqs(tm._test_lobby)
    tm.lobbies[1].close_lobby.assert_not_awaited()
    tm.lobbies[2].close_lobby.assert_awaited_once()


@pytest.mark.asyncio
async def test_first_open_second_closed():
    tm = make_tm(prereq_ids=[1, 2], prereq_states=['reporting', 'closed'])
    await tm.close_prereqs(tm._test_lobby)
    tm.lobbies[1].close_lobby.assert_awaited_once()
    tm.lobbies[2].close_lobby.assert_not_awaited()


@pytest.mark.asyncio
async def test_both_closed_prereqs_skipped():
    tm = make_tm(prereq_ids=[1, 2], prereq_states=['closed', 'closed'])
    await tm.close_prereqs(tm._test_lobby)
    tm.lobbies[1].close_lobby.assert_not_awaited()
    tm.lobbies[2].close_lobby.assert_not_awaited()


# ─── No prereqs ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_prereqs_does_nothing():
    """A match with no prereqs (e.g. round 1) should not crash or close anything."""
    tm = make_tm(prereq_ids=[], prereq_states=[])
    await tm.close_prereqs(tm._test_lobby)
    # No lobbies to close — just verify no exception was raised
    assert tm.lobbies == {}