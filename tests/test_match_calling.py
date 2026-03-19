"""
tests/test_match_calling.py

Tests for TournamentManager.get_lobby_name and add_match_call.

Verifies:
- Winners bracket matches produce 'w'-prefixed lobby names
- Losers bracket matches produce 'l'-prefixed lobby names
- Single elimination matches produce 's'-prefixed lobby names (not 'l')
- add_match_call embed title and color are correct per bracket
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import discord


def make_match_data(bracket, round_number=1, player_1=1, player_2=2):
    return {
        'match_id': 10,
        'bracket': bracket,
        'round': round_number,
        'player_1': player_1,
        'player_2': player_2,
        'prereq_matches': [],
    }


def make_tm(format='double elimination'):
    from tournaments.tournament_manager import TournamentManager

    tournament = {
        '_id': 'tid',
        'name': 'Test',
        'format': format,
        'challonge_data': {'url': 'test-url', 'id': 'chid'},
        'stagelist': [],
    }

    tm = object.__new__(TournamentManager)
    tm.tournament = tournament
    tm.lobbies = {}
    tm.match_calls = {}
    tm.ch = AsyncMock()
    tm.guild = MagicMock()
    tm.bot = MagicMock()
    tm.bot.dh = AsyncMock()
    tm.bot.dh.get_tournament_by_id = AsyncMock(return_value=tournament)
    tm.bot.dh.get_lobby_time = AsyncMock(return_value=None)
    tm.debug = False
    tm.tournament_reset = False
    tm.autocall_matches = False
    tm.organizer_role = None

    async def fake_get_players(match_data):
        p1 = {'user_id': match_data['player_1'], 'name': f"Player{match_data['player_1']}"}
        p2 = {'user_id': match_data['player_2'], 'name': f"Player{match_data['player_2']}"}
        return p1, p2

    tm.get_players_from_match = fake_get_players
    tm.get_short_timestamp = lambda ts: "12:00"
    tm.get_tournament_category = MagicMock(return_value=MagicMock())

    return tm


# ─── get_lobby_name ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_winners_bracket_lobby_name_starts_with_w():
    tm = make_tm()
    name = await tm.get_lobby_name(make_match_data('Winners'))
    assert name.startswith('w'), f"Expected 'w' prefix, got: {name}"


@pytest.mark.asyncio
async def test_losers_bracket_lobby_name_starts_with_l():
    tm = make_tm()
    name = await tm.get_lobby_name(make_match_data('Losers'))
    assert name.startswith('l'), f"Expected 'l' prefix, got: {name}"


@pytest.mark.asyncio
async def test_single_elim_lobby_name_starts_with_s_not_l():
    """
    Before the fix, SE lobbies were tagged 'l', causing the loser to receive
    an 'eliminated from losers bracket' message. Should be 's'.
    """
    tm = make_tm(format='single elimination')
    name = await tm.get_lobby_name(make_match_data(''))
    assert name.startswith('s'), f"Expected 's' prefix, got: {name}"
    assert not name.startswith('l'), "SE lobby must NOT start with 'l'"


# ─── add_match_call embed ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_winners_bracket_call_is_green():
    tm = make_tm()
    sent_embed = None

    async def capture_send(embed, view):
        nonlocal sent_embed
        sent_embed = embed
        msg = AsyncMock()
        return msg

    mock_channel = AsyncMock()
    mock_channel.send = capture_send

    with patch('discord.utils.get', return_value=mock_channel):
        await tm.add_match_call(make_match_data('Winners'))

    assert sent_embed is not None
    assert sent_embed.color == discord.Color.green()


@pytest.mark.asyncio
async def test_losers_bracket_call_is_red():
    tm = make_tm()
    sent_embed = None

    async def capture_send(embed, view):
        nonlocal sent_embed
        sent_embed = embed
        return AsyncMock()

    mock_channel = AsyncMock()
    mock_channel.send = capture_send

    with patch('discord.utils.get', return_value=mock_channel):
        await tm.add_match_call(make_match_data('Losers'))

    assert sent_embed.color == discord.Color.red()


@pytest.mark.asyncio
async def test_single_elim_call_is_not_red_and_has_no_bracket_prefix():
    """
    Before the fix, SE embeds got a leading space in the title and red color.
    Now they should have a clean title and a distinct (blue) color.
    """
    tm = make_tm(format='single elimination')
    sent_embed = None

    async def capture_send(embed, view):
        nonlocal sent_embed
        sent_embed = embed
        return AsyncMock()

    mock_channel = AsyncMock()
    mock_channel.send = capture_send

    with patch('discord.utils.get', return_value=mock_channel):
        await tm.add_match_call(make_match_data(''))

    assert sent_embed is not None
    assert not sent_embed.title.startswith(' '), "Title must not start with a space"
    assert 'Winners' not in sent_embed.title
    assert 'Losers' not in sent_embed.title
    assert sent_embed.color != discord.Color.red()


@pytest.mark.asyncio
async def test_losers_round_number_is_absolute():
    """
    Challonge uses negative round numbers for losers bracket.
    The embed title should show a positive number.
    """
    tm = make_tm()
    sent_embed = None

    async def capture_send(embed, view):
        nonlocal sent_embed
        sent_embed = embed
        return AsyncMock()

    mock_channel = AsyncMock()
    mock_channel.send = capture_send

    with patch('discord.utils.get', return_value=mock_channel):
        await tm.add_match_call(make_match_data('Losers', round_number=-3))

    assert '-3' not in sent_embed.title, "Negative round number should not appear in title"
    assert '3' in sent_embed.title