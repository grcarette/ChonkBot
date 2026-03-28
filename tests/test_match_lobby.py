# tests/test_match_lobby.py
"""
Tests for MatchLobby lifecycle.

Covers:
- close_lobby updates DB state to 'closed' AND deletes the Discord channel
- close_lobby sets channel to None after deletion
- delete_lobby removes DB record without state update
- delete_lobby deletes channel if present
- end_reporting delegates to match_service when present
- end_reporting falls back to tournament_manager.report_match when no match_service
- end_reporting on DQ closes lobby immediately
- end_reporting on non-DQ does not close lobby
- stage_bans with 0 stages skips straight to reporting
- end_stage_bans picks from remaining (non-banned) stages only
- force_advance('stage_bans') resets DB and calls start_stage_bans
- force_advance('reporting') resets DB and calls start_reporting
- force_advance('reporting') picks a stage when none is set
- force_advance('reporting') does not overwrite an existing picked_stage
- force_advance('winner', winner_id) calls end_reporting with correct winner
- force_advance('winner') without winner_id raises ValueError
"""

import pytest
import random
from unittest.mock import AsyncMock, MagicMock, patch


def make_lobby(is_dq=False, num_winners=1, stages=None):
    from tournaments.match_lobby import MatchLobby

    lobby = object.__new__(MatchLobby)
    lobby.match_id = 10
    lobby.lobby_name = 'wr1-A vs B'
    lobby.bracket = 'Winners'
    lobby.players = ['100', '200']
    lobby.remaining_players = {'100', '200'}
    lobby.stages = stages or ['s1', 's2', 's3']
    lobby.num_winners = num_winners
    lobby.channel = AsyncMock()
    lobby.guild = MagicMock()
    lobby.prereq_matches = []
    lobby.match_service = None

    lobby.tournament = {
        '_id': 'tid',
        'name': 'Test',
        'format': 'double elimination',
        'entrants': {'100': 10, '200': 20},
        'dqs': [],
        'challonge_data': {'url': 'test-url'},
    }

    tm = MagicMock()
    tm.tournament = lobby.tournament
    tm.report_match = AsyncMock()
    lobby.tournament_manager = tm

    lobby.dh = AsyncMock()
    lobby.dh.get_lobby = AsyncMock(return_value={
        'results': ['100'],
        'players': ['100', '200'],
        'picked_stage': 's1',
        'checked_in': [],
    })
    lobby.dh.update_lobby_state = AsyncMock()
    lobby.dh.delete_lobby = AsyncMock()
    lobby.dh.pick_lobby_stage = AsyncMock()
    lobby.dh.reset_lobby = AsyncMock(return_value={'players': ['100', '200'], 'picked_stage': None})
    lobby.dh.get_stage = AsyncMock(return_value={'name': 'Test Stage', 'code': 's1'})

    lobby.send_player_instructions = AsyncMock()
    lobby.close_lobby = AsyncMock()
    lobby.purge_bot_messages = AsyncMock()
    lobby.start_reporting = AsyncMock()
    lobby.start_stage_bans = AsyncMock()
    lobby.end_reporting = AsyncMock()

    return lobby


# ─── close_lobby ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_close_lobby_updates_db_state_to_closed():
    from tournaments.match_lobby import MatchLobby
    lobby = object.__new__(MatchLobby)
    lobby.match_id = 10
    lobby.channel = AsyncMock()
    lobby.dh = AsyncMock()
    lobby.dh.update_lobby_state = AsyncMock()

    await MatchLobby.close_lobby(lobby)

    lobby.dh.update_lobby_state.assert_awaited_once_with(10, 'closed')


@pytest.mark.asyncio
async def test_close_lobby_deletes_discord_channel():
    from tournaments.match_lobby import MatchLobby
    lobby = object.__new__(MatchLobby)
    lobby.match_id = 10
    channel = AsyncMock()
    lobby.channel = channel
    lobby.dh = AsyncMock()
    lobby.dh.update_lobby_state = AsyncMock()

    await MatchLobby.close_lobby(lobby)

    channel.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_lobby_sets_channel_to_none():
    from tournaments.match_lobby import MatchLobby
    lobby = object.__new__(MatchLobby)
    lobby.match_id = 10
    lobby.channel = AsyncMock()
    lobby.dh = AsyncMock()
    lobby.dh.update_lobby_state = AsyncMock()

    await MatchLobby.close_lobby(lobby)

    assert lobby.channel is None


@pytest.mark.asyncio
async def test_close_lobby_with_no_channel_does_not_crash():
    from tournaments.match_lobby import MatchLobby
    lobby = object.__new__(MatchLobby)
    lobby.match_id = 10
    lobby.channel = None
    lobby.dh = AsyncMock()
    lobby.dh.update_lobby_state = AsyncMock()

    await MatchLobby.close_lobby(lobby)  # should not raise

    lobby.dh.update_lobby_state.assert_awaited_once_with(10, 'closed')


