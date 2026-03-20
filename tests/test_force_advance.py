"""
tests/test_force_advance.py

Tests for MatchLobby.force_advance.

Covers the logic in force_advance itself — DB resets, state restoration,
and correct delegation to start_* / end_reporting. The Discord UI layer
(ForceAdvanceView, ForceWinnerView) is not tested here.

Covers:
- force_advance('stage_bans') resets DB and calls start_stage_bans
- force_advance('reporting') resets DB and calls start_reporting
- force_advance('reporting') picks a stage when none is set
- force_advance('reporting') does not overwrite an existing picked_stage
- force_advance('winner', winner_id) calls end_reporting with correct winner
- force_advance('winner') without winner_id raises ValueError
- remaining_players is restored from DB after each reset
"""

import pytest
import random
from unittest.mock import AsyncMock, MagicMock, patch


def make_lobby(picked_stage=None, players=None):
    """
    Build a minimal MatchLobby for force_advance testing.
    All start_* and end_reporting methods are mocked — we're only testing
    that force_advance calls the right ones with the right arguments.
    """
    from tournaments.match_lobby import MatchLobby

    lobby = object.__new__(MatchLobby)
    lobby.match_id = 10
    lobby.players = players or [100, 200]
    lobby.remaining_players = set(lobby.players)
    lobby.stages = ['s1', 's2', 's3']
    lobby.channel = AsyncMock()

    lobby.dh = AsyncMock()
    lobby.dh.reset_lobby = AsyncMock()
    lobby.dh.pick_lobby_stage = AsyncMock()
    lobby.dh.get_lobby = AsyncMock(return_value={
        'players': lobby.players,
        'picked_stage': picked_stage,
    })

    lobby.purge_bot_messages = AsyncMock()
    lobby.start_stage_bans = AsyncMock()
    lobby.start_reporting = AsyncMock()
    lobby.end_reporting = AsyncMock()

    return lobby


# ─── stage_bans ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_force_stage_bans_calls_db_reset():
    lobby = make_lobby()
    await lobby.force_advance('stage_bans')
    lobby.dh.reset_lobby.assert_awaited_once_with(10, 'stage_bans')


@pytest.mark.asyncio
async def test_force_stage_bans_calls_start_stage_bans():
    lobby = make_lobby()
    await lobby.force_advance('stage_bans')
    lobby.start_stage_bans.assert_awaited_once()


@pytest.mark.asyncio
async def test_force_stage_bans_restores_remaining_players():
    lobby = make_lobby(players=[100, 200])
    lobby.remaining_players = set()  # simulate depleted state
    await lobby.force_advance('stage_bans')
    assert lobby.remaining_players == {100, 200}


@pytest.mark.asyncio
async def test_force_stage_bans_purges_bot_messages():
    lobby = make_lobby()
    await lobby.force_advance('stage_bans')
    lobby.purge_bot_messages.assert_awaited_once()


# ─── reporting ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_force_reporting_calls_db_reset():
    lobby = make_lobby(picked_stage='s1')
    await lobby.force_advance('reporting')
    lobby.dh.reset_lobby.assert_awaited_once_with(10, 'report')


@pytest.mark.asyncio
async def test_force_reporting_calls_start_reporting():
    lobby = make_lobby(picked_stage='s1')
    await lobby.force_advance('reporting')
    lobby.start_reporting.assert_awaited_once()


@pytest.mark.asyncio
async def test_force_reporting_restores_remaining_players():
    lobby = make_lobby(picked_stage='s1', players=[100, 200])
    lobby.remaining_players = set()
    await lobby.force_advance('reporting')
    assert lobby.remaining_players == {100, 200}


@pytest.mark.asyncio
async def test_force_reporting_picks_stage_when_none_set():
    """If no picked_stage exists in DB, a random one must be chosen."""
    lobby = make_lobby(picked_stage=None)
    await lobby.force_advance('reporting')
    lobby.dh.pick_lobby_stage.assert_awaited_once()


@pytest.mark.asyncio
async def test_force_reporting_picks_stage_from_stagelist():
    """The picked stage must come from the lobby's own stagelist."""
    lobby = make_lobby(picked_stage=None)

    with patch('random.choice', return_value='s2') as mock_choice:
        await lobby.force_advance('reporting')
        mock_choice.assert_called_once_with(lobby.stages)

    lobby.dh.pick_lobby_stage.assert_awaited_once_with(10, 's2')


@pytest.mark.asyncio
async def test_force_reporting_does_not_overwrite_existing_stage():
    """If a stage is already picked in DB, do not pick another."""
    lobby = make_lobby(picked_stage='s1')
    await lobby.force_advance('reporting')
    lobby.dh.pick_lobby_stage.assert_not_awaited()


# ─── winner ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_force_winner_calls_end_reporting():
    lobby = make_lobby()
    await lobby.force_advance('winner', winner_id=100)
    lobby.end_reporting.assert_awaited_once_with(winner_id=100)


@pytest.mark.asyncio
async def test_force_winner_does_not_call_db_reset():
    """end_reporting handles its own DB writes — force_advance should not reset."""
    lobby = make_lobby()
    await lobby.force_advance('winner', winner_id=100)
    lobby.dh.reset_lobby.assert_not_awaited()


@pytest.mark.asyncio
async def test_force_winner_without_winner_id_raises():
    lobby = make_lobby()
    with pytest.raises(ValueError):
        await lobby.force_advance('winner')


@pytest.mark.asyncio
async def test_force_winner_purges_bot_messages():
    lobby = make_lobby()
    await lobby.force_advance('winner', winner_id=100)
    lobby.purge_bot_messages.assert_awaited_once()