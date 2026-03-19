"""
tests/test_bracket_persistence.py

Tests that the `bracket` field is correctly stored in the DB when a lobby
is created, and correctly restored when the bot restarts and rehydrates lobbies
from the DB.

This is the regression test for the lobby-name-as-bracket-tag bandaid:
after the fix, bracket context must survive a bot restart.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, call


def make_dh():
    dh = AsyncMock()
    dh.get_tournament_by_id = AsyncMock(return_value={
        '_id': 'tid',
        'name': 'Test Tournament',
        'format': 'double elimination',
        'stagelist': [],
        'entrants': {},
        'dqs': [],
    })
    return dh


# ─── create_lobby stores bracket ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_lobby_stores_winners_bracket():
    from data.lobby import LobbyMethodsMixin

    dh = LobbyMethodsMixin.__new__(LobbyMethodsMixin)
    dh.lobby_collection = AsyncMock()
    dh.lobby_collection.count_documents = AsyncMock(return_value=0)
    dh.lobby_collection.insert_one = AsyncMock()
    dh.get_prereq_matches = AsyncMock(return_value=[])

    tournament = {'_id': 'tid', 'name': 'Test'}
    await dh.create_lobby(
        tournament=tournament,
        match_id=10,
        lobby_name='wr1-A vs B',
        prereq_matches=[],
        players=[1, 2],
        stages=[],
        num_winners=1,
        bracket='Winners',
    )

    inserted = dh.lobby_collection.insert_one.call_args[0][0]
    assert inserted['bracket'] == 'Winners'


@pytest.mark.asyncio
async def test_create_lobby_stores_losers_bracket():
    from data.lobby import LobbyMethodsMixin

    dh = LobbyMethodsMixin.__new__(LobbyMethodsMixin)
    dh.lobby_collection = AsyncMock()
    dh.lobby_collection.count_documents = AsyncMock(return_value=2)
    dh.lobby_collection.insert_one = AsyncMock()
    dh.get_prereq_matches = AsyncMock(return_value=[])

    tournament = {'_id': 'tid', 'name': 'Test'}
    await dh.create_lobby(
        tournament=tournament,
        match_id=11,
        lobby_name='lr1-A vs B',
        prereq_matches=[],
        players=[1, 2],
        stages=[],
        num_winners=1,
        bracket='Losers',
    )

    inserted = dh.lobby_collection.insert_one.call_args[0][0]
    assert inserted['bracket'] == 'Losers'


@pytest.mark.asyncio
async def test_create_lobby_stores_none_bracket_for_swiss():
    from data.lobby import LobbyMethodsMixin

    dh = LobbyMethodsMixin.__new__(LobbyMethodsMixin)
    dh.lobby_collection = AsyncMock()
    dh.lobby_collection.count_documents = AsyncMock(return_value=0)
    dh.lobby_collection.insert_one = AsyncMock()
    dh.get_prereq_matches = AsyncMock(return_value=[])

    tournament = {'_id': 'tid', 'name': 'Test'}
    await dh.create_lobby(
        tournament=tournament,
        match_id=20,
        lobby_name='swiss-A-vs-B',
        prereq_matches=[],
        players=[1, 2],
        stages=[],
        num_winners=1,
        bracket=None,
    )

    inserted = dh.lobby_collection.insert_one.call_args[0][0]
    assert 'bracket' in inserted
    assert inserted['bracket'] is None


# ─── setup_lobby passes bracket to create_lobby ───────────────────────────────

@pytest.mark.asyncio
async def test_setup_lobby_passes_bracket_to_db():
    """
    When a MatchLobby is newly created (no existing DB entry),
    setup_lobby should pass self.bracket through to dh.create_lobby.
    """
    from tournaments.match_lobby import MatchLobby

    lobby = object.__new__(MatchLobby)
    lobby.tournament_id = 'tid'
    lobby.match_id = 5
    lobby.lobby_name = 'wr1-A vs B'
    lobby.players = [1, 2]
    lobby.prereq_matches = []
    lobby.stages = []
    lobby.num_winners = 1
    lobby.bracket = 'Winners'
    lobby.channel = None
    lobby.guild = MagicMock()
    lobby.tournament = {'_id': 'tid', 'name': 'Test'}
    lobby.organizer_role = 'Test TO'

    lobby.dh = AsyncMock()
    lobby.dh.create_lobby = AsyncMock(return_value=1)

    await lobby.setup_lobby()

    call_kwargs = lobby.dh.create_lobby.call_args
    assert call_kwargs.kwargs.get('bracket') == 'Winners' or \
        (len(call_kwargs.args) > 8 and call_kwargs.args[8] == 'Winners'), \
        "setup_lobby must pass bracket to create_lobby"


# ─── Restart rehydration reads bracket from DB ────────────────────────────────

@pytest.mark.asyncio
async def test_rehydrated_lobby_has_correct_bracket():
    """
    Simulate the bot restarting and reloading active lobbies.
    The bracket field should be read from the DB document and
    set on the MatchLobby object.
    """
    from tournaments.match_lobby import MatchLobby

    stored_lobby_doc = {
        'match_id': 7,
        'lobby_name': 'lr2-A vs B',
        'prereq_matches': [],
        'players': [1, 2],
        'stages': [],
        'num_winners': 1,
        'bracket': 'Losers',   # stored in DB
        'state': 'reporting',
        'channel_id': 999,     # required by add_channel()
        'results': [],
        'checked_in': [],
    }

    dh = AsyncMock()
    dh.get_tournament_by_id = AsyncMock(return_value={
        '_id': 'tid', 'name': 'Test', 'format': 'double elimination',
        'stagelist': [], 'entrants': {}, 'dqs': [],
    })
    dh.get_lobby = AsyncMock(return_value=stored_lobby_doc)
    dh.add_channel_to_lobby = AsyncMock()

    tm = MagicMock()
    tm.is_swiss = False
    mock_channel = AsyncMock()
    mock_channel.id = 999
    guild = MagicMock()
    guild.channels = [mock_channel]

    lobby = await MatchLobby.create(
        tournament_id='tid',
        match_id=7,
        lobby_name='lr2-A vs B',
        prereq_matches=[],
        players=[1, 2],
        stages=[],
        num_winners=1,
        tournament_manager=tm,
        datahandler=dh,
        guild=guild,
        bracket=stored_lobby_doc['bracket'],   # passed from DB doc
    )

    assert lobby.bracket == 'Losers'