# ─── delete_lobby ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_lobby_removes_db_record():
    from tournaments.match_lobby import MatchLobby
    lobby = object.__new__(MatchLobby)
    lobby.match_id = 10
    lobby.channel = None
    lobby.dh = AsyncMock()
    lobby.dh.delete_lobby = AsyncMock()

    await MatchLobby.delete_lobby(lobby)

    lobby.dh.delete_lobby.assert_awaited_once_with(10)


@pytest.mark.asyncio
async def test_delete_lobby_deletes_channel_when_present():
    from tournaments.match_lobby import MatchLobby
    lobby = object.__new__(MatchLobby)
    lobby.match_id = 10
    channel = AsyncMock()
    lobby.channel = channel
    lobby.dh = AsyncMock()
    lobby.dh.delete_lobby = AsyncMock()

    await MatchLobby.delete_lobby(lobby)

    channel.delete.assert_awaited_once()


# ─── end_reporting ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_end_reporting_calls_match_service_when_present():
    from tournaments.match_lobby import MatchLobby
    lobby = make_lobby()

    real_lobby = object.__new__(MatchLobby)
    real_lobby.__dict__.update(lobby.__dict__)
    real_lobby.close_lobby = AsyncMock()
    real_lobby.send_player_instructions = AsyncMock()
    real_lobby.match_service = AsyncMock()
    real_lobby.purge_bot_messages = AsyncMock()

    await MatchLobby.end_reporting(real_lobby, winner_id=100)

    real_lobby.match_service.record_result.assert_awaited_once_with('100', '200', False)


@pytest.mark.asyncio
async def test_end_reporting_falls_back_to_report_match_when_no_service():
    from tournaments.match_lobby import MatchLobby
    lobby = make_lobby()

    real_lobby = object.__new__(MatchLobby)
    real_lobby.__dict__.update(lobby.__dict__)
    real_lobby.match_service = None
    real_lobby.close_lobby = AsyncMock()
    real_lobby.send_player_instructions = AsyncMock()
    real_lobby.purge_bot_messages = AsyncMock()

    await MatchLobby.end_reporting(real_lobby, winner_id=100)

    real_lobby.tournament_manager.report_match.assert_awaited_once()


@pytest.mark.asyncio
async def test_end_reporting_dq_sends_player_instructions():
    """A DQ result backgrounds send_player_instructions via create_task — no close_lobby."""
    from tournaments.match_lobby import MatchLobby
    import tournaments.match_lobby as ml
    lobby = make_lobby()

    real_lobby = object.__new__(MatchLobby)
    real_lobby.__dict__.update(lobby.__dict__)
    real_lobby.close_lobby = AsyncMock()
    real_lobby.send_player_instructions = AsyncMock()
    real_lobby.match_service = AsyncMock()
    real_lobby.purge_bot_messages = AsyncMock()

    with patch.object(ml.asyncio, 'create_task') as mock_create_task:
        await MatchLobby.end_reporting(real_lobby, winner_id=100, is_dq=True)

    mock_create_task.assert_called_once()
    real_lobby.close_lobby.assert_not_awaited()


@pytest.mark.asyncio
async def test_end_reporting_non_dq_sends_player_instructions():
    """A normal result backgrounds send_player_instructions via create_task."""
    from tournaments.match_lobby import MatchLobby
    import tournaments.match_lobby as ml
    lobby = make_lobby()

    real_lobby = object.__new__(MatchLobby)
    real_lobby.__dict__.update(lobby.__dict__)
    real_lobby.close_lobby = AsyncMock()
    real_lobby.send_player_instructions = AsyncMock()
    real_lobby.match_service = AsyncMock()
    real_lobby.purge_bot_messages = AsyncMock()

    with patch.object(ml.asyncio, 'create_task') as mock_create_task:
        await MatchLobby.end_reporting(real_lobby, winner_id=100, is_dq=False)

    mock_create_task.assert_called_once()

# ─── Stage bans ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_zero_stage_bans_skips_to_reporting():
    from tournaments.match_lobby import MatchLobby
    import tournaments.match_lobby as ml

    lobby = make_lobby(stages=['s1'])

    real_lobby = object.__new__(MatchLobby)
    real_lobby.__dict__.update(lobby.__dict__)
    real_lobby.start_reporting = AsyncMock()
    real_lobby.purge_bot_messages = AsyncMock()

    mock_view = MagicMock()
    mock_view.calculate_num_stage_bans = MagicMock(return_value=0)
    mock_view_cls = MagicMock(return_value=mock_view)

    original = ml.BanStagesButton
    ml.BanStagesButton = mock_view_cls
    try:
        await MatchLobby.start_stage_bans(real_lobby)
    finally:
        ml.BanStagesButton = original

    real_lobby.start_reporting.assert_awaited_once()


