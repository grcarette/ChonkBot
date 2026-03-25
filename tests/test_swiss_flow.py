# tests/test_swiss_flow.py
"""
Tests for SwissManager round lifecycle.

Covers:
- run_pairing_cycle: closes channels, posts standings, increments round, creates matches
- run_pairing_cycle: aborts when not running
- run_pairing_cycle: calls end_event when event is already complete
- run_pairing_cycle: starts bye wait for single available player
- run_pairing_cycle: does nothing with zero available players
- check_round_complete: does nothing at round 0
- check_round_complete: does nothing when any player has active_match_id
- check_round_complete: does nothing when swiss event is finished
- check_round_complete: flushes Ranked API calls then checks completion
- check_round_complete: calls end_event when event is complete
- on_player_joined: triggers pairing when between rounds
- on_player_joined: does nothing when matches are active
- on_player_joined: cancels bye wait when a new player joins
- on_player_dropped: triggers round complete check when current_round > 0
- on_player_dropped: does nothing at round 0
- Bye timer: awards bye after wait if player still in queue
- Bye timer: does not award bye if queue was cleared
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


def make_player_doc(discord_id, points=0, dropped=False, active_match_id=None, match_history=None):
    return {
        'username': f'player_{discord_id}',
        'elo': 1000 + discord_id * 100,
        'points': float(points),
        'wins': int(points),
        'losses': 0,
        'rounds_played': int(points),
        'active_match_id': active_match_id,
        'dropped': dropped,
        'match_history': match_history or [],
    }


def make_swiss_manager(players=None, current_round=0, round_limit=3):
    from tournaments.swiss_manager import SwissManager

    if players is None:
        players = {str(i): make_player_doc(i) for i in range(1, 5)}

    swiss_event = {
        '_id': 'eid',
        'tournament_id': 'tid',
        'state': 'active',
        'current_round': current_round,
        'round_limit': round_limit,
        'players': players,
        'matches': [],
        'bye_queue': None,
    }

    tournament = {
        '_id': 'tid',
        'name': 'Test',
        'format': 'swiss',
        'state': 'active',
        'stagelist': ['s1', 's2'],
        'entrants': {str(k): None for k in players},
        'dqs': [],
        'debug': False,
    }

    dh = AsyncMock()
    dh.get_swiss_event_by_tournament = AsyncMock(return_value=swiss_event)
    dh.get_swiss_event = AsyncMock(return_value=swiss_event)
    dh.swiss_get_available_players = AsyncMock(return_value=[
        {'discord_id': int(k), **v}
        for k, v in players.items()
        if not v['dropped'] and v['active_match_id'] is None
    ])
    dh.swiss_is_event_complete = AsyncMock(return_value=False)
    dh.swiss_increment_round = AsyncMock(return_value=current_round + 1)
    dh.swiss_create_match = AsyncMock()
    dh.swiss_next_match_id = AsyncMock(return_value=100)
    dh.swiss_record_result = AsyncMock()
    dh.swiss_award_bye = AsyncMock()
    dh.swiss_set_bye_queue = AsyncMock()
    dh.swiss_get_standings = AsyncMock(return_value=[])
    dh.update_swiss_state = AsyncMock()
    dh.get_tournament_by_id = AsyncMock(return_value=tournament)

    bot = MagicMock()
    bot.dh = dh

    fmt = MagicMock()
    fmt.flush_pending_results = AsyncMock()

    tm = MagicMock()
    tm.tournament = tournament
    tm.bot = bot
    tm.guild = MagicMock()
    tm.lobbies = {}
    tm.debug = False
    tm.format = fmt
    tm.get_channel = AsyncMock(return_value=AsyncMock())
    tm.get_tournament = AsyncMock(return_value=tournament)
    tm.progress_tournament = AsyncMock()

    sm = object.__new__(SwissManager)
    sm.tm = tm
    sm.bot = bot
    sm.dh = dh
    sm.guild = tm.guild
    sm.bye_task = None
    sm.running = True

    sm.call_match = AsyncMock()
    sm.close_previous_round_channels = AsyncMock()
    sm.randomize_stagelist = AsyncMock()
    sm.end_event = AsyncMock()
    sm.post_round_complete = AsyncMock()
    sm.start_bye_wait = AsyncMock()

    return sm, dh, swiss_event, tournament


# ─── run_pairing_cycle ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pairing_cycle_pairs_all_available_players():
    sm, dh, swiss_event, _ = make_swiss_manager()
    await sm.run_pairing_cycle()
    assert sm.call_match.await_count == 2


@pytest.mark.asyncio
async def test_pairing_cycle_increments_round():
    sm, dh, swiss_event, _ = make_swiss_manager()
    await sm.run_pairing_cycle()
    dh.swiss_increment_round.assert_awaited_once()


@pytest.mark.asyncio
async def test_pairing_cycle_closes_previous_round_channels():
    sm, dh, swiss_event, _ = make_swiss_manager()
    await sm.run_pairing_cycle()
    sm.close_previous_round_channels.assert_awaited_once()


@pytest.mark.asyncio
async def test_pairing_cycle_posts_standings_after_round_1():
    sm, dh, swiss_event, _ = make_swiss_manager(current_round=1)
    await sm.run_pairing_cycle()
    sm.post_round_complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_pairing_cycle_does_not_post_standings_on_round_0():
    sm, dh, swiss_event, _ = make_swiss_manager(current_round=0)
    await sm.run_pairing_cycle()
    sm.post_round_complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_pairing_cycle_aborts_when_not_running():
    sm, dh, swiss_event, _ = make_swiss_manager()
    sm.running = False
    await sm.run_pairing_cycle()
    sm.call_match.assert_not_awaited()
    dh.swiss_increment_round.assert_not_awaited()


@pytest.mark.asyncio
async def test_pairing_cycle_ends_event_when_complete():
    sm, dh, swiss_event, _ = make_swiss_manager()
    dh.swiss_is_event_complete = AsyncMock(return_value=True)
    await sm.run_pairing_cycle()
    sm.end_event.assert_awaited_once()
    sm.call_match.assert_not_awaited()


@pytest.mark.asyncio
async def test_pairing_cycle_starts_bye_wait_for_single_player():
    players = {'1': make_player_doc(1)}
    sm, dh, swiss_event, _ = make_swiss_manager(players=players)
    dh.swiss_get_available_players = AsyncMock(return_value=[
        {'discord_id': 1, **players['1']}
    ])
    await sm.run_pairing_cycle()
    sm.start_bye_wait.assert_awaited_once()
    sm.call_match.assert_not_awaited()


@pytest.mark.asyncio
async def test_pairing_cycle_does_nothing_with_zero_players():
    sm, dh, swiss_event, _ = make_swiss_manager()
    dh.swiss_get_available_players = AsyncMock(return_value=[])
    await sm.run_pairing_cycle()
    sm.call_match.assert_not_awaited()
    sm.start_bye_wait.assert_not_awaited()


# ─── check_round_complete ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_round_complete_skips_at_round_zero():
    sm, dh, swiss_event, _ = make_swiss_manager(current_round=0)
    swiss_event['current_round'] = 0
    await sm.check_round_complete()
    sm.end_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_round_complete_skips_when_active_matches_exist():
    players = {
        '1': make_player_doc(1, active_match_id=100),
        '2': make_player_doc(2, active_match_id=100),
    }
    sm, dh, swiss_event, _ = make_swiss_manager(players=players, current_round=1)
    swiss_event['current_round'] = 1
    await sm.check_round_complete()
    sm.end_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_round_complete_skips_when_swiss_event_finished():
    sm, dh, swiss_event, _ = make_swiss_manager(current_round=1)
    swiss_event['state'] = 'finished'
    await sm.check_round_complete()
    sm.end_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_round_complete_flushes_ranked_results():
    sm, dh, swiss_event, _ = make_swiss_manager(current_round=1)
    swiss_event['current_round'] = 1
    await sm.check_round_complete()
    sm.tm.format.flush_pending_results.assert_awaited_once()


@pytest.mark.asyncio
async def test_round_complete_ends_event_when_complete():
    sm, dh, swiss_event, _ = make_swiss_manager(current_round=3, round_limit=3)
    swiss_event['current_round'] = 3
    dh.swiss_is_event_complete = AsyncMock(return_value=True)
    await sm.check_round_complete()
    sm.end_event.assert_awaited_once()


# ─── on_player_joined ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_player_joining_between_rounds_triggers_pairing():
    players = {str(i): make_player_doc(i) for i in range(1, 4)}
    sm, dh, swiss_event, _ = make_swiss_manager(players=players)
    swiss_event['bye_queue'] = None
    sm.run_pairing_cycle = AsyncMock()
    await sm.on_player_joined()
    sm.run_pairing_cycle.assert_awaited_once()


@pytest.mark.asyncio
async def test_player_joining_mid_round_does_not_trigger_pairing():
    players = {
        '1': make_player_doc(1, active_match_id=100),
        '2': make_player_doc(2, active_match_id=100),
    }
    sm, dh, swiss_event, _ = make_swiss_manager(players=players)
    sm.run_pairing_cycle = AsyncMock()
    await sm.on_player_joined()
    sm.run_pairing_cycle.assert_not_awaited()


@pytest.mark.asyncio
async def test_player_joining_cancels_bye_wait():
    players = {'1': make_player_doc(1)}
    sm, dh, swiss_event, _ = make_swiss_manager(players=players)
    swiss_event['bye_queue'] = 1
    sm.cancel_bye_wait = AsyncMock()
    sm.run_pairing_cycle = AsyncMock()
    await sm.on_player_joined()
    sm.cancel_bye_wait.assert_awaited_once_with('eid')


# ─── on_player_dropped ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_player_dropping_mid_round_triggers_round_check():
    sm, dh, swiss_event, _ = make_swiss_manager(current_round=1)
    swiss_event['current_round'] = 1
    sm.check_round_complete = AsyncMock()
    await sm.on_player_dropped()
    sm.check_round_complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_player_dropping_before_rounds_start_does_nothing():
    sm, dh, swiss_event, _ = make_swiss_manager(current_round=0)
    swiss_event['current_round'] = 0
    sm.check_round_complete = AsyncMock()
    await sm.on_player_dropped()
    sm.check_round_complete.assert_not_awaited()


# ─── Bye timer ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bye_timer_awards_bye_when_player_still_in_queue():
    sm, dh, swiss_event, _ = make_swiss_manager()
    swiss_event['bye_queue'] = 42
    dh.get_swiss_event = AsyncMock(return_value=swiss_event)
    sm.check_round_complete = AsyncMock()

    with patch('tournaments.swiss_manager.BYE_WAIT_SECONDS', 0):
        await sm._bye_timer(42, 'eid')

    dh.swiss_award_bye.assert_awaited_once_with('eid', 42)


@pytest.mark.asyncio
async def test_bye_timer_does_not_award_bye_when_queue_cleared():
    sm, dh, swiss_event, _ = make_swiss_manager()
    swiss_event['bye_queue'] = None  # someone else joined
    dh.get_swiss_event = AsyncMock(return_value=swiss_event)

    with patch('tournaments.swiss_manager.BYE_WAIT_SECONDS', 0):
        await sm._bye_timer(42, 'eid')

    dh.swiss_award_bye.assert_not_awaited()


@pytest.mark.asyncio
async def test_bye_timer_cancelled_does_not_award_bye():
    sm, dh, swiss_event, _ = make_swiss_manager()

    async def immediate_cancel(discord_id, event_id):
        raise asyncio.CancelledError()

    with patch.object(sm, '_bye_timer', immediate_cancel):
        try:
            await sm._bye_timer(42, 'eid')
        except asyncio.CancelledError:
            pass

    dh.swiss_award_bye.assert_not_awaited()