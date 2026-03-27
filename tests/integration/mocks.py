# tests/integration/mocks.py
"""
Mock Discord and external API objects for integration testing.

These stubs replace the real Discord guild, channels, and UCH Ranked API
so scenarios can run without a live Discord connection. Everything else
— TournamentManager, SwissFormat, MongoDB — is real.
"""

from unittest.mock import AsyncMock, MagicMock
import asyncio


# ── Mock Discord member ───────────────────────────────────────────────────────

def make_mock_member(user_id: int, name: str = None) -> MagicMock:
    """A Discord member stub with a real id and display name."""
    member = MagicMock()
    member.id            = user_id
    member.name          = name or f'debug_user_{user_id}'
    member.display_name  = name or f'debug_user_{user_id}'
    member.mention       = f'<@{user_id}>'
    member.display_avatar = MagicMock()
    member.display_avatar.url = f'https://cdn.discordapp.com/avatars/{user_id}/fake.png'
    member.add_roles     = AsyncMock()
    member.remove_roles  = AsyncMock()
    member.send          = AsyncMock()
    member.roles         = []
    return member


# ── Mock Discord role ─────────────────────────────────────────────────────────

def make_mock_role(name: str) -> MagicMock:
    role         = MagicMock()
    role.name    = name
    role.mention = f'@{name}'
    role.delete  = AsyncMock()
    return role


# ── Mock Discord channel ──────────────────────────────────────────────────────

def make_mock_channel(name: str) -> MagicMock:
    channel              = MagicMock()
    channel.name         = name
    channel.id           = hash(name) % (10 ** 10)
    channel.mention      = f'#{name}'
    channel.send         = AsyncMock(return_value=MagicMock(id=1, components=[]))
    channel.purge        = AsyncMock()
    channel.delete       = AsyncMock()
    channel.edit         = AsyncMock()
    channel.set_permissions = AsyncMock()
    channel.history      = _mock_history
    channel.overwrites_for = MagicMock(return_value=MagicMock(
        view_channel=True,
        send_messages=True,
    ))
    return channel


def _mock_history(limit=None, oldest_first=False):
    """Async generator that yields nothing — empty channel history."""
    async def _gen():
        return
        yield  # make it an async generator
    return _gen()


# ── Mock Discord category ─────────────────────────────────────────────────────

class MockCategory:
    """
    Simulates a Discord category that holds channels.
    Channels are created on demand and stored by name.
    """

    def __init__(self, name: str, category_id: int):
        self.name     = name
        self.id       = category_id
        self._channels: dict[str, MagicMock] = {}

    @property
    def channels(self) -> list:
        return list(self._channels.values())

    @property
    def text_channels(self) -> list:
        return list(self._channels.values())

    def get_channel(self, name: str) -> MagicMock | None:
        return self._channels.get(name)

    async def create_text_channel(self, name: str, **kwargs) -> MagicMock:
        ch = make_mock_channel(name)
        self._channels[name] = ch
        return ch

    async def delete(self):
        self._channels.clear()


# ── Mock Discord guild ────────────────────────────────────────────────────────

class MockGuild:
    """
    Simulates a Discord guild for testing.

    Maintains a registry of members and roles so that discord.utils.get()
    calls work correctly. Creates MockCategory instances on demand.
    """

    def __init__(self, player_ids: list[int]):
        self.id              = 999999999
        self.name            = 'Test Server'
        self.default_role    = make_mock_role('@everyone')
        self._members        = {uid: make_mock_member(uid) for uid in player_ids}
        self._roles: dict[str, MagicMock] = {'@everyone': self.default_role}
        self._categories: dict[int, MockCategory] = {}
        self._next_category_id = 100000

    @property
    def members(self) -> list:
        return list(self._members.values())

    @property
    def roles(self) -> list:
        return list(self._roles.values())

    @property
    def categories(self) -> list:
        return list(self._categories.values())

    def get_member(self, user_id: int) -> MagicMock | None:
        return self._members.get(user_id)

    def get_channel(self, channel_id: int) -> MagicMock | None:
        for cat in self._categories.values():
            for ch in cat.channels:
                if ch.id == channel_id:
                    return ch
        return None

    async def create_role(self, name: str, **kwargs) -> MagicMock:
        role = make_mock_role(name)
        self._roles[name] = role
        return role

    async def create_category(self, name: str, **kwargs) -> MockCategory:
        cat_id = self._next_category_id
        self._next_category_id += 1
        cat = MockCategory(name, cat_id)
        self._categories[cat_id] = cat
        return cat

    async def create_text_channel(self, name: str, category=None, **kwargs) -> MagicMock:
        if category and isinstance(category, MockCategory):
            return await category.create_text_channel(name, **kwargs)
        ch = make_mock_channel(name)
        return ch

    async def edit_channel_positions(self, *args, **kwargs):
        pass


# ── Mock UCH Ranked API ───────────────────────────────────────────────────────

class MockRankedAPI:
    """
    Simulates the UCH Ranked API.

    By default every report succeeds. Configure fail_next to make the
    next call fail, or always_fail to make all calls fail.
    """

    def __init__(self):
        self.reports: list[dict]  = []  # record of every report made
        self.fail_next: bool      = False
        self.always_fail: bool    = False
        self._next_match_id       = 5000

    def _should_fail(self) -> bool:
        if self.always_fail:
            return True
        if self.fail_next:
            self.fail_next = False
            return True
        return False

    async def get_player(self, discord_id: int) -> dict | None:
        return {
            'found':    True,
            'username': f'player_{discord_id}',
            'elo':      1200,
            'rank':     'Bronze',
            'division': 0,
        }

    async def report_match(
        self,
        player1_id: int,
        player2_id: int,
        score: str,
        vod: str = '',
    ) -> dict:
        if self._should_fail():
            return {'success': False, 'error': 'Mock API failure'}

        match_id = self._next_match_id
        self._next_match_id += 1
        self.reports.append({
            'player1_id': player1_id,
            'player2_id': player2_id,
            'match_id':   match_id,
        })
        return {'success': True, 'match_id': match_id}

    async def accept_match(self, discord_id: int, match_id: int) -> dict:
        return {'success': True}

    async def reject_match(self, discord_id: int, match_id: int) -> dict:
        return {'success': True}

    async def accept_all(self, discord_id: int) -> dict:
        return {'success': True}

    async def get_matches(self, discord_id: int) -> list:
        return []

    async def get_leaderboard(self, n: int) -> list:
        return []

    async def get_winstreak_leaderboard(self, n: int) -> list:
        return []

    async def get_winrate(self, discord_id: int) -> dict | None:
        return None

    async def get_recent_games(self, n: int) -> list:
        return []