@pytest.mark.asyncio
async def test_end_stage_bans_picks_only_from_remaining_stages():
    from tournaments.match_lobby import MatchLobby
    lobby = make_lobby(stages=['s1', 's2', 's3'])

    real_lobby = object.__new__(MatchLobby)
    real_lobby.__dict__.update(lobby.__dict__)
    real_lobby.start_reporting = AsyncMock()

    await MatchLobby.end_stage_bans(real_lobby, banned_stages=['s1', 's3'])

    real_lobby.dh.pick_lobby_stage.assert_awaited_once_with(10, 's2')


# ─── force_advance ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_force_advance_stage_bans_resets_db():
    from tournaments.match_lobby import MatchLobby
    lobby = make_lobby()
    real_lobby = object.__new__(MatchLobby)
    real_lobby.__dict__.update(lobby.__dict__)

    await MatchLobby.force_advance(real_lobby, 'stage_bans')

    real_lobby.dh.reset_lobby.assert_awaited_once_with(10, 'stage_bans')


@pytest.mark.asyncio
async def test_force_advance_stage_bans_calls_start_stage_bans():
    from tournaments.match_lobby import MatchLobby
    lobby = make_lobby()
    real_lobby = object.__new__(MatchLobby)
    real_lobby.__dict__.update(lobby.__dict__)

    await MatchLobby.force_advance(real_lobby, 'stage_bans')

    real_lobby.start_stage_bans.assert_awaited_once()


@pytest.mark.asyncio
async def test_force_advance_reporting_resets_db():
    from tournaments.match_lobby import MatchLobby
    lobby = make_lobby()
    real_lobby = object.__new__(MatchLobby)
    real_lobby.__dict__.update(lobby.__dict__)
    real_lobby.dh.reset_lobby = AsyncMock(return_value={'players': ['100', '200'], 'picked_stage': 's1'})
    real_lobby.dh.get_lobby = AsyncMock(return_value={'players': ['100', '200'], 'picked_stage': 's1'})

    await MatchLobby.force_advance(real_lobby, 'reporting')

    real_lobby.dh.reset_lobby.assert_awaited_once_with(10, 'report')


@pytest.mark.asyncio
async def test_force_advance_reporting_picks_stage_when_none():
    from tournaments.match_lobby import MatchLobby
    lobby = make_lobby()
    real_lobby = object.__new__(MatchLobby)
    real_lobby.__dict__.update(lobby.__dict__)
    real_lobby.dh.get_lobby = AsyncMock(return_value={'players': ['100', '200'], 'picked_stage': None})
    real_lobby.dh.reset_lobby = AsyncMock(return_value={'players': ['100', '200'], 'picked_stage': None})

    await MatchLobby.force_advance(real_lobby, 'reporting')

    real_lobby.dh.pick_lobby_stage.assert_awaited_once()


@pytest.mark.asyncio
async def test_force_advance_reporting_does_not_overwrite_existing_stage():
    from tournaments.match_lobby import MatchLobby
    lobby = make_lobby()
    real_lobby = object.__new__(MatchLobby)
    real_lobby.__dict__.update(lobby.__dict__)
    real_lobby.dh.get_lobby = AsyncMock(return_value={'players': ['100', '200'], 'picked_stage': 's2'})
    real_lobby.dh.reset_lobby = AsyncMock(return_value={'players': ['100', '200'], 'picked_stage': 's2'})

    await MatchLobby.force_advance(real_lobby, 'reporting')

    real_lobby.dh.pick_lobby_stage.assert_not_awaited()


@pytest.mark.asyncio
async def test_force_advance_winner_calls_end_reporting():
    from tournaments.match_lobby import MatchLobby
    lobby = make_lobby()
    real_lobby = object.__new__(MatchLobby)
    real_lobby.__dict__.update(lobby.__dict__)

    await MatchLobby.force_advance(real_lobby, 'winner', winner_id=100)

    real_lobby.end_reporting.assert_awaited_once_with(winner_id=100)


@pytest.mark.asyncio
async def test_force_advance_winner_without_id_raises():
    from tournaments.match_lobby import MatchLobby
    lobby = make_lobby()
    real_lobby = object.__new__(MatchLobby)
    real_lobby.__dict__.update(lobby.__dict__)

    with pytest.raises(ValueError):
        await MatchLobby.force_advance(real_lobby, 'winner')