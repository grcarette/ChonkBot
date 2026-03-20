"""
tests/test_checkin_reminder.py

Tests for the match checkin reminder system.

Two areas covered:

1. LobbyMethodsMixin.get_stale_checkin_lobbies
   - Correct query shape (state, tournament, timestamp cutoff)
   - Returns what the collection returns

2. TournamentManager._send_checkin_reminders
   - DMs players who haven't checked in and are past the threshold
   - Skips players who have already checked in
   - Deduplication: doesn't DM the same player twice across loop iterations
   - Forbidden is swallowed and the player is still marked as reminded
   - Players not found in guild are skipped
   - Does nothing in debug mode
   - stop_checkin_reminder_loop cancels the task cleanly
"""

import asyncio
import pytest
import discord
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, call
from bson import ObjectId


# ─── get_stale_checkin_lobbies ────────────────────────────────────────────────

# Valid 24-character hex ObjectId strings for use in DB tests
FAKE_TOURNAMENT_ID = '6' * 24   # '666666666666666666666666'
FAKE_TOURNAMENT_ID_2 = '7' * 24


@pytest.mark.asyncio
async def test_get_stale_checkin_lobbies_queries_correct_state():
    """Only lobbies in 'checkin' state should be returned."""
    from data.lobby import LobbyMethodsMixin

    dh = LobbyMethodsMixin.__new__(LobbyMethodsMixin)
    dh.lobby_collection = AsyncMock()

    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=[])
    dh.lobby_collection.find = MagicMock(return_value=mock_cursor)

    await dh.get_stale_checkin_lobbies(FAKE_TOURNAMENT_ID, threshold_seconds=300)

    query = dh.lobby_collection.find.call_args[0][0]
    assert query['state'] == 'checkin'


@pytest.mark.asyncio
async def test_get_stale_checkin_lobbies_uses_correct_tournament_id():
    from data.lobby import LobbyMethodsMixin

    dh = LobbyMethodsMixin.__new__(LobbyMethodsMixin)
    dh.lobby_collection = AsyncMock()

    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=[])
    dh.lobby_collection.find = MagicMock(return_value=mock_cursor)

    await dh.get_stale_checkin_lobbies(FAKE_TOURNAMENT_ID_2, threshold_seconds=300)

    query = dh.lobby_collection.find.call_args[0][0]
    assert query['tournament'] == ObjectId(FAKE_TOURNAMENT_ID_2)


@pytest.mark.asyncio
async def test_get_stale_checkin_lobbies_cutoff_is_in_the_past():
    """The timestamp cutoff should be before now by at least threshold_seconds."""
    from data.lobby import LobbyMethodsMixin

    dh = LobbyMethodsMixin.__new__(LobbyMethodsMixin)
    dh.lobby_collection = AsyncMock()

    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=[])
    dh.lobby_collection.find = MagicMock(return_value=mock_cursor)

    before = datetime.now()
    await dh.get_stale_checkin_lobbies(FAKE_TOURNAMENT_ID, threshold_seconds=300)
    after = datetime.now()

    query = dh.lobby_collection.find.call_args[0][0]
    cutoff = query['state_timestamp']['$lt']

    # cutoff should be ~300s before now
    assert cutoff < before
    assert cutoff > after - timedelta(seconds=310)  # small tolerance


@pytest.mark.asyncio
async def test_get_stale_checkin_lobbies_returns_collection_results():
    from data.lobby import LobbyMethodsMixin

    dh = LobbyMethodsMixin.__new__(LobbyMethodsMixin)
    dh.lobby_collection = AsyncMock()

    fake_lobbies = [{'match_id': 1}, {'match_id': 2}]
    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=fake_lobbies)
    dh.lobby_collection.find = MagicMock(return_value=mock_cursor)

    result = await dh.get_stale_checkin_lobbies(FAKE_TOURNAMENT_ID, threshold_seconds=300)
    assert result == fake_lobbies


# ─── _send_checkin_reminders ──────────────────────────────────────────────────

def make_tm(debug=False):
    """Build a minimal TournamentManager for reminder tests."""
    from tournaments.tournament_manager import TournamentManager

    tournament = {
        '_id': 'tid',
        'name': 'Test Tournament',
        'debug': debug,
    }

    tm = object.__new__(TournamentManager)
    tm.tournament = tournament
    tm.debug = debug
    tm._checkin_reminded = set()

    tm.bot = MagicMock()
    tm.bot.dh = AsyncMock()
    tm.guild = MagicMock()

    return tm


def make_lobby_doc(match_id, players, checked_in=None, channel_id=999):
    return {
        'match_id': match_id,
        'players': players,
        'checked_in': checked_in or [],
        'channel_id': channel_id,
        # Default to 5 minutes stale — within reminder window, below auto-DQ threshold
        'state_timestamp': datetime.now() - timedelta(seconds=300),
    }


def make_member(user_id):
    member = AsyncMock()
    member.id = user_id
    member.send = AsyncMock()
    return member


