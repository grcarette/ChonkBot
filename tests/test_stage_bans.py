"""
tests/test_stage_bans.py

Tests for BanStagesButton.submit_player_bans logic.

Same philosophy as test_match_report.py — we test the pure state logic,
not the Discord UI layer. The key behaviours are:

- First player submitting does not trigger end_stage_bans
- Both players submitting triggers end_stage_bans exactly once
- Banned stages from both players are unioned correctly
- Duplicate submission from the same user is ignored
- Concurrent submissions only trigger end_stage_bans once
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock


def make_view(player_ids=(100, 200)):
    """
    Build a BanStagesButton without hitting Discord or the View registry.
    generate_embed is mocked out here — it's a Discord/DB concern tested elsewhere.
    """
    from ui.stage_bans import BanStagesButton

    view = object.__new__(BanStagesButton)
    view.player_bans = {}
    view.finished_users = []
    view._lock = asyncio.Lock()

    lobby = MagicMock()
    lobby.remaining_players = set(player_ids)
    lobby.end_stage_bans = AsyncMock()
    view.lobby = lobby

    view.message = AsyncMock()
    view.message.delete = AsyncMock()
    view.message.edit = AsyncMock()

    view.stop = MagicMock()

    # generate_embed involves Discord file I/O and DB calls — not our concern here
    view.generate_embed = AsyncMock(return_value=(MagicMock(), MagicMock()))

    return view


def make_user(user_id):
    user = MagicMock()
    user.id = user_id
    return user


# ─── Partial submission ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_first_player_does_not_trigger_end_stage_bans():
    """Only one player has submitted — should not advance yet."""
    view = make_view()

    await view.submit_player_bans(make_user(100), ['s1'])

    view.lobby.end_stage_bans.assert_not_awaited()


@pytest.mark.asyncio
async def test_first_player_submission_edits_message():
    """After the first submission the embed should update to show who still needs to ban."""
    view = make_view()

    await view.submit_player_bans(make_user(100), ['s1'])

    view.generate_embed.assert_awaited_once()
    view.message.edit.assert_awaited_once()


# ─── Both players submit ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_both_players_trigger_end_stage_bans():
    view = make_view()

    await view.submit_player_bans(make_user(100), ['s1'])
    await view.submit_player_bans(make_user(200), ['s2'])

    view.lobby.end_stage_bans.assert_awaited_once()


@pytest.mark.asyncio
async def test_banned_stages_are_union_of_both_players():
    """The combined banned stage set should include bans from both players."""
    view = make_view()

    await view.submit_player_bans(make_user(100), ['s1', 's2'])
    await view.submit_player_bans(make_user(200), ['s3'])

    call_args = view.lobby.end_stage_bans.call_args[0][0]
    assert call_args == {'s1', 's2', 's3'}


@pytest.mark.asyncio
async def test_overlapping_bans_deduped():
    """If both players ban the same stage it should only appear once."""
    view = make_view()

    await view.submit_player_bans(make_user(100), ['s1'])
    await view.submit_player_bans(make_user(200), ['s1'])

    call_args = view.lobby.end_stage_bans.call_args[0][0]
    assert call_args == {'s1'}


@pytest.mark.asyncio
async def test_completion_deletes_message():
    view = make_view()

    await view.submit_player_bans(make_user(100), ['s1'])
    await view.submit_player_bans(make_user(200), ['s2'])

    view.message.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_completion_calls_stop():
    view = make_view()

    await view.submit_player_bans(make_user(100), ['s1'])
    await view.submit_player_bans(make_user(200), ['s2'])

    view.stop.assert_called_once()


@pytest.mark.asyncio
async def test_edit_only_called_for_partial_submissions():
    """
    message.edit should be called once (after the first/partial submission)
    but not on the final submission — delete handles that instead.
    With 2 players: 1 partial submission → 1 edit, 1 completion → delete.
    """
    view = make_view()

    await view.submit_player_bans(make_user(100), ['s1'])
    await view.submit_player_bans(make_user(200), ['s2'])

    assert view.message.edit.await_count == 1
    view.message.delete.assert_awaited_once()


# ─── Duplicate submission guard ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_duplicate_submission_from_same_user_ignored():
    """A player submitting twice should not count as two submissions."""
    view = make_view()

    await view.submit_player_bans(make_user(100), ['s1'])
    await view.submit_player_bans(make_user(100), ['s1'])  # duplicate

    assert view.finished_users.count(100) == 1
    view.lobby.end_stage_bans.assert_not_awaited()


@pytest.mark.asyncio
async def test_duplicate_does_not_overwrite_original_bans():
    """A duplicate submission with different stages should not replace the original."""
    view = make_view()
    user = make_user(100)

    await view.submit_player_bans(user, ['s1'])
    await view.submit_player_bans(user, ['s2', 's3'])  # duplicate with different stages

    assert len(view.player_bans) == 1


# ─── Concurrency ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_concurrent_submissions_trigger_end_stage_bans_once():
    """Both players submitting concurrently should only call end_stage_bans once."""
    view = make_view()

    await asyncio.gather(
        view.submit_player_bans(make_user(100), ['s1']),
        view.submit_player_bans(make_user(200), ['s2']),
    )

    view.lobby.end_stage_bans.assert_awaited_once()


@pytest.mark.asyncio
async def test_concurrent_duplicates_from_same_user_ignored():
    """Same user firing submit_player_bans concurrently still only counts once."""
    view = make_view()

    await asyncio.gather(
        view.submit_player_bans(make_user(100), ['s1']),
        view.submit_player_bans(make_user(100), ['s1']),
    )

    assert view.finished_users.count(100) == 1
    view.lobby.end_stage_bans.assert_not_awaited()