# tests/test_match_report.py
"""
Tests for match reporting in solo and teams mode.

Covers:
- Solo: non-participant cannot submit a report
- Solo: both players must report the same winner to complete
- Solo: disagreement triggers redo_report
- Teams: non-participant cannot submit a report
- Teams: first submission from a slot locks out teammate
- Teams: both slots must report before completion
- Teams: disagreement between slots triggers redo_report
- Teams: TO override bypasses slot check and reports immediately
- MatchReportView: solo mode builds dropdown from user names
- MatchReportView: teams mode builds dropdown from team names
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


def make_lobby(is_teams_mode=False):
    lobby = MagicMock()
    lobby.match_id = 1
    lobby.organizer_role = 'Event Organizer'
    lobby.end_reporting = AsyncMock()
    lobby.channel = AsyncMock()
    lobby.dh = AsyncMock()

    tm = MagicMock()
    tm.is_teams_mode = is_teams_mode
    tm.get_tournament = AsyncMock(return_value={'entrants': {}})

    if is_teams_mode:
        lobby.remaining_players = ['101_102', '201_202']

        async def resolve_slot(user_id):
            for team_id in lobby.remaining_players:
                p1, p2 = (int(x) for x in str(team_id).split('_'))
                if user_id in (p1, p2):
                    return team_id
            return None

        async def parse_team(team_id):
            a, b = team_id.split('_')
            return int(a), int(b)

        tm._parse_team_id = MagicMock(side_effect=lambda tid: tuple(int(x) for x in tid.split('_')))
        lobby._resolve_checkin_slot = AsyncMock(side_effect=resolve_slot)
    else:
        lobby.remaining_players = [101, 201]

        async def resolve_slot_solo(user_id):
            return user_id if user_id in lobby.remaining_players else None

        lobby._resolve_checkin_slot = AsyncMock(side_effect=resolve_slot_solo)

    lobby.tournament_manager = tm
    return lobby


def make_report_button(lobby):
    from ui.match_report import MatchReportButton
    view = object.__new__(MatchReportButton)
    view.lobby = lobby
    view.reports = []
    view.user_reports = []
    view._lock = asyncio.Lock()
    view.redo_report = AsyncMock()
    return view


def make_user(user_id, roles=None):
    user = MagicMock()
    user.id = user_id
    user.roles = roles or []
    return user


def make_to_user(user_id, organizer_role_name='Event Organizer'):
    role = MagicMock()
    role.name = organizer_role_name
    return make_user(user_id, roles=[role])


# ═══════════════════════════════════════════════════════════════════════════════
# Solo mode
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_solo_non_participant_cannot_report():
    lobby = make_lobby(is_teams_mode=False)
    view = make_report_button(lobby)
    outsider = make_user(999)
    original_message = AsyncMock()

    await view.add_report(outsider, 101, original_message)

    assert len(view.user_reports) == 0
    lobby.end_reporting.assert_not_awaited()


@pytest.mark.asyncio
async def test_solo_both_players_must_report_same_winner():
    lobby = make_lobby(is_teams_mode=False)
    view = make_report_button(lobby)
    original_message = AsyncMock()

    await view.add_report(make_user(101), 101, original_message)
    lobby.end_reporting.assert_not_awaited()

    await view.add_report(make_user(201), 101, original_message)
    lobby.end_reporting.assert_awaited_once_with(101)


@pytest.mark.asyncio
async def test_solo_disagreement_triggers_redo():
    lobby = make_lobby(is_teams_mode=False)
    view = make_report_button(lobby)
    original_message = AsyncMock()

    await view.add_report(make_user(101), 101, original_message)
    await view.add_report(make_user(201), 201, original_message)

    view.redo_report.assert_awaited_once()
    lobby.end_reporting.assert_not_awaited()


# ═══════════════════════════════════════════════════════════════════════════════
# Teams mode
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_teams_non_participant_cannot_report():
    lobby = make_lobby(is_teams_mode=True)
    view = make_report_button(lobby)
    outsider = make_user(999)
    original_message = AsyncMock()

    await view.add_report(outsider, '101_102', original_message)

    assert len(view.user_reports) == 0
    lobby.end_reporting.assert_not_awaited()


@pytest.mark.asyncio
async def test_teams_teammate_blocked_after_first_submission():
    lobby = make_lobby(is_teams_mode=True)
    view = make_report_button(lobby)
    original_message = AsyncMock()

    await view.add_report(make_user(101), '101_102', original_message)
    assert '101_102' in view.user_reports

    # Teammate submits a different winner
    await view.add_report(make_user(102), '201_202', original_message)

    # Still only one entry for this slot
    assert view.user_reports.count('101_102') == 1


@pytest.mark.asyncio
async def test_teams_both_slots_required_to_complete():
    lobby = make_lobby(is_teams_mode=True)
    view = make_report_button(lobby)
    original_message = AsyncMock()

    await view.add_report(make_user(101), '101_102', original_message)
    lobby.end_reporting.assert_not_awaited()

    await view.add_report(make_user(201), '101_102', original_message)
    lobby.end_reporting.assert_awaited_once_with('101_102')


@pytest.mark.asyncio
async def test_teams_disagreement_triggers_redo():
    lobby = make_lobby(is_teams_mode=True)
    view = make_report_button(lobby)
    original_message = AsyncMock()

    await view.add_report(make_user(101), '101_102', original_message)
    await view.add_report(make_user(201), '201_202', original_message)

    view.redo_report.assert_awaited_once()
    lobby.end_reporting.assert_not_awaited()


@pytest.mark.asyncio
async def test_teams_to_override_reports_immediately():
    lobby = make_lobby(is_teams_mode=True)
    view = make_report_button(lobby)
    original_message = AsyncMock()
    to_user = make_to_user(999)

    await view.add_report(to_user, '101_102', original_message)

    lobby.end_reporting.assert_awaited_once_with('101_102')
    assert len(view.user_reports) == 0


@pytest.mark.asyncio
async def test_teams_concurrent_submissions_from_same_slot():
    """Both teammates submitting simultaneously should result in exactly one slot entry."""
    lobby = make_lobby(is_teams_mode=True)
    view = make_report_button(lobby)
    original_message = AsyncMock()

    await asyncio.gather(
        view.add_report(make_user(101), '101_102', original_message),
        view.add_report(make_user(102), '101_102', original_message),
    )

    assert view.user_reports.count('101_102') == 1


# ═══════════════════════════════════════════════════════════════════════════════
# MatchReportView dropdown
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_report_view_solo_shows_player_names():
    from ui.match_report import MatchReportView

    lobby = make_lobby(is_teams_mode=False)
    lobby.dh.get_user = AsyncMock(side_effect=lambda user_id=None: {
        101: {'name': 'Alice'},
        201: {'name': 'Bob'},
    }.get(user_id))

    view = object.__new__(MatchReportView)
    view.lobby = lobby
    view.winner = None
    view.parent = MagicMock()
    view.original_message = AsyncMock()
    view.players = {}
    view._children = []
    view.add_item = MagicMock()

    await view.setup()

    names = list(view.players.values())
    assert 'Alice' in names
    assert 'Bob' in names


@pytest.mark.asyncio
async def test_report_view_teams_shows_team_names():
    from ui.match_report import MatchReportView

    lobby = make_lobby(is_teams_mode=True)
    lobby.dh.get_user = AsyncMock(side_effect=lambda user_id=None: {
        101: {'name': 'Alice'},
        102: {'name': 'Charlie'},
        201: {'name': 'Bob'},
        202: {'name': 'Dave'},
    }.get(user_id))

    view = object.__new__(MatchReportView)
    view.lobby = lobby
    view.winner = None
    view.parent = MagicMock()
    view.original_message = AsyncMock()
    view.players = {}
    view._children = []
    view.add_item = MagicMock()

    await view.setup()

    names = list(view.players.values())
    assert 'Alice / Charlie' in names
    assert 'Bob / Dave' in names