"""
tests/test_match_report.py

Tests for MatchReportButton.add_report logic.

The Discord UI layer (button presses, interaction.response) is not tested here —
that's discord.py's responsibility. What we test is the pure state logic in
add_report, which determines when end_reporting is called, when redo_report
fires, and that the lock prevents double-submission.

Covers:
- Unanimous report calls end_reporting exactly once
- Disagreeing reports trigger redo_report and reset state
- A duplicate submission from the same user is ignored
- TO override calls end_reporting immediately, ignoring remaining players
- Concurrent submissions from both players only call end_reporting once
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock


def make_view(player_ids=(100, 200), organizer_role='Test TO'):
    """
    Build a MatchReportButton without hitting Discord or instantiating a real View.
    We bypass __init__ because it calls discord.ui.View.__init__ which requires
    the discord library internals. Instead we set up only the attributes that
    add_report actually uses.
    """
    from ui.match_report import MatchReportButton
    import asyncio

    view = object.__new__(MatchReportButton)
    view.reports = []
    view.user_reports = []
    view._lock = asyncio.Lock()

    lobby = MagicMock()
    lobby.remaining_players = set(player_ids)
    lobby.organizer_role = organizer_role
    lobby.end_reporting = AsyncMock()
    lobby.channel = AsyncMock()
    lobby.channel.send = AsyncMock()
    view.lobby = lobby

    return view


def make_user(user_id, roles=None):
    user = MagicMock()
    user.id = user_id
    user.roles = roles or []
    return user


def make_original_message():
    msg = AsyncMock()
    msg.delete = AsyncMock()
    return msg


# ─── Unanimous report ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unanimous_report_calls_end_reporting():
    """Both players reporting the same winner should call end_reporting once."""
    view = make_view()
    msg = make_original_message()

    await view.add_report(make_user(100), 200, msg)
    await view.add_report(make_user(200), 200, msg)

    view.lobby.end_reporting.assert_awaited_once_with(200)


@pytest.mark.asyncio
async def test_unanimous_report_deletes_original_message():
    view = make_view()
    msg = make_original_message()

    await view.add_report(make_user(100), 200, msg)
    await view.add_report(make_user(200), 200, msg)

    msg.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_partial_report_does_not_call_end_reporting():
    """Only one of two players has reported — should not advance yet."""
    view = make_view()
    msg = make_original_message()

    await view.add_report(make_user(100), 200, msg)

    view.lobby.end_reporting.assert_not_awaited()


# ─── Disagreement ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_disagreement_does_not_call_end_reporting():
    """Players reporting different winners should not call end_reporting."""
    view = make_view()
    msg = make_original_message()

    await view.add_report(make_user(100), 200, msg)
    await view.add_report(make_user(200), 100, msg)  # disagrees

    view.lobby.end_reporting.assert_not_awaited()


@pytest.mark.asyncio
async def test_disagreement_sends_redo_message():
    """A non-unanimous report should send an error message to the channel."""
    view = make_view()
    msg = make_original_message()

    await view.add_report(make_user(100), 200, msg)
    await view.add_report(make_user(200), 100, msg)

    view.lobby.channel.send.assert_awaited_once()
    call_args = view.lobby.channel.send.call_args[0][0]
    assert 'not unanimous' in call_args.lower() or 'Error' in call_args


@pytest.mark.asyncio
async def test_disagreement_resets_state():
    """After a redo, user_reports and reports should both be cleared."""
    view = make_view()
    msg = make_original_message()

    await view.add_report(make_user(100), 200, msg)
    await view.add_report(make_user(200), 100, msg)

    assert view.user_reports == []
    assert view.reports == []


# ─── Duplicate submission guard ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_duplicate_submission_from_same_user_is_ignored():
    """A user submitting twice should not count as two reports."""
    view = make_view()
    msg = make_original_message()

    await view.add_report(make_user(100), 200, msg)
    await view.add_report(make_user(100), 200, msg)  # duplicate

    # Only one entry should be recorded
    assert view.user_reports.count(100) == 1
    assert len(view.reports) == 1
    view.lobby.end_reporting.assert_not_awaited()


# ─── TO override ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_to_override_calls_end_reporting_immediately():
    """A TO submitting a report should bypass the normal all-players check."""
    to_role = MagicMock()
    to_role.name = 'Test TO'
    to_user = make_user(999, roles=[to_role])

    view = make_view()
    msg = make_original_message()

    # Only the TO reports — player 200 has not reported
    await view.add_report(to_user, 100, msg)

    view.lobby.end_reporting.assert_awaited_once_with(100)


@pytest.mark.asyncio
async def test_to_override_does_not_require_other_player():
    """TO override should work even if neither player has reported."""
    to_role = MagicMock()
    to_role.name = 'Test TO'
    to_user = make_user(999, roles=[to_role])

    view = make_view(player_ids=(100, 200))
    msg = make_original_message()

    await view.add_report(to_user, 200, msg)

    view.lobby.end_reporting.assert_awaited_once()


# ─── Concurrency ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_concurrent_submissions_call_end_reporting_once():
    """
    Simulate both players submitting at almost exactly the same time.
    end_reporting should still only be called once despite the concurrency.
    """
    view = make_view()
    msg = make_original_message()

    await asyncio.gather(
        view.add_report(make_user(100), 200, msg),
        view.add_report(make_user(200), 200, msg),
    )

    view.lobby.end_reporting.assert_awaited_once_with(200)


@pytest.mark.asyncio
async def test_concurrent_duplicate_submissions_ignored():
    """
    Same user firing add_report twice concurrently should result in
    exactly one entry recorded.
    """
    view = make_view()
    msg = make_original_message()

    await asyncio.gather(
        view.add_report(make_user(100), 200, msg),
        view.add_report(make_user(100), 200, msg),
    )

    assert view.user_reports.count(100) == 1