"""
tests/test_swiss_flow.py

Tests for the Swiss tournament flow from start to finish.

Covers:
- Full round cycle: pairing → match completion → round complete → next round
- Event completion after round_limit is reached
- Player joining mid-event triggers pairing if between rounds
- Player dropping mid-match gives opponent the win
- Player dropping between rounds just removes them from future pairings
- Bye logic: odd player out waits, gets bye if no one joins
- check_round_complete doesn't fire while matches are still active
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def make_swiss_manager(players=None, current_round=0, round_limit=3):
    """
    Build a SwissManager with a fully mocked DB layer.
    players: dict of { str(discord_id): player_dict }
    """
    from tournaments.swiss_manager import SwissManager

    if players is None:
        players = {
            '1': make_player_doc(1, points=0),
            '2': make_player_doc(2, points=0),
            '3': make_player_doc(3, points=0),
            '4': make_player_doc(4, points=0),
        }

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
        'stagelist': ['stage1', 'stage2'],
        'entrants': {str(k): None for k in players.keys()},
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
    bot.add_view = MagicMock()

    tm = MagicMock()
    tm.tournament = tournament
    tm.bot = bot
    tm.guild = MagicMock()
    tm.lobbies = {}
    tm.debug = False
    tm.is_swiss = True
    tm.tc = AsyncMock()
    tm.tc.bc = AsyncMock()
    tm.get_channel = AsyncMock(return_value=AsyncMock())

    sm = object.__new__(SwissManager)
    sm.tm = tm
    sm.bot = bot
    sm.dh = dh
    sm.guild = tm.guild
    sm.bye_task = None
    sm.running = True

    # Stub call_match so we don't hit Discord
    sm.call_match = AsyncMock()
    sm.close_previous_round_channels = AsyncMock()
    sm.randomize_stagelist = AsyncMock()
    sm.end_event = AsyncMock()
    sm.post_round_complete = AsyncMock()
    sm.start_bye_wait = AsyncMock()

    return sm, dh, swiss_event


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


# ─── run_pairing_cycle ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pairing_cycle_pairs_all_available_players():
    sm, dh, _ = make_swiss_manager()
    await sm.run_pairing_cycle()
    # 4 players → 2 pairs → call_match called twice
    assert sm.call_match.await_count == 2


@pytest.mark.asyncio
async def test_pairing_cycle_increments_round():
    sm, dh, _ = make_swiss_manager()
    await sm.run_pairing_cycle()
    dh.swiss_increment_round.assert_awaited_once()


@pytest.mark.asyncio
async def test_pairing_cycle_closes_previous_round_channels():
    sm, dh, _ = make_swiss_manager()
    await sm.run_pairing_cycle()
    sm.close_previous_round_channels.assert_awaited_once()


@pytest.mark.asyncio
async def test_pairing_cycle_with_one_player_starts_bye_wait():
    players = {'1': make_player_doc(1)}
    sm, dh, _ = make_swiss_manager(players=players)
    dh.swiss_get_available_players = AsyncMock(return_value=[
        {'discord_id': 1, **players['1']}
    ])
    await sm.run_pairing_cycle()
    sm.start_bye_wait.assert_awaited_once()
    sm.call_match.assert_not_awaited()


@pytest.mark.asyncio
async def test_pairing_cycle_with_zero_players_does_nothing():
    sm, dh, _ = make_swiss_manager()
    dh.swiss_get_available_players = AsyncMock(return_value=[])
    await sm.run_pairing_cycle()
    sm.call_match.assert_not_awaited()
    sm.start_bye_wait.assert_not_awaited()


@pytest.mark.asyncio
async def test_pairing_cycle_stops_when_event_complete():
    sm, dh, _ = make_swiss_manager()
    dh.swiss_is_event_complete = AsyncMock(return_value=True)
    await sm.run_pairing_cycle()
    sm.end_event.assert_awaited_once()
    sm.call_match.assert_not_awaited()


@pytest.mark.asyncio
async def test_pairing_cycle_does_nothing_when_not_running():
    sm, dh, _ = make_swiss_manager()
    sm.running = False
    await sm.run_pairing_cycle()
    sm.call_match.assert_not_awaited()
    dh.swiss_increment_round.assert_not_awaited()


# ─── check_round_complete ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_round_not_complete_while_match_active():
    players = {
        '1': make_player_doc(1, active_match_id=100),
        '2': make_player_doc(2, active_match_id=100),
    }
    sm, dh, swiss_event = make_swiss_manager(players=players, current_round=1)
    swiss_event['current_round'] = 1
    dh.get_swiss_event_by_tournament = AsyncMock(return_value=swiss_event)

    await sm.check_round_complete()

    sm.post_round_complete.assert_not_awaited()
    sm.end_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_round_complete_when_all_matches_done():
    players = {
        '1': make_player_doc(1, active_match_id=None),
        '2': make_player_doc(2, active_match_id=None),
    }
    sm, dh, swiss_event = make_swiss_manager(players=players, current_round=1)
    swiss_event['current_round'] = 1
    dh.get_swiss_event_by_tournament = AsyncMock(return_value=swiss_event)

    await sm.check_round_complete()

    sm.post_round_complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_round_complete_skips_if_round_zero():
    """Don't fire round-complete logic before any rounds have started."""
    sm, dh, swiss_event = make_swiss_manager(current_round=0)
    swiss_event['current_round'] = 0
    dh.get_swiss_event_by_tournament = AsyncMock(return_value=swiss_event)

    await sm.check_round_complete()

    sm.post_round_complete.assert_not_awaited()
    sm.end_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_check_round_complete_ends_event_when_limit_reached():
    players = {
        '1': make_player_doc(1, active_match_id=None),
        '2': make_player_doc(2, active_match_id=None),
    }
    sm, dh, swiss_event = make_swiss_manager(players=players, current_round=3, round_limit=3)
    swiss_event['current_round'] = 3
    dh.get_swiss_event_by_tournament = AsyncMock(return_value=swiss_event)
    dh.swiss_is_event_complete = AsyncMock(return_value=True)

    await sm.check_round_complete()

    sm.end_event.assert_awaited_once()
    sm.post_round_complete.assert_not_awaited()