@pytest.mark.asyncio
async def test_dm_sent_to_player_who_has_not_checked_in():
    tm = make_tm()
    member = make_member(100)

    tm.bot.dh.get_stale_checkin_lobbies = AsyncMock(return_value=[
        make_lobby_doc(match_id=10, players=[100, 200], checked_in=[200])
    ])

    def fake_get(collection, id=None, **kwargs):
        if id == 100:
            return member
        return None

    with patch('discord.utils.get', side_effect=fake_get):
        await tm._send_checkin_reminders()

    member.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_dm_sent_to_player_who_has_checked_in():
    tm = make_tm()
    member_100 = make_member(100)
    member_200 = make_member(200)

    tm.bot.dh.get_stale_checkin_lobbies = AsyncMock(return_value=[
        make_lobby_doc(match_id=10, players=[100, 200], checked_in=[100, 200])
    ])

    with patch('discord.utils.get', return_value=None):
        await tm._send_checkin_reminders()

    member_100.send.assert_not_awaited()
    member_200.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_dm_not_sent_twice_to_same_player():
    """Calling _send_checkin_reminders twice should only DM each player once."""
    tm = make_tm()
    member = make_member(100)

    tm.bot.dh.get_stale_checkin_lobbies = AsyncMock(return_value=[
        make_lobby_doc(match_id=10, players=[100, 200], checked_in=[200])
    ])

    def fake_get(collection, id=None, **kwargs):
        if id == 100:
            return member
        return None

    with patch('discord.utils.get', side_effect=fake_get):
        await tm._send_checkin_reminders()
        await tm._send_checkin_reminders()  # second call — should be no-op for player 100

    assert member.send.await_count == 1


@pytest.mark.asyncio
async def test_forbidden_swallowed_and_player_marked_as_reminded():
    """A player with DMs off should be marked as reminded so we don't retry."""
    tm = make_tm()
    member = make_member(100)
    member.send.side_effect = discord.Forbidden(MagicMock(status=403), 'Cannot send messages to this user')

    tm.bot.dh.get_stale_checkin_lobbies = AsyncMock(return_value=[
        make_lobby_doc(match_id=10, players=[100, 200], checked_in=[200])
    ])

    def fake_get(collection, id=None, **kwargs):
        if id == 100:
            return member
        return None

    with patch('discord.utils.get', side_effect=fake_get):
        # Should not raise
        await tm._send_checkin_reminders()

    # Player should be marked so we don't retry next loop
    assert (10, 100) in tm._checkin_reminded


@pytest.mark.asyncio
async def test_forbidden_does_not_retry_on_next_loop():
    """Even after Forbidden, the player should not be DM'd again on the next iteration."""
    tm = make_tm()
    member = make_member(100)
    member.send.side_effect = discord.Forbidden(MagicMock(status=403), 'Cannot send messages to this user')

    tm.bot.dh.get_stale_checkin_lobbies = AsyncMock(return_value=[
        make_lobby_doc(match_id=10, players=[100, 200], checked_in=[200])
    ])

    def fake_get(collection, id=None, **kwargs):
        if id == 100:
            return member
        return None

    with patch('discord.utils.get', side_effect=fake_get):
        await tm._send_checkin_reminders()
        member.send.side_effect = None  # DMs now work — but we shouldn't retry
        await tm._send_checkin_reminders()

    assert member.send.await_count == 1


@pytest.mark.asyncio
async def test_player_not_in_guild_is_skipped():
    """If discord.utils.get returns None for a member, no DM is attempted."""
    tm = make_tm()

    tm.bot.dh.get_stale_checkin_lobbies = AsyncMock(return_value=[
        make_lobby_doc(match_id=10, players=[100, 200], checked_in=[200])
    ])

    with patch('discord.utils.get', return_value=None):
        await tm._send_checkin_reminders()  # should not raise


@pytest.mark.asyncio
async def test_no_reminders_sent_in_debug_mode():
    """Debug mode should skip all DMs entirely."""
    tm = make_tm(debug=True)
    member = make_member(100)

    tm.bot.dh.get_stale_checkin_lobbies = AsyncMock(return_value=[
        make_lobby_doc(match_id=10, players=[100, 200], checked_in=[])
    ])

    with patch('discord.utils.get', return_value=member):
        await tm._send_checkin_reminders()

    member.send.assert_not_awaited()
    # DB should not even be queried in debug mode
    tm.bot.dh.get_stale_checkin_lobbies.assert_not_awaited()


@pytest.mark.asyncio
async def test_multiple_lobbies_each_player_reminded_independently():
    """Players across different lobbies each get their own reminder."""
    tm = make_tm()
    member_a = make_member(100)
    member_b = make_member(300)

    tm.bot.dh.get_stale_checkin_lobbies = AsyncMock(return_value=[
        make_lobby_doc(match_id=10, players=[100, 200], checked_in=[200]),
        make_lobby_doc(match_id=11, players=[300, 400], checked_in=[400]),
    ])

    def fake_get(collection, id=None, **kwargs):
        return {100: member_a, 300: member_b}.get(id)

    with patch('discord.utils.get', side_effect=fake_get):
        await tm._send_checkin_reminders()

    member_a.send.assert_awaited_once()
    member_b.send.assert_awaited_once()


# ─── stop_checkin_reminder_loop ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stop_cancels_running_task():
    tm = make_tm()
    tm._checkin_reminded = set()

    # Create a real task that just sleeps forever
    tm._checkin_reminder_task = asyncio.create_task(asyncio.sleep(9999))

    tm.stop_checkin_reminder_loop()

    # Give the event loop a tick to process the cancellation
    await asyncio.sleep(0)

    assert tm._checkin_reminder_task.cancelled()


@pytest.mark.asyncio
async def test_stop_clears_reminded_set():
    tm = make_tm()
    tm._checkin_reminded = {(10, 100), (11, 200)}
    tm._checkin_reminder_task = asyncio.create_task(asyncio.sleep(9999))

    tm.stop_checkin_reminder_loop()
    await asyncio.sleep(0)

    assert tm._checkin_reminded == set()


@pytest.mark.asyncio
async def test_stop_does_not_crash_when_no_task_exists():
    """stop_checkin_reminder_loop should be safe to call even if the loop was never started."""
    tm = make_tm()
    tm._checkin_reminded = set()
    # No _checkin_reminder_task attribute set

    tm.stop_checkin_reminder_loop()  # should not raise