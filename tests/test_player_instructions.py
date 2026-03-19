"""
tests/test_player_instructions.py

Tests for MatchLobby.send_player_instructions.

These tests mock out Discord and the DB entirely — the logic under test
is purely which message the loser receives based on bracket + format.
We test by inspecting the embed sent to the channel.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def make_lobby(bracket, is_swiss=False, results=None):
    """
    Build a minimal MatchLobby-like object without hitting Discord or the DB.
    We bypass MatchLobby.create entirely and construct the object directly.
    """
    from tournaments.match_lobby import MatchLobby

    lobby = object.__new__(MatchLobby)
    lobby.bracket = bracket
    lobby.match_id = 1
    lobby.lobby_name = "test-lobby"
    lobby.players = [100, 200]
    lobby.remaining_players = {100, 200}
    lobby.stages = []
    lobby.num_winners = 1
    lobby.guild = MagicMock()

    # Mock tournament manager
    tm = MagicMock()
    tm.is_swiss = is_swiss
    lobby.tournament_manager = tm

    # Mock channel — capture what gets sent
    lobby.channel = AsyncMock()

    # Mock dh — return a fake lobby document with results
    lobby.dh = AsyncMock()
    lobby.dh.get_tournament_by_id = AsyncMock(return_value={
        'name': 'Test Tournament',
        '_id': 'fake-id',
    })
    lobby.dh.get_lobby = AsyncMock(return_value={
        'results': results or [100, 200],
    })

    lobby.tournament = {'name': 'Test Tournament', '_id': 'fake-id'}
    lobby.organizer_role = 'Test Tournament TO'

    return lobby


async def get_sent_embed(lobby):
    """Run send_player_instructions and return the embed that was sent."""
    await lobby.send_player_instructions()
    assert lobby.channel.send.called, "channel.send was never called"
    call_kwargs = lobby.channel.send.call_args
    embed = call_kwargs.kwargs.get('embed') or call_kwargs.args[0]
    return embed


# ─── Double elimination ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_de_winners_bracket_loser_gets_dropped_to_losers_message():
    lobby = make_lobby(bracket='Winners', is_swiss=False)
    embed = await get_sent_embed(lobby)
    assert "not out of the tournament" in embed.description
    assert "losers" in embed.description.lower()


@pytest.mark.asyncio
async def test_de_winners_bracket_winner_gets_next_match_message():
    lobby = make_lobby(bracket='Winners', is_swiss=False)
    embed = await get_sent_embed(lobby)
    assert "pinged when your next match is ready" in embed.description


@pytest.mark.asyncio
async def test_de_losers_bracket_loser_gets_eliminated_message():
    lobby = make_lobby(bracket='Losers', is_swiss=False)
    embed = await get_sent_embed(lobby)
    assert "eliminated" in embed.description.lower()


@pytest.mark.asyncio
async def test_de_losers_bracket_does_not_say_dropped_to_losers():
    """
    A player losing in losers bracket is OUT — they should not be told
    they're dropping to losers bracket again.
    """
    lobby = make_lobby(bracket='Losers', is_swiss=False)
    embed = await get_sent_embed(lobby)
    assert "not out of the tournament" not in embed.description


# ─── Single elimination ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_se_loser_gets_eliminated_message():
    lobby = make_lobby(bracket='', is_swiss=False)
    embed = await get_sent_embed(lobby)
    assert "eliminated" in embed.description.lower()


@pytest.mark.asyncio
async def test_se_loser_does_not_get_losers_bracket_message():
    """SE has no losers bracket — the loser should never be told to wait for losers."""
    lobby = make_lobby(bracket='', is_swiss=False)
    embed = await get_sent_embed(lobby)
    assert "not out of the tournament" not in embed.description
    assert "losers bracket" not in embed.description.lower()


# ─── Swiss ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_swiss_loser_gets_next_round_message():
    lobby = make_lobby(bracket=None, is_swiss=True)
    embed = await get_sent_embed(lobby)
    # Swiss losers are NOT eliminated — they play again next round
    assert "next round" in embed.description.lower() or "next match" in embed.description.lower()


@pytest.mark.asyncio
async def test_swiss_loser_does_not_get_eliminated_message():
    """Losing a Swiss match does not eliminate you."""
    lobby = make_lobby(bracket=None, is_swiss=True)
    embed = await get_sent_embed(lobby)
    assert "eliminated" not in embed.description.lower()


@pytest.mark.asyncio
async def test_swiss_loser_does_not_get_losers_bracket_message():
    lobby = make_lobby(bracket=None, is_swiss=True)
    embed = await get_sent_embed(lobby)
    assert "not out of the tournament" not in embed.description
    assert "losers bracket" not in embed.description.lower()


# ─── No channel (lobby already closed) ───────────────────────────────────────

@pytest.mark.asyncio
async def test_no_channel_returns_silently():
    """If the channel is gone, send_player_instructions should do nothing."""
    lobby = make_lobby(bracket='Winners', is_swiss=False)
    lobby.channel = None
    await lobby.send_player_instructions()  # should not raise