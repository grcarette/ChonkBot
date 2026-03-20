"""
tests/test_unregister_player.py

Tests for TournamentManager.unregister_player.

Verifies:
- Swiss players are dropped from the swiss event, never from Challonge
- DE players are unregistered from Challonge using their stored player_id
- A None player_id (stale data) never reaches the Challonge API
- A user not in entrants returns early without crashing
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def make_tm(format='double elimination', entrants=None, player_id=42):
    """Build a minimal TournamentManager without touching Discord or the DB."""
    from tournaments.tournament_manager import TournamentManager

    bot = MagicMock()
    bot.guild = MagicMock()
    bot.guild.members = []

    tournament = {
        '_id': 'tid',
        'name': 'Test Tournament',
        'format': format,
        'entrants': entrants or {'999': player_id},
        'state': 'active',
    }

    tm = object.__new__(TournamentManager)
    tm.bot = bot
    tm.tournament = tournament
    tm.guild = bot.guild
    tm.swiss_manager = AsyncMock()
    tm.ch = AsyncMock()
    tm.debug = False

    # dh mocks
    tm.bot.dh = AsyncMock()
    tm.bot.dh.get_tournament_by_id = AsyncMock(return_value=tournament)
    tm.bot.dh.unregister_player = AsyncMock()
    tm.bot.dh.swiss_drop_player = AsyncMock()
    tm.bot.dh.get_swiss_event_by_tournament = AsyncMock(return_value={
        '_id': 'swiss-eid',
        'players': {'999': {'active_match_id': None}},
    })
    tm.bot.dh.get_registration_status = AsyncMock(return_value=True)

    tm.format = MagicMock()
    tm.format.on_player_unregister = AsyncMock()

    return tm


# ─── Helper to call unregister_player without Discord role side-effects ───────

async def unregister(tm, user_id=999):
    """
    Patch discord.utils.get so role removal is a no-op,
    then call unregister_player.
    """
    with patch('tournaments.tournament_manager.discord.utils.get', return_value=None):
        await tm.unregister_player(user_id)


# ─── Swiss ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_swiss_drops_from_swiss_event():
    tm = make_tm(format='swiss', entrants={'999': None})
    await unregister(tm)
    tm.format.on_player_unregister.assert_awaited_once_with(999)


@pytest.mark.asyncio
async def test_swiss_never_calls_challonge_unregister():
    tm = make_tm(format='swiss', entrants={'999': None})
    await unregister(tm)
    tm.ch.unregister_player.assert_not_awaited()


@pytest.mark.asyncio
async def test_swiss_calls_dh_unregister_player():
    tm = make_tm(format='swiss', entrants={'999': None})
    await unregister(tm)
    tm.bot.dh.unregister_player.assert_awaited_once()


# ─── Double elimination ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_de_calls_challonge_unregister_with_correct_player_id():
    tm = make_tm(format='double elimination', entrants={'999': 42})
    tm.tournament['challonge_data'] = {'id': 'chid'}
    tm.bot.dh.get_tournament_by_id = AsyncMock(return_value={
        **tm.tournament,
        'challonge_data': {'id': 'chid'},
    })

    await unregister(tm)
    tm.format.on_player_unregister.assert_awaited_once_with(999)


@pytest.mark.asyncio
async def test_de_does_not_call_swiss_drop():
    tm = make_tm(format='double elimination', entrants={'999': 42})
    tm.tournament['challonge_data'] = {'id': 'chid'}
    tm.bot.dh.get_tournament_by_id = AsyncMock(return_value={
        **tm.tournament,
        'challonge_data': {'id': 'chid'},
    })
    await unregister(tm)
    tm.bot.dh.swiss_drop_player.assert_not_awaited()


# ─── None player_id guard ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_none_player_id_does_not_call_challonge():
    """
    If a player somehow has None as their Challonge ID,
    we must not pass that to the API.
    """
    tm = make_tm(format='double elimination', entrants={'999': None})
    tm.tournament['challonge_data'] = {'id': 'chid'}
    tm.bot.dh.get_tournament_by_id = AsyncMock(return_value={
        **tm.tournament,
        'challonge_data': {'id': 'chid'},
    })
    await unregister(tm)
    tm.ch.unregister_player.assert_not_awaited()


# ─── User not in entrants ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unregister_unknown_user_returns_early():
    """A user not in entrants should cause an early return with no side-effects."""
    tm = make_tm(format='double elimination', entrants={'999': 42})
    await unregister(tm, user_id=12345)  # not in entrants
    tm.ch.unregister_player.assert_not_awaited()
    tm.bot.dh.unregister_player.assert_not_awaited()