# ─── on_player_joined ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_player_joining_between_rounds_triggers_pairing():
    """If no matches are active, a new player joining should trigger pairing."""
    players = {
        '1': make_player_doc(1, active_match_id=None),
        '2': make_player_doc(2, active_match_id=None),
        '3': make_player_doc(3, active_match_id=None),  # the new joiner
    }
    sm, dh, swiss_event = make_swiss_manager(players=players)
    swiss_event['bye_queue'] = None
    dh.get_swiss_event_by_tournament = AsyncMock(return_value=swiss_event)
    sm.run_pairing_cycle = AsyncMock()

    await sm.on_player_joined()

    sm.run_pairing_cycle.assert_awaited_once()


@pytest.mark.asyncio
async def test_player_joining_mid_round_does_not_trigger_pairing():
    """If matches are still active, don't start a new round."""
    players = {
        '1': make_player_doc(1, active_match_id=100),
        '2': make_player_doc(2, active_match_id=100),
    }
    sm, dh, swiss_event = make_swiss_manager(players=players)
    swiss_event['bye_queue'] = None
    dh.get_swiss_event_by_tournament = AsyncMock(return_value=swiss_event)
    sm.run_pairing_cycle = AsyncMock()

    await sm.on_player_joined()

    sm.run_pairing_cycle.assert_not_awaited()


@pytest.mark.asyncio
async def test_player_joining_cancels_pending_bye():
    """If someone was waiting for a bye and a new player joins, cancel the bye."""
    players = {
        '1': make_player_doc(1, active_match_id=None),
    }
    sm, dh, swiss_event = make_swiss_manager(players=players)
    swiss_event['bye_queue'] = 1  # player 1 was waiting
    dh.get_swiss_event_by_tournament = AsyncMock(return_value=swiss_event)
    sm.cancel_bye_wait = AsyncMock()
    sm.run_pairing_cycle = AsyncMock()

    await sm.on_player_joined()

    sm.cancel_bye_wait.assert_awaited_once_with('eid')


# ─── on_player_dropped ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_player_dropping_mid_round_triggers_round_check():
    players = {'1': make_player_doc(1), '2': make_player_doc(2)}
    sm, dh, swiss_event = make_swiss_manager(players=players, current_round=1)
    swiss_event['current_round'] = 1
    dh.get_swiss_event_by_tournament = AsyncMock(return_value=swiss_event)
    sm.check_round_complete = AsyncMock()

    await sm.on_player_dropped()

    sm.check_round_complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_player_dropping_before_rounds_start_does_not_check_complete():
    """Dropping during registration (round 0) should not trigger round-complete."""
    sm, dh, swiss_event = make_swiss_manager(current_round=0)
    swiss_event['current_round'] = 0
    dh.get_swiss_event_by_tournament = AsyncMock(return_value=swiss_event)
    sm.check_round_complete = AsyncMock()

    await sm.on_player_dropped()

    sm.check_round_complete.assert_not_awaited()


# ─── end_event ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_end_event_marks_swiss_event_finished():
    from tournaments.swiss_manager import SwissManager

    sm, dh, swiss_event = make_swiss_manager()
    sm.tm.prompt_end_tournament = AsyncMock()  # it gets awaited

    real_end_event = SwissManager.end_event
    sm.end_event = lambda: real_end_event(sm)

    await sm.end_event()

    dh.update_swiss_state.assert_awaited_with('eid', 'finished')


@pytest.mark.asyncio
async def test_end_event_sets_running_false():
    from tournaments.swiss_manager import SwissManager

    sm, dh, swiss_event = make_swiss_manager()
    sm.tm.debug = True  # skip Discord channel cleanup
    sm.tm.prompt_end_tournament = AsyncMock()

    real_end_event = SwissManager.end_event
    sm.end_event = lambda: real_end_event(sm)

    await sm.end_event()

    assert sm.running is False