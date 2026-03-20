"""
tests/test_remove_tournament.py

Regression tests for remove_tournament_from_discord.

Covers:
- Does not crash when get_tournament_category() returns None (the bug that was filed)
- Channels that raise NotFound (already deleted) are skipped, not crashed on
- All channels in the category are deleted when category exists
- Roles are deleted when they exist
- Roles are skipped gracefully when they don't exist
"""

import pytest
import discord
from unittest.mock import AsyncMock, MagicMock, patch


def make_tm(category=None, roles=None):
    """
    Build a minimal TournamentManager for remove_tournament_from_discord tests.
    category: the mock category returned by get_tournament_category(), or None.
    roles: dict of role name -> mock role (or None to omit)
    """
    from tournaments.tournament_manager import TournamentManager

    tournament = {
        '_id': 'tid',
        'name': 'Test Tournament',
        'format': 'double elimination',
        'state': 'finished',
    }

    tm = object.__new__(TournamentManager)
    tm.tournament = tournament
    tm.debug = False

    tm.bot = MagicMock()
    tm.bot.guild = MagicMock()
    tm.guild = tm.bot.guild

    tm.get_tournament = AsyncMock(return_value=tournament)
    tm.get_tournament_category = MagicMock(return_value=category)

    # Wire up discord.utils.get to return roles by name
    roles = roles or {}
    def fake_get(collection, name=None, **kwargs):
        if name:
            return roles.get(name)
        return None

    tm._fake_roles = roles
    tm._discord_get_patch = fake_get

    return tm


def make_channel(name='lobby-channel'):
    ch = AsyncMock()
    ch.name = name
    ch.delete = AsyncMock()
    return ch


def make_category(channels=None):
    cat = AsyncMock()
    cat.channels = channels or []
    cat.delete = AsyncMock()
    return cat


def make_role(name):
    role = AsyncMock()
    role.name = name
    role.delete = AsyncMock()
    return role


# ─── None category guard ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_crash_when_category_is_none():
    """
    Regression test for: AttributeError: 'NoneType' object has no attribute 'channels'
    This is the exact crash that was reported.
    """
    tm = make_tm(category=None)

    with patch('discord.utils.get', return_value=None):
        # Should complete without raising
        await tm.remove_tournament_from_discord()


@pytest.mark.asyncio
async def test_no_channels_deleted_when_category_is_none():
    """If there's no category, nothing Discord-related should be attempted."""
    tm = make_tm(category=None)
    channel = make_channel()

    with patch('discord.utils.get', return_value=None):
        await tm.remove_tournament_from_discord()

    channel.delete.assert_not_awaited()


# ─── NotFound handling ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_not_found_on_channel_delete_does_not_crash():
    """
    A channel that was already deleted (e.g. lobby channel from end_tournament)
    should be skipped, not crash the whole cleanup.
    """
    channel = make_channel()
    channel.delete.side_effect = discord.NotFound(MagicMock(), 'Unknown Channel')

    category = make_category(channels=[channel])
    tm = make_tm(category=category)

    with patch('discord.utils.get', return_value=None):
        await tm.remove_tournament_from_discord()

    # delete was called but the NotFound was swallowed
    channel.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_remaining_channels_deleted_after_not_found():
    """
    If one channel raises NotFound, the remaining channels should still be deleted.
    """
    channel_1 = make_channel('lobby-1')
    channel_1.delete.side_effect = discord.NotFound(MagicMock(), 'Unknown Channel')
    channel_2 = make_channel('lobby-2')

    category = make_category(channels=[channel_1, channel_2])
    tm = make_tm(category=category)

    with patch('discord.utils.get', return_value=None):
        await tm.remove_tournament_from_discord()

    channel_2.delete.assert_awaited_once()


# ─── Normal deletion ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_all_channels_deleted_when_category_exists():
    channels = [make_channel(f'channel-{i}') for i in range(3)]
    category = make_category(channels=channels)
    tm = make_tm(category=category)

    with patch('discord.utils.get', return_value=None):
        await tm.remove_tournament_from_discord()

    for ch in channels:
        ch.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_category_itself_is_deleted():
    category = make_category()
    tm = make_tm(category=category)

    with patch('discord.utils.get', return_value=None):
        await tm.remove_tournament_from_discord()

    category.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_roles_deleted_when_they_exist():
    tournament_role = make_role('Test Tournament')
    to_role = make_role('Test Tournament TO')

    category = make_category()
    tm = make_tm(category=category)

    def fake_get(collection, name=None, **kwargs):
        return {'Test Tournament': tournament_role, 'Test Tournament TO': to_role}.get(name)

    with patch('discord.utils.get', side_effect=fake_get):
        await tm.remove_tournament_from_discord()

    tournament_role.delete.assert_awaited_once()
    to_role.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_crash_when_roles_do_not_exist():
    """discord.utils.get returning None for roles should not crash."""
    category = make_category()
    tm = make_tm(category=category)

    with patch('discord.utils.get', return_value=None):
        await tm.remove_tournament_from_discord()