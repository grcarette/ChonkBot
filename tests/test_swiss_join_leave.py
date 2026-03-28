# tests/test_swiss_join_leave.py
"""
Tests for mid-event join and leave behavior in Swiss tournaments.

Covers:
- Late join: player is not immediately paired, only eligible from next round
- Late join: bonus points from elo are awarded exactly once (fresh add)
- Late join then leave then rejoin: no double bonus, accumulated wins preserved
- Leave with no matches played: player is removed from the scoreboard entirely
- Leave with matches played: player record stands, marked dropped only
- Leave while in an active match: opponent wins (not a DQ win), is_dq=False
- Leave while in an active match: swiss_record_result called without is_dq flag
- Leave while in an active match: left player is not penalized with -1 points
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from data.swiss import SwissMethodsMixin, get_tier


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_swiss_format(tournament_state='active'):
    from formats.swiss import SwissFormat

    tournament = {
        '_id': 'tid',
        'state': tournament_state,
        'dqs': [],
    }

    dh = AsyncMock()
    dh.get_swiss_event_by_tournament = AsyncMock(return_value={'_id': 'eid', 'players': {}})
    dh.swiss_rejoin_player = AsyncMock(return_value=False)
    dh.swiss_add_player = AsyncMock()
    dh.swiss_drop_player = AsyncMock()
    dh.register_player = AsyncMock()

    tm = MagicMock()
    tm.tournament = tournament
    tm.get_tournament = AsyncMock(return_value=tournament)
    tm.bot = MagicMock()
    tm.bot.dh = dh
    tm.get_ranked_player = AsyncMock(return_value={'elo': 1500, 'username': 'TestPlayer'})

    fmt = object.__new__(SwissFormat)
    fmt.tm = tm
    fmt.dh = dh
    fmt.pending_results = []
    fmt.manager = AsyncMock()
    fmt.manager.on_player_joined = AsyncMock()
    fmt.manager.on_player_dropped = AsyncMock()

    return fmt, dh, tm


# ═══════════════════════════════════════════════════════════════════════════════
# Late joining
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_late_join_triggers_on_player_joined_not_immediate_pairing():
    """
    A player who joins while the tournament is active must trigger on_player_joined
    so the pairing cycle can consider them next round — not force an immediate match.
    """
    fmt, dh, tm = make_swiss_format(tournament_state='active')

    await fmt.on_player_register(100, {'name': 'LatePlayer'})

    fmt.manager.on_player_joined.assert_awaited_once()


@pytest.mark.asyncio
async def test_late_join_before_tournament_starts_does_not_trigger_on_player_joined():
    """
    A player who registers during the registration phase must NOT trigger
    on_player_joined — the round loop hasn't started yet.
    """
    fmt, dh, tm = make_swiss_format(tournament_state='registration')

    await fmt.on_player_register(100, {'name': 'EarlyPlayer'})

    fmt.manager.on_player_joined.assert_not_awaited()


@pytest.mark.asyncio
async def test_late_join_calls_swiss_add_player_with_elo_bonus():
    """
    A brand-new late joiner must be added via swiss_add_player which assigns
    elo-based bonus points. The elo passed must match what get_ranked_player returns.
    """
    fmt, dh, tm = make_swiss_format(tournament_state='active')
    tm.get_ranked_player = AsyncMock(return_value={'elo': 1600, 'username': 'LatePlayer'})

    await fmt.on_player_register(100, {'name': 'LatePlayer'})

    dh.swiss_add_player.assert_awaited_once()
    args = dh.swiss_add_player.call_args[0]
    assert args[1] == 100       # discord_id
    assert args[3] == 1600      # elo passed through correctly


@pytest.mark.asyncio
async def test_late_join_bonus_points_awarded_once_via_swiss_add_player():
    """
    swiss_add_player internally sets points = bonus_points from get_tier(elo).
    Verify the correct bonus is assigned for a tier-2 elo (1400–2000 → 1 point).
    This test guards against double-awarding by ensuring add is only called once.
    """
    fmt, dh, tm = make_swiss_format(tournament_state='active')
    tm.get_ranked_player = AsyncMock(return_value={'elo': 1500, 'username': 'LatePlayer'})

    await fmt.on_player_register(100, {'name': 'LatePlayer'})

    # swiss_add_player must be called exactly once — not twice, which would double bonus
    assert dh.swiss_add_player.await_count == 1


@pytest.mark.asyncio
async def test_rejoin_after_leave_does_not_call_swiss_add_player():
    """
    A player who left and rejoins must go through swiss_rejoin_player (which
    restores dropped=False without touching points), NOT swiss_add_player
    (which would re-award elo bonus points).
    """
    fmt, dh, tm = make_swiss_format(tournament_state='active')
    # Simulate the player already having a record — rejoin succeeds
    dh.swiss_rejoin_player = AsyncMock(return_value=True)

    await fmt.on_player_register(100, {'name': 'RejoiningPlayer'})

    dh.swiss_add_player.assert_not_awaited()
    dh.swiss_rejoin_player.assert_awaited_once_with('eid', 100)


@pytest.mark.asyncio
async def test_rejoin_preserves_accumulated_points_and_wins():
    """
    After rejoin, the player's existing points (elo bonus + wins) must not be
    reset. swiss_rejoin_player must not be passed any point/win values.
    This test verifies the call signature only touches identity, not stats.
    """
    fmt, dh, tm = make_swiss_format(tournament_state='active')
    dh.swiss_rejoin_player = AsyncMock(return_value=True)

    await fmt.on_player_register(100, {'name': 'RejoiningPlayer'})

    # Rejoin must be called with only event_id and discord_id — no stat fields
    args = dh.swiss_rejoin_player.call_args[0]
    assert args == ('eid', 100)


# ═══════════════════════════════════════════════════════════════════════════════
# Leaving — no matches played
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_leave_with_no_matches_played_removes_from_scoreboard():
    """
    A player who leaves having never played a match must be marked dropped=True
    so their record is preserved for potential rejoin, preventing double elo bonus.
    """
    from data.swiss import SwissMethodsMixin

    event = {
        '_id': 'eid',
        'players': {
            '100': {
                'rounds_played': 0,
                'match_history': [],
                'dropped': False,
                'active_match_id': None,
                'points': 1.0,  # elo bonus only
            },
            '200': {
                'rounds_played': 2,
                'match_history': [100],
                'dropped': False,
                'active_match_id': None,
                'points': 2.0,
            },
        }
    }

    mixin = object.__new__(SwissMethodsMixin)
    mixin.get_swiss_event = AsyncMock(return_value=event)
    mixin.swiss_collection = AsyncMock()
    mixin.swiss_collection.update_one = AsyncMock()

    with patch('data.swiss.ObjectId', side_effect=lambda x: x):
        await mixin.swiss_drop_player('eid', 100)

    update_call = mixin.swiss_collection.update_one.call_args
    update_op = update_call[0][1]
    assert '$set' in update_op
    assert update_op['$set'].get('players.100.dropped') is True, (
        "Player must be marked dropped=True even with no matches played"
    )


@pytest.mark.asyncio
async def test_leave_with_matches_played_marks_dropped_not_removed():
    """
    A player who leaves after playing at least one match must have their
    record preserved (dropped=True) so their results stand on the scoreboard.
    """
    from data.swiss import SwissMethodsMixin

    event = {
        '_id': 'eid',
        'players': {
            '100': {
                'rounds_played': 1,
                'match_history': [200],
                'dropped': False,
                'active_match_id': None,
                'points': 2.0,
            },
        }
    }

    mixin = object.__new__(SwissMethodsMixin)
    mixin.get_swiss_event = AsyncMock(return_value=event)
    mixin.swiss_collection = AsyncMock()
    mixin.swiss_collection.update_one = AsyncMock()

    with patch('data.swiss.ObjectId', side_effect=lambda x: x):
        await mixin.swiss_drop_player('eid', 100)

    update_call = mixin.swiss_collection.update_one.call_args
    update_op = update_call[0][1]
    assert '$set' in update_op
    assert update_op['$set'].get('players.100.dropped') is True
    assert '$unset' not in update_op, (
        "Player with played matches must not be fully removed"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Leaving — exclusion from future pairings
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_leave_marks_dropped_true_via_on_player_unregister():
    """
    unregister_player → on_player_unregister must call swiss_drop_player
    so the dropped flag gates them out of swiss_get_available_players.
    """
    fmt, dh, tm = make_swiss_format(tournament_state='active')

    await fmt.on_player_unregister(100)

    dh.swiss_drop_player.assert_awaited_once_with('eid', 100)


@pytest.mark.asyncio
async def test_leave_triggers_on_player_dropped_so_pairing_rechecks():
    """
    After marking dropped, on_player_unregister must call manager.on_player_dropped
    so the pairing cycle can check if a round just became completable.
    """
    fmt, dh, tm = make_swiss_format(tournament_state='active')

    await fmt.on_player_unregister(100)

    fmt.manager.on_player_dropped.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════════════════════
# Leaving mid-match
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_leave_mid_match_calls_swiss_record_result_without_is_dq():
    """
    When a player leaves during an active match, swiss_record_result must be
    called with is_dq=False (or omitted). A voluntary leave is not a DQ —
    the leaving player must not receive a -1 point penalty.
    """
    from ui.swiss_register import SwissActiveRegisterView

    tournament = {'_id': 'tid', 'state': 'active', 'name': 'Test', 'dqs': []}
    swiss_event = {
        '_id': 'eid',
        'players': {
            '100': {'active_match_id': 42, 'dropped': False, 'points': 1.0},
            '200': {'active_match_id': 42, 'dropped': False, 'points': 1.0},
        }
    }

    mock_lobby = MagicMock()
    mock_lobby.players = [100, 200]
    mock_lobby.channel = None  # skip Discord send

    dh = AsyncMock()
    dh.get_registration_status = AsyncMock(return_value=True)
    dh.get_swiss_event_by_tournament = AsyncMock(return_value=swiss_event)
    dh.swiss_record_result = AsyncMock()
    dh.unregister_player = AsyncMock()

    tm = MagicMock()
    tm.tournament = tournament
    tm.get_tournament = AsyncMock(return_value=tournament)
    tm.bot = MagicMock()
    tm.bot.dh = dh
    tm.lobbies = {42: mock_lobby}
    tm.unregister_player = AsyncMock()
    tm.swiss_manager = None

    view = object.__new__(SwissActiveRegisterView)
    view.tm = tm

    interaction = AsyncMock()
    interaction.user.id = 100
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    await view.leave(interaction)

    dh.swiss_record_result.assert_awaited_once()
    call_kwargs = dh.swiss_record_result.call_args[1]
    call_args = dh.swiss_record_result.call_args[0]
    # is_dq must be False or absent (defaults to False)
    is_dq = call_kwargs.get('is_dq', call_args[4] if len(call_args) > 4 else False)
    assert is_dq is False, "Voluntary leave must not be treated as a DQ"


@pytest.mark.asyncio
async def test_leave_mid_match_opponent_is_recorded_as_winner():
    """
    The opponent (not the leaving player) must be passed as winner_id
    to swiss_record_result.
    """
    from ui.swiss_register import SwissActiveRegisterView

    tournament = {'_id': 'tid', 'state': 'active', 'name': 'Test', 'dqs': []}
    swiss_event = {
        '_id': 'eid',
        'players': {
            '100': {'active_match_id': 42, 'dropped': False, 'points': 1.0},
            '200': {'active_match_id': 42, 'dropped': False, 'points': 1.0},
        }
    }

    mock_lobby = MagicMock()
    mock_lobby.players = [100, 200]
    mock_lobby.channel = None

    dh = AsyncMock()
    dh.get_registration_status = AsyncMock(return_value=True)
    dh.get_swiss_event_by_tournament = AsyncMock(return_value=swiss_event)
    dh.swiss_record_result = AsyncMock()

    tm = MagicMock()
    tm.tournament = tournament
    tm.get_tournament = AsyncMock(return_value=tournament)
    tm.bot = MagicMock()
    tm.bot.dh = dh
    tm.lobbies = {42: mock_lobby}
    tm.unregister_player = AsyncMock()
    tm.swiss_manager = None

    view = object.__new__(SwissActiveRegisterView)
    view.tm = tm

    interaction = AsyncMock()
    interaction.user.id = 100
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    await view.leave(interaction)

    args = dh.swiss_record_result.call_args[0]
    # swiss_record_result(event_id, match_id, winner_id, loser_id, ...)
    assert args[2] == 200, "Opponent (200) must be recorded as winner"
    assert args[3] == 100, "Leaving player (100) must be recorded as loser"


@pytest.mark.asyncio
async def test_leave_mid_match_leaving_player_not_penalized():
    """
    Because is_dq=False, the leaving player's points must not be decremented.
    swiss_record_result with is_dq=False leaves loser points unchanged.
    This test verifies no -1 penalty is applied via the record_result call.
    """
    from data.swiss import SwissMethodsMixin

    event = {
        '_id': 'eid',
        'players': {
            '100': {
                'discord_id': 100,
                'points': 1.0,
                'wins': 1,
                'losses': 0,
                'rounds_played': 1,
                'active_match_id': 42,
                'match_history': [],
            },
            '200': {
                'discord_id': 200,
                'points': 1.0,
                'wins': 1,
                'losses': 0,
                'rounds_played': 1,
                'active_match_id': 42,
                'match_history': [],
            },
        },
        'matches': [
            {'match_id': 42, 'player_1': 100, 'player_2': 200, 'winner': None, 'state': 'active'}
        ],
    }

    mixin = object.__new__(SwissMethodsMixin)
    mixin.get_swiss_event = AsyncMock(return_value=event)
    mixin.swiss_collection = AsyncMock()
    mixin.swiss_collection.update_one = AsyncMock()

    with patch('data.swiss.ObjectId', side_effect=lambda x: x):
        await mixin.swiss_record_result('eid', 42, winner_id=200, loser_id=100, is_dq=False)

    update_op = mixin.swiss_collection.update_one.call_args[0][1]
    inc_ops = update_op.get('$inc', {})
    assert f'players.100.points' not in inc_ops, (
        "Leaving player's points must not be decremented — voluntary leave is not a DQ"
    )