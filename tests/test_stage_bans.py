# tests/test_stage_bans.py
"""
Tests for stage ban behavior in solo and teams mode.

Covers:
- Solo mode: each player must submit their own bans
- Solo mode: a non-participant cannot submit bans
- Teams mode: first submission from a team locks out the teammate
- Teams mode: second submission from the same team is silently ignored
- Teams mode: both team slots must submit before bans complete
- Teams mode: non-participant is blocked
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio


def make_lobby(is_teams_mode=False, remaining_players=None):
    lobby = MagicMock()
    lobby.match_id = 1
    lobby.stages = ['s1', 's2', 's3', 's4', 's5']
    lobby.dh = AsyncMock()
    lobby.dh.get_stage = AsyncMock(side_effect=lambda code: {'code': code, 'name': code})

    tm = MagicMock()
    tm.is_teams_mode = is_teams_mode

    if is_teams_mode:
        lobby.remaining_players = remaining_players or ['101_102', '201_202']
        async def resolve(slots):
            mapping = {'101_102': [101, 102], '201_202': [201, 202]}
            result = []
            for s in slots:
                result.extend(mapping.get(str(s), []))
            return result
        tm.resolve_team_members = AsyncMock(side_effect=resolve)

        async def resolve_slot(user_id):
            for team_id in lobby.remaining_players:
                p1, p2 = (int(x) for x in str(team_id).split('_'))
                if user_id in (p1, p2):
                    return team_id
            return None
        lobby._resolve_checkin_slot = AsyncMock(side_effect=resolve_slot)
    else:
        lobby.remaining_players = remaining_players or [101, 201]
        async def resolve_slot_solo(user_id):
            return user_id if user_id in lobby.remaining_players else None
        lobby._resolve_checkin_slot = AsyncMock(side_effect=resolve_slot_solo)

    lobby.tournament_manager = tm
    lobby.check_to_role = AsyncMock(return_value=False)
    lobby.end_stage_bans = AsyncMock()
    return lobby


def make_ban_button(lobby):
    from ui.stage_bans import BanStagesButton
    view = object.__new__(BanStagesButton)
    view.lobby = lobby
    view.num_stage_bans = 2
    view.banned_stages = []
    view.player_bans = {}
    view.finished_users = []
    view.message = AsyncMock()
    view.message.edit = AsyncMock()
    view.message.delete = AsyncMock()
    view._lock = asyncio.Lock()
    view.stop = MagicMock()
    # Stub generate_embed so we don't hit file I/O
    view.generate_embed = AsyncMock(return_value=(MagicMock(), MagicMock()))
    return view


# ─── Solo mode ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_solo_both_players_must_submit():
    lobby = make_lobby(is_teams_mode=False)
    view = make_ban_button(lobby)

    user1 = MagicMock()
    user1.id = 101
    user2 = MagicMock()
    user2.id = 201

    await view.submit_player_bans(user1, ['s1', 's2'])
    assert not lobby.end_stage_bans.called

    await view.submit_player_bans(user2, ['s3', 's4'])
    lobby.end_stage_bans.assert_awaited_once()


@pytest.mark.asyncio
async def test_solo_non_participant_is_ignored():
    lobby = make_lobby(is_teams_mode=False)
    view = make_ban_button(lobby)

    outsider = MagicMock()
    outsider.id = 999

    await view.submit_player_bans(outsider, ['s1', 's2'])
    assert len(view.finished_users) == 0
    lobby.end_stage_bans.assert_not_awaited()


# ─── Teams mode ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_teams_first_submission_locks_out_teammate():
    lobby = make_lobby(is_teams_mode=True)
    view = make_ban_button(lobby)

    player1 = MagicMock()
    player1.id = 101  # member of team '101_102'

    await view.submit_player_bans(player1, ['s1', 's2'])

    # Slot is now locked
    assert '101_102' in view.finished_users

    # Teammate tries to submit
    player2 = MagicMock()
    player2.id = 102

    await view.submit_player_bans(player2, ['s3', 's4'])

    # Still only one submission recorded for this slot
    assert view.finished_users.count('101_102') == 1
    # Only player1's bans are stored
    assert player2 not in view.player_bans


@pytest.mark.asyncio
async def test_teams_both_slots_required_to_complete():
    lobby = make_lobby(is_teams_mode=True)
    view = make_ban_button(lobby)

    p1 = MagicMock()
    p1.id = 101
    p2 = MagicMock()
    p2.id = 201  # member of team '201_202'

    await view.submit_player_bans(p1, ['s1', 's2'])
    lobby.end_stage_bans.assert_not_awaited()

    await view.submit_player_bans(p2, ['s3', 's4'])
    lobby.end_stage_bans.assert_awaited_once()


@pytest.mark.asyncio
async def test_teams_non_participant_is_ignored():
    lobby = make_lobby(is_teams_mode=True)
    view = make_ban_button(lobby)

    outsider = MagicMock()
    outsider.id = 999

    await view.submit_player_bans(outsider, ['s1', 's2'])
    assert len(view.finished_users) == 0
    lobby.end_stage_bans.assert_not_awaited()


@pytest.mark.asyncio
async def test_teams_duplicate_slot_submission_does_not_double_count():
    """Concurrent submissions from both teammates should result in exactly one slot entry."""
    lobby = make_lobby(is_teams_mode=True)
    view = make_ban_button(lobby)

    p1 = MagicMock()
    p1.id = 101
    p2 = MagicMock()
    p2.id = 102

    # Fire both concurrently — the lock should ensure only one wins
    await asyncio.gather(
        view.submit_player_bans(p1, ['s1', 's2']),
        view.submit_player_bans(p2, ['s3', 's4']),
    )

    assert view.finished_users.count('101_102') == 1