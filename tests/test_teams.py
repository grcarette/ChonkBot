# tests/test_teams.py
"""
Tests for 2v2 teams mode behavior.

Architecture (Option A — lean, no separate teams collection):
- tournament['config']['teams_mode'] = True enables 2v2
- tournament['pending_teams'] = [{'player1_id': int, 'player2_id': int}, ...]
- tournament['entrants'] maps team_id → participant_id, same shape as solo
- team_id is a deterministic string: f"{min(p1,p2)}_{max(p1,p2)}"
- TournamentManager._make_team_id, _parse_team_id, _find_team_id_for_player are helpers
- dh.add_pending_team / remove_pending_team / get_pending_teams manage pending state
- dh.register_team / unregister_team manage confirmed entrants

Covers:
# ─── is_teams_mode property ───────────────────────────────────────────────────
- Returns True when config.teams_mode is True
- Returns False when config.teams_mode is False
- Returns False when key is absent

# ─── Helper methods ───────────────────────────────────────────────────────────
- _make_team_id is order-independent
- _make_team_id always puts lower ID first
- _parse_team_id round-trips correctly

# ─── Team registration (pending handshake) ────────────────────────────────────
- Creates pending team via dh.add_pending_team and returns 'pending'
- Returns 'self_invite' when player1 == player2
- Returns 'already_registered' when player1 is in entrants
- Returns 'partner_already_registered' when player2 is in entrants
- Returns 'already_pending' when player1 already has an outstanding invite

# ─── Team acceptance ──────────────────────────────────────────────────────────
- Confirms team, calls format.on_team_register, returns 'registered'
- Returns 'no_invite' when no pending invite exists for player
- Returns 'already_registered' when player2 is already in entrants
- Team name is set to "Player1 / Player2"
- Both players get Discord role assigned

# ─── Unregistration ───────────────────────────────────────────────────────────
- Calls dh.unregister_team and format.on_team_unregister
- Removes Discord roles from both team members
- No-op if player is not on a team
- Either team member can trigger unregistration

# ─── Tournament config ────────────────────────────────────────────────────────
- teams_mode stored in config on create_tournament
- teams_mode defaults to False when not supplied

# ─── Lobby member resolution ──────────────────────────────────────────────────
- resolve_team_members returns both discord IDs for each team
- Empty list returns empty list
- Raises ValueError for a team_id not in entrants

# ─── Discord role side-effects ────────────────────────────────────────────────
- accept_team_invite grants role to both players
- unregister_player removes role from both team members

# ─── Debug mode ───────────────────────────────────────────────────────────────
- Swiss debug: 2 teams registered (4 players paired)
- Challonge debug: 4 teams registered (8 players paired)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ─── Factory ──────────────────────────────────────────────────────────────────

def make_tm(fmt='double elimination', state='registration', debug=False, teams_mode=True):
    from tournaments.tournament_manager import TournamentManager

    tournament = {
        '_id': 'tid',
        'name': 'Test Tournament',
        'format': fmt,
        'state': state,
        'entrants': {},
        'pending_teams': [],
        'checked_in': [],
        'dqs': [],
        'stagelist': [],
        'organizers': [999],
        'config': {
            'approved_registration': False,
            'randomized_stagelist': False,
            'display_entrants': False,
            'ranked_reporting': False,
            'teams_mode': teams_mode,
        },
        'registration_open': True,
        'challonge_data': {'id': 'chid', 'url': 'test-url'},
        'debug': debug,
        'category_id': 99999,
    }

    tm = object.__new__(TournamentManager)
    tm.tournament = tournament
    tm.guild = MagicMock()
    tm.guild.members = []
    tm.lobbies = {}
    tm.tournament_reset = False
    tm.debug = debug
    tm.organizer_role = None

    tm.bot = MagicMock()
    tm.bot.dh = AsyncMock()
    tm.bot.dh.get_tournament_by_id = AsyncMock(return_value=tournament)
    tm.bot.dh.get_registration_status = AsyncMock(return_value=None)
    tm.bot.dh.register_player = AsyncMock(return_value=True)
    tm.bot.dh.register_user = AsyncMock()
    tm.bot.dh.get_user = AsyncMock(side_effect=lambda user_id=None: {
        101: {'user_id': 101, 'name': 'Alice'},
        102: {'user_id': 102, 'name': 'Bob'},
    }.get(user_id, {'user_id': user_id, 'name': f'player_{user_id}'}))
    tm.bot.dh.unregister_player = AsyncMock()
    tm.bot.dh.update_tournament_state = AsyncMock()
    tm.bot.dh.add_pending_team = AsyncMock()
    tm.bot.dh.remove_pending_team = AsyncMock()
    tm.bot.dh.get_pending_teams = AsyncMock(return_value=[])
    tm.bot.dh.register_team = AsyncMock()
    tm.bot.dh.unregister_team = AsyncMock()

    tm.format = MagicMock()
    tm.format.on_player_register = AsyncMock()
    tm.format.on_player_unregister = AsyncMock()
    tm.format.on_team_register = AsyncMock()
    tm.format.on_team_unregister = AsyncMock()

    tm.get_tournament = AsyncMock(return_value=tournament)
    tm.edit_event_info = AsyncMock()

    return tm, tournament


# ═══════════════════════════════════════════════════════════════════════════════
# is_teams_mode property
# ═══════════════════════════════════════════════════════════════════════════════

def test_is_teams_mode_true_when_config_set():
    tm, _ = make_tm(teams_mode=True)
    assert tm.is_teams_mode is True


def test_is_teams_mode_false_when_config_false():
    tm, _ = make_tm(teams_mode=False)
    assert tm.is_teams_mode is False


def test_is_teams_mode_false_when_key_absent():
    tm, t = make_tm(teams_mode=False)
    del t['config']['teams_mode']
    assert tm.is_teams_mode is False


# ═══════════════════════════════════════════════════════════════════════════════
# Helper methods
# ═══════════════════════════════════════════════════════════════════════════════

def test_make_team_id_is_order_independent():
    from tournaments.tournament_manager import TournamentManager
    assert TournamentManager._make_team_id(101, 102) == TournamentManager._make_team_id(102, 101)


def test_make_team_id_lower_id_first():
    from tournaments.tournament_manager import TournamentManager
    assert TournamentManager._make_team_id(200, 50) == '50_200'


def test_parse_team_id_round_trips():
    from tournaments.tournament_manager import TournamentManager
    team_id = TournamentManager._make_team_id(101, 202)
    p1, p2 = TournamentManager._parse_team_id(team_id)
    assert set((p1, p2)) == {101, 202}


# ═══════════════════════════════════════════════════════════════════════════════
# Team registration — pending handshake
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_register_player_team_creates_pending_team():
    tm, _ = make_tm()
    tm.bot.dh.get_pending_teams = AsyncMock(return_value=[])
    result = await tm.register_player_team(101, 102)
    tm.bot.dh.add_pending_team.assert_awaited_once_with('tid', 101, 102)
    assert result == 'pending'


@pytest.mark.asyncio
async def test_register_player_team_returns_self_invite_when_same_player():
    tm, _ = make_tm()
    result = await tm.register_player_team(101, 101)
    tm.bot.dh.add_pending_team.assert_not_awaited()
    assert result == 'self_invite'


@pytest.mark.asyncio
async def test_register_player_team_returns_already_registered_if_player1_on_team():
    tm, t = make_tm()
    t['entrants'] = {'101_102': None}
    tm.get_tournament = AsyncMock(return_value=t)
    tm.bot.dh.get_pending_teams = AsyncMock(return_value=[])
    result = await tm.register_player_team(101, 103)
    tm.bot.dh.add_pending_team.assert_not_awaited()
    assert result == 'already_registered'


@pytest.mark.asyncio
async def test_register_player_team_returns_partner_already_registered_if_player2_on_team():
    tm, t = make_tm()
    t['entrants'] = {'101_102': None}
    tm.get_tournament = AsyncMock(return_value=t)
    tm.bot.dh.get_pending_teams = AsyncMock(return_value=[])
    result = await tm.register_player_team(103, 102)
    tm.bot.dh.add_pending_team.assert_not_awaited()
    assert result == 'partner_already_registered'


@pytest.mark.asyncio
async def test_register_player_team_returns_already_pending_if_invite_outstanding():
    tm, _ = make_tm()
    tm.bot.dh.get_pending_teams = AsyncMock(return_value=[
        {'player1_id': 101, 'player2_id': 999}
    ])
    result = await tm.register_player_team(101, 102)
    tm.bot.dh.add_pending_team.assert_not_awaited()
    assert result == 'already_pending'


# ═══════════════════════════════════════════════════════════════════════════════
# Team acceptance
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_accept_team_invite_confirms_team_and_calls_on_team_register():
    tm, _ = make_tm()
    tm.bot.dh.get_pending_teams = AsyncMock(return_value=[
        {'player1_id': 101, 'player2_id': 102}
    ])

    with patch('tournaments.tournament_manager.discord.utils.get', return_value=None):
        result = await tm.accept_team_invite(102)

    tm.format.on_team_register.assert_awaited_once()
    assert result == 'registered'


@pytest.mark.asyncio
async def test_accept_team_invite_returns_no_invite_when_none_pending():
    tm, _ = make_tm()
    tm.bot.dh.get_pending_teams = AsyncMock(return_value=[])
    result = await tm.accept_team_invite(102)
    tm.format.on_team_register.assert_not_awaited()
    assert result == 'no_invite'


@pytest.mark.asyncio
async def test_accept_team_invite_returns_already_registered_if_already_on_team():
    tm, t = make_tm()
    t['entrants'] = {'101_102': None}
    tm.get_tournament = AsyncMock(return_value=t)
    tm.bot.dh.get_pending_teams = AsyncMock(return_value=[
        {'player1_id': 103, 'player2_id': 102}
    ])
    result = await tm.accept_team_invite(102)
    tm.format.on_team_register.assert_not_awaited()
    assert result == 'already_registered'


@pytest.mark.asyncio
async def test_accept_team_invite_team_id_contains_both_player_ids():
    tm, _ = make_tm()
    tm.bot.dh.get_pending_teams = AsyncMock(return_value=[
        {'player1_id': 101, 'player2_id': 102}
    ])

    with patch('tournaments.tournament_manager.discord.utils.get', return_value=None):
        await tm.accept_team_invite(102)

    call_args = tm.format.on_team_register.call_args[0]
    team_id = call_args[0]
    assert '101' in team_id and '102' in team_id


@pytest.mark.asyncio
async def test_team_name_is_player1_slash_player2():
    tm, _ = make_tm()
    tm.bot.dh.get_pending_teams = AsyncMock(return_value=[
        {'player1_id': 101, 'player2_id': 102}
    ])
    tm.bot.dh.get_user = AsyncMock(side_effect=lambda user_id=None: {
        101: {'user_id': 101, 'name': 'Alice'},
        102: {'user_id': 102, 'name': 'Bob'},
    }.get(user_id))

    with patch('tournaments.tournament_manager.discord.utils.get', return_value=None):
        await tm.accept_team_invite(102)

    team_doc = tm.format.on_team_register.call_args[0][1]
    assert team_doc['name'] == 'Alice / Bob'


# ═══════════════════════════════════════════════════════════════════════════════
# Unregistration
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_unregister_player_calls_unregister_team_and_on_team_unregister():
    tm, t = make_tm()
    t['entrants'] = {'101_102': None}
    tm.get_tournament = AsyncMock(return_value=t)
    with patch('tournaments.tournament_manager.discord.utils.get', return_value=None):
        await tm.unregister_player(101)
    tm.bot.dh.unregister_team.assert_awaited_once_with('tid', '101_102')
    tm.format.on_team_unregister.assert_awaited_once_with('101_102')


@pytest.mark.asyncio
async def test_unregister_player_noop_if_not_on_team():
    tm, t = make_tm()
    t['entrants'] = {}
    tm.get_tournament = AsyncMock(return_value=t)
    await tm.unregister_player(101)
    tm.bot.dh.unregister_team.assert_not_awaited()
    tm.format.on_team_unregister.assert_not_awaited()


@pytest.mark.asyncio
async def test_either_team_member_can_trigger_unregister():
    tm, t = make_tm()
    t['entrants'] = {'101_102': None}
    tm.get_tournament = AsyncMock(return_value=t)
    with patch('tournaments.tournament_manager.discord.utils.get', return_value=None):
        await tm.unregister_player(102)
    tm.bot.dh.unregister_team.assert_awaited_once_with('tid', '101_102')


# ═══════════════════════════════════════════════════════════════════════════════
# Tournament config
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_create_tournament_stores_teams_mode_true():
    from data.tournaments import TournamentMethodsMixin

    mixin = object.__new__(TournamentMethodsMixin)
    mixin.tournament_collection = AsyncMock()
    mixin.tournament_collection.find_one = AsyncMock(return_value=None)
    mixin.tournament_collection.insert_one = AsyncMock(
        return_value=MagicMock(inserted_id='new_id')
    )
    mixin.get_tournament = AsyncMock(return_value={
        '_id': 'new_id', 'name': 'T', 'config': {'teams_mode': True}
    })

    payload = {
        'name': 'T', 'date': '2026-01-01', 'organizer': 1,
        'format': 'double elimination',
        'approved_registration': False,
        'randomized_stagelist': False,
        'display_entrants': False,
        'teams_mode': True,
    }
    await mixin.create_tournament(payload)

    insert_call = mixin.tournament_collection.insert_one.call_args[0][0]
    assert insert_call['config']['teams_mode'] is True


@pytest.mark.asyncio
async def test_create_tournament_teams_mode_defaults_false():
    from data.tournaments import TournamentMethodsMixin

    mixin = object.__new__(TournamentMethodsMixin)
    mixin.tournament_collection = AsyncMock()
    mixin.tournament_collection.find_one = AsyncMock(return_value=None)
    mixin.tournament_collection.insert_one = AsyncMock(
        return_value=MagicMock(inserted_id='new_id')
    )
    mixin.get_tournament = AsyncMock(return_value={
        '_id': 'new_id', 'name': 'T', 'config': {'teams_mode': False}
    })

    payload = {
        'name': 'T', 'date': '2026-01-01', 'organizer': 1,
        'format': 'double elimination',
        'approved_registration': False,
        'randomized_stagelist': False,
        'display_entrants': False,
        # teams_mode intentionally omitted
    }
    await mixin.create_tournament(payload)

    insert_call = mixin.tournament_collection.insert_one.call_args[0][0]
    assert insert_call['config'].get('teams_mode', False) is False


# ═══════════════════════════════════════════════════════════════════════════════
# Lobby member resolution
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_resolve_team_members_returns_both_discord_ids():
    tm, t = make_tm()
    t['entrants'] = {'101_202': None, '50_201': None}
    tm.get_tournament = AsyncMock(return_value=t)
    members = await tm.resolve_team_members(['101_202', '50_201'])
    assert set(members) == {101, 202, 50, 201}


@pytest.mark.asyncio
async def test_resolve_team_members_empty_list_returns_empty():
    tm, _ = make_tm()
    members = await tm.resolve_team_members([])
    assert members == []


@pytest.mark.asyncio
async def test_resolve_team_members_raises_on_missing_team():
    tm, t = make_tm()
    t['entrants'] = {}
    tm.get_tournament = AsyncMock(return_value=t)
    with pytest.raises(ValueError, match='team_99'):
        await tm.resolve_team_members(['team_99'])


# ═══════════════════════════════════════════════════════════════════════════════
# Discord role side-effects
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_accept_team_invite_grants_role_to_both_players():
    tm, _ = make_tm()
    tm.bot.dh.get_pending_teams = AsyncMock(return_value=[
        {'player1_id': 101, 'player2_id': 102}
    ])

    member1 = MagicMock()
    member2 = MagicMock()
    member1.add_roles = AsyncMock()
    member2.add_roles = AsyncMock()
    role = MagicMock()

    def get_side_effect(seq, **kw):
        if kw.get('name'):
            return role
        return {101: member1, 102: member2}.get(kw.get('id'))

    with patch('tournaments.tournament_manager.discord.utils.get', side_effect=get_side_effect):
        await tm.accept_team_invite(102)

    member1.add_roles.assert_awaited_once_with(role)
    member2.add_roles.assert_awaited_once_with(role)


@pytest.mark.asyncio
async def test_unregister_player_removes_role_from_both_team_members():
    tm, t = make_tm()
    t['entrants'] = {'101_102': None}
    tm.get_tournament = AsyncMock(return_value=t)

    member1 = MagicMock()
    member2 = MagicMock()
    member1.remove_roles = AsyncMock()
    member2.remove_roles = AsyncMock()
    role = MagicMock()

    def get_side_effect(seq, **kw):
        if kw.get('name'):
            return role
        return {101: member1, 102: member2}.get(kw.get('id'))

    with patch('tournaments.tournament_manager.discord.utils.get', side_effect=get_side_effect):
        await tm.unregister_player(101)

    member1.remove_roles.assert_awaited_once_with(role)
    member2.remove_roles.assert_awaited_once_with(role)


# ═══════════════════════════════════════════════════════════════════════════════
# Debug mode
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_debug_swiss_registers_2_teams():
    tm, t = make_tm(fmt='swiss', debug=True, teams_mode=True)
    t['debug'] = True
    tm.debug = True
    tm.get_channel = AsyncMock(return_value=None)
    tm.register_player_team = AsyncMock(return_value='pending')
    tm.accept_team_invite = AsyncMock(return_value='registered')
    tm.get_tournament = AsyncMock(return_value=t)

    with patch('tournaments.tournament_manager.create_channel', new=AsyncMock(return_value=AsyncMock())):
        await tm.open_registration()

    assert tm.register_player_team.await_count == 2


@pytest.mark.asyncio
async def test_debug_challonge_registers_4_teams():
    tm, t = make_tm(fmt='double elimination', debug=True, teams_mode=True)
    t['debug'] = True
    tm.debug = True
    tm.get_channel = AsyncMock(return_value=None)
    tm.register_player_team = AsyncMock(return_value='pending')
    tm.accept_team_invite = AsyncMock(return_value='registered')
    tm.get_tournament = AsyncMock(return_value=t)

    with patch('tournaments.tournament_manager.create_channel', new=AsyncMock(return_value=AsyncMock())):
        await tm.open_registration()

    assert tm.register_player_team.await_count == 4