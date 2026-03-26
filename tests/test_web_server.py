# tests/test_web_server.py
"""
Tests for the web server API.

Covers:
# ─── Auth ─────────────────────────────────────────────────────────────────────
- Unauthenticated requests to session-protected routes redirect to /auth/login
- Valid session cookie grants access to protected routes
- Expired session is rejected and redirects to /auth/login
- OAuth callback with no code redirects to login with error
- OAuth callback for non-TO user redirects to login with error
- OAuth callback for valid TO user sets session cookie and redirects to dashboard
- Logout deletes session from DB and clears cookie
- Login page redirects to dashboard if already authenticated

# ─── Token auth (seeding) ─────────────────────────────────────────────────────
- generate_token produces a token that validate_token accepts
- validate_token returns None for unknown token
- validate_token returns None and removes expired token
- Seeding page returns 403 with no token
- Seeding page returns 403 with invalid token
- Seeding page returns HTML with token injected when token is valid
- GET /api/participants returns 403 with no token
- GET /api/participants returns participant list with valid token
- POST /api/seed returns 403 with no token
- POST /api/seed returns 400 with missing fields
- POST /api/seed returns 200 and calls challonge handler on success

# ─── GET /api/tournaments ─────────────────────────────────────────────────────
- Returns list with correct fields per tournament
- active_count reflects only tournaments in 'active' state
- lobby_count and player_count are summed across all tournaments
- Tournaments sorted: non-debug before debug, then by state order
- Returns empty list when no tournaments exist

# ─── POST /api/tournaments ────────────────────────────────────────────────────
- Returns 400 when required fields are missing
- Creates tournament and returns its id on success

# ─── GET /api/tournament/{id} ────────────────────────────────────────────────
- Returns 404 for unknown tournament_id
- Returns correct shape: name, format, state, entrants, lobbies, stagelist, config, swiss
- stagelist_ready is True when stagelist_published is True
- stagelist_ready is True for Swiss with randomized_stagelist and a non-empty stagelist
- stagelist_ready is False otherwise
- swiss field is None for non-Swiss tournaments
- swiss field contains current_round, round_limit, active_matches, players_remaining

# ─── POST /api/tournament/{id}/action ────────────────────────────────────────
- Returns 400 for invalid JSON body
- Returns 400 when action field is missing
- Returns 400 for unknown action name
- Returns 404 when tournament not found
- Returns 400 when tm is not loaded and action requires it
- 'progress' calls tm.progress_tournament
- 'open_registration' calls tm.open_registration
- 'close_registration' calls tm.close_registration
- 'ping_checkin' returns 400 when ping limit reached
- 'ping_checkin' returns 200 when ping succeeds
- 'next_round' returns 400 for non-Swiss format
- 'next_round' calls tm.format.manager.run_pairing_cycle for Swiss
- 'dq_player' returns 400 when discord_id is missing
- 'dq_player' returns 400 when player is not registered
- 'dq_player' calls tm.disqualify_player with correct id
- 'undq_player' returns 400 when discord_id is missing
- 'undq_player' calls tm.undisqualify_player
- 'revert_tournament' calls tm.revert_tournament
- 'delete_tournament' calls tm.delete_tournament
- 'unpublish_tournament' calls remove_from_discord and dh.unpublish_tournament
- 'post_results' calls tm.post_final_results
- 'call_match' returns 400 when match_id is missing
- 'call_match' returns 400 when match not found in pending
- 'call_match' calls tm.format.call_match on success
- 'set_autocall' returns 400 for non-Challonge format
- 'toggle_hold_when_ready' returns 400 when match_id missing
- 'reopen_lobby' calls tm.reopen_lobby with match_id as string

# ─── POST /api/tournament/{id}/stages ────────────────────────────────────────
- Returns 400 when codes field is missing
- Returns 400 when any code is invalid
- Returns 200 and calls dh.add_stages_to_tournament with valid codes
- Multiple comma-separated codes are all added

# ─── DELETE /api/tournament/{id}/stages/{code} ───────────────────────────────
- Returns 404 for unknown tournament
- Returns 200 and calls dh.remove_stage_from_tournament

# ─── DELETE /api/tournament/{id}/upload/{image_type} ────────────────────────
- Returns 400 for invalid image_type (not banner or logo)
- Returns 200 and calls dh.update_tournament_image_path with None
"""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta
from aiohttp.test_utils import TestClient, TestServer
from aiohttp import web


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_bot(tournament=None, tournaments=None):
    """Build a minimal bot mock wired for web server tests."""
    bot = MagicMock()
    bot.guild = MagicMock()
    bot.guild.get_member = MagicMock(return_value=None)

    dh = AsyncMock()
    dh.get_session = AsyncMock(return_value=None)
    dh.delete_session = AsyncMock()
    dh.get_active_events = AsyncMock(return_value=tournaments or [])
    dh.get_active_lobbies = AsyncMock(return_value=[])
    dh.get_all_lobbies = AsyncMock(return_value=[])
    dh.get_users_bulk = AsyncMock(return_value={
        100: {'name': 'Player100', 'avatar_url': None},
        200: {'name': 'Player200', 'avatar_url': None},
    })
    dh.get_tournament_by_id = AsyncMock(return_value=tournament)
    dh.get_stages_from_list = AsyncMock(return_value=[])
    dh.get_swiss_event_by_tournament = AsyncMock(return_value=None)
    dh.get_registration_requests = AsyncMock(return_value=[])
    dh.add_stages_to_tournament = AsyncMock()
    dh.remove_stage_from_tournament = AsyncMock()
    dh.update_tournament_image_path = AsyncMock()
    dh.create_tournament = AsyncMock(return_value={'_id': 'new_tid'})
    bot.dh = dh

    bot.th = MagicMock()
    bot.th.tournaments = {}

    return bot


def make_session():
    return {
        'token': 'valid_token',
        'discord_user_id': 123,
        'discord_username': 'TestUser',
        'avatar': None,
        'expires_at': datetime.now(timezone.utc) + timedelta(days=1),
    }


def make_tournament(tid='tid', state='registration', fmt='double elimination'):
    return {
        '_id': tid,
        'name': 'Test Tournament',
        'format': fmt,
        'state': state,
        'date': '2026-01-01',
        'entrants': {'100': 10, '200': 20},
        'checked_in': [100],
        'dqs': [],
        'stagelist': [],
        'stagelist_published': False,
        'registration_open': True,
        'config': {
            'approved_registration': False,
            'randomized_stagelist': False,
            'display_entrants': False,
            'ranked_reporting': False,
        },
        'debug': False,
    }


def make_app(bot):
    from web.web_server import create_app
    challonge_factory = MagicMock(return_value=AsyncMock())
    return create_app(challonge_factory, bot)


async def authed_client(aiohttp_client, bot):
    """Return a TestClient with a valid session cookie pre-set."""
    session = make_session()
    bot.dh.get_session = AsyncMock(return_value=session)
    app = make_app(bot)
    client = await aiohttp_client(app)
    client.session.cookie_jar.update_cookies({'session': 'valid_token'})
    return client


# ═══════════════════════════════════════════════════════════════════════════════
# Auth
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_unauthenticated_request_redirects_to_login(aiohttp_client):
    bot = make_bot()
    bot.dh.get_session = AsyncMock(return_value=None)
    client = await aiohttp_client(make_app(bot))

    resp = await client.get('/api/tournaments', allow_redirects=False)

    assert resp.status == 302
    assert '/auth/login' in resp.headers['Location']


@pytest.mark.asyncio
async def test_valid_session_grants_access(aiohttp_client):
    bot = make_bot()
    client = await authed_client(aiohttp_client, bot)

    resp = await client.get('/api/tournaments')

    assert resp.status == 200


@pytest.mark.asyncio
async def test_expired_session_redirects_to_login(aiohttp_client):
    bot = make_bot()
    expired_session = {
        **make_session(),
        'expires_at': datetime.now(timezone.utc) - timedelta(days=1),
    }
    bot.dh.get_session = AsyncMock(return_value=expired_session)
    app = make_app(bot)
    client = await aiohttp_client(app)
    client.session.cookie_jar.update_cookies({'session': 'expired_token'})

    resp = await client.get('/api/tournaments', allow_redirects=False)

    assert resp.status == 302
    assert '/auth/login' in resp.headers['Location']


@pytest.mark.asyncio
async def test_oauth_callback_no_code_redirects_with_error(aiohttp_client):
    bot = make_bot()
    client = await aiohttp_client(make_app(bot))

    resp = await client.get('/auth/callback', allow_redirects=False)

    assert resp.status == 302
    assert 'missing_code' in resp.headers['Location']


@pytest.mark.asyncio
async def test_oauth_callback_non_to_user_redirects_with_error(aiohttp_client):
    bot = make_bot()
    bot.guild.get_member = MagicMock(return_value=None)  # not in guild → not TO
    client = await aiohttp_client(make_app(bot))

    with patch('web.auth.exchange_code_for_token', AsyncMock(return_value={'access_token': 'tok'})), \
         patch('web.auth.get_discord_user', AsyncMock(return_value={'id': '999', 'username': 'nobody', 'avatar': None})), \
         patch('web.auth.is_tournament_organizer', return_value=False):
        resp = await client.get('/auth/callback?code=abc', allow_redirects=False)

    assert resp.status == 302
    assert 'unauthorized' in resp.headers['Location']


@pytest.mark.asyncio
async def test_oauth_callback_valid_to_sets_cookie_and_redirects(aiohttp_client):
    bot = make_bot()
    bot.dh.create_session = AsyncMock(return_value=None)
    client = await aiohttp_client(make_app(bot))

    with patch('web.auth.exchange_code_for_token', AsyncMock(return_value={'access_token': 'tok'})), \
         patch('web.auth.get_discord_user', AsyncMock(return_value={'id': '123', 'username': 'TO_User', 'avatar': None})), \
         patch('web.auth.is_tournament_organizer', return_value=True), \
         patch('web.auth.create_session', AsyncMock(return_value='new_session_token')):
        resp = await client.get('/auth/callback?code=abc', allow_redirects=False)

    assert resp.status == 302
    assert resp.headers['Location'] == '/dashboard'
    assert 'session' in resp.cookies


@pytest.mark.asyncio
async def test_logout_deletes_session_and_clears_cookie(aiohttp_client):
    bot = make_bot()
    client = await authed_client(aiohttp_client, bot)

    resp = await client.get('/auth/logout', allow_redirects=False)

    bot.dh.delete_session.assert_awaited_once_with('valid_token')
    assert resp.status == 302


@pytest.mark.asyncio
async def test_login_page_redirects_to_dashboard_when_already_authenticated(aiohttp_client):
    bot = make_bot()
    client = await authed_client(aiohttp_client, bot)

    resp = await client.get('/auth/login', allow_redirects=False)

    assert resp.status == 302
    assert '/dashboard' in resp.headers['Location']


# ═══════════════════════════════════════════════════════════════════════════════
# Token auth (seeding)
# ═══════════════════════════════════════════════════════════════════════════════

def test_generate_token_is_valid():
    from web.web_server import generate_token, validate_token, token_store
    token_store.clear()

    token = generate_token('tid', 'https://challonge.com/test')
    result = validate_token(token)

    assert result is not None
    assert result['tournament_id'] == 'tid'


def test_validate_token_returns_none_for_unknown():
    from web.web_server import validate_token
    assert validate_token('nonexistent_token') is None


def test_validate_token_removes_and_returns_none_for_expired():
    from web.web_server import validate_token, token_store
    token_store['expired'] = {
        'tournament_id': 'tid',
        'challonge_url': 'url',
        'expires_at': datetime.now(timezone.utc) - timedelta(minutes=1),
    }

    result = validate_token('expired')

    assert result is None
    assert 'expired' not in token_store


@pytest.mark.asyncio
async def test_seeding_page_returns_403_with_no_token(aiohttp_client):
    bot = make_bot()
    client = await aiohttp_client(make_app(bot))

    resp = await client.get('/seeding')

    assert resp.status == 403


@pytest.mark.asyncio
async def test_seeding_page_returns_403_with_invalid_token(aiohttp_client):
    bot = make_bot()
    client = await aiohttp_client(make_app(bot))

    resp = await client.get('/seeding?token=bad_token')

    assert resp.status == 403


@pytest.mark.asyncio
async def test_seeding_page_returns_html_with_valid_token(aiohttp_client):
    from web.web_server import generate_token, token_store
    token_store.clear()

    bot = make_bot(tournament=make_tournament())
    client = await aiohttp_client(make_app(bot))
    token = generate_token('tid', 'https://challonge.com/test')

    resp = await client.get(f'/seeding?token={token}')
    text = await resp.text()

    assert resp.status == 200
    assert token in text


@pytest.mark.asyncio
async def test_get_participants_returns_403_with_no_token(aiohttp_client):
    bot = make_bot()
    client = await aiohttp_client(make_app(bot))

    resp = await client.get('/api/participants')

    assert resp.status == 403


@pytest.mark.asyncio
async def test_get_participants_returns_list_with_valid_token(aiohttp_client):
    from web.web_server import generate_token, token_store
    token_store.clear()

    tournament = make_tournament()
    tournament['entrants'] = {'100': 10}
    bot = make_bot(tournament=tournament)
    bot.guild.get_member = MagicMock(return_value=None)

    challonge_handler = AsyncMock()
    challonge_handler.get_participants = AsyncMock(return_value=[
        {'id': 10, 'name': 'Player1', 'seed': 1}
    ])
    bot_app = make_app(bot)
    bot_app['challonge_handler_factory'] = MagicMock(return_value=challonge_handler)

    client = await aiohttp_client(bot_app)
    token = generate_token('tid', 'https://challonge.com/test')

    resp = await client.get(f'/api/participants?token={token}')
    data = await resp.json()

    assert resp.status == 200
    assert isinstance(data, list)
    assert data[0]['name'] == 'Player1'


@pytest.mark.asyncio
async def test_update_seed_returns_403_with_no_token(aiohttp_client):
    bot = make_bot()
    client = await aiohttp_client(make_app(bot))

    resp = await client.post('/api/seed', json={'participant_id': 1, 'seed': 2})

    assert resp.status == 403


@pytest.mark.asyncio
async def test_update_seed_returns_400_with_missing_fields(aiohttp_client):
    from web.web_server import generate_token, token_store
    token_store.clear()

    bot = make_bot()
    client = await aiohttp_client(make_app(bot))
    token = generate_token('tid', 'https://challonge.com/test')

    resp = await client.post(f'/api/seed?token={token}', json={})

    assert resp.status == 400


@pytest.mark.asyncio
async def test_update_seed_calls_challonge_on_success(aiohttp_client):
    from web.web_server import generate_token, token_store
    token_store.clear()

    bot = make_bot()
    challonge_handler = AsyncMock()
    challonge_handler.update_seed = AsyncMock()
    bot_app = make_app(bot)
    bot_app['challonge_handler_factory'] = MagicMock(return_value=challonge_handler)

    client = await aiohttp_client(bot_app)
    token = generate_token('tid', 'https://challonge.com/test')

    resp = await client.post(
        f'/api/seed?token={token}',
        json={'participant_id': 10, 'seed': 3}
    )
    data = await resp.json()

    assert resp.status == 200
    assert data['ok'] is True
    challonge_handler.update_seed.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/tournaments
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_tournaments_returns_correct_fields(aiohttp_client):
    t = make_tournament(state='active')
    bot = make_bot(tournaments=[t])
    client = await authed_client(aiohttp_client, bot)

    resp = await client.get('/api/tournaments')
    data = await resp.json()

    assert resp.status == 200
    assert len(data['tournaments']) == 1
    entry = data['tournaments'][0]
    for field in ('id', 'name', 'format', 'state', 'entrant_count', 'lobby_count'):
        assert field in entry, f"Missing field: {field}"


@pytest.mark.asyncio
async def test_get_tournaments_active_count(aiohttp_client):
    bot = make_bot(tournaments=[
        make_tournament(tid='t1', state='active'),
        make_tournament(tid='t2', state='registration'),
        make_tournament(tid='t3', state='active'),
    ])
    client = await authed_client(aiohttp_client, bot)

    resp = await client.get('/api/tournaments')
    data = await resp.json()

    assert data['active_count'] == 2


@pytest.mark.asyncio
async def test_get_tournaments_sorted_debug_last(aiohttp_client):
    t_normal = {**make_tournament(tid='t1', state='registration'), 'debug': False}
    t_debug  = {**make_tournament(tid='t2', state='active'),       'debug': True}
    bot = make_bot(tournaments=[t_debug, t_normal])
    client = await authed_client(aiohttp_client, bot)

    resp = await client.get('/api/tournaments')
    data = await resp.json()

    ids = [t['id'] for t in data['tournaments']]
    assert ids.index('t1') < ids.index('t2'), "Non-debug tournaments must come before debug ones"


@pytest.mark.asyncio
async def test_get_tournaments_empty(aiohttp_client):
    bot = make_bot(tournaments=[])
    client = await authed_client(aiohttp_client, bot)

    resp = await client.get('/api/tournaments')
    data = await resp.json()

    assert data['tournaments'] == []
    assert data['active_count'] == 0
    assert data['player_count'] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/tournament/{id}
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_tournament_returns_404_for_unknown(aiohttp_client):
    bot = make_bot(tournament=None)
    client = await authed_client(aiohttp_client, bot)

    resp = await client.get('/api/tournament/nonexistent')

    assert resp.status == 404


@pytest.mark.asyncio
async def test_get_tournament_returns_correct_shape(aiohttp_client):
    bot = make_bot(tournament=make_tournament())
    client = await authed_client(aiohttp_client, bot)

    resp = await client.get('/api/tournament/tid')
    data = await resp.json()

    assert resp.status == 200
    for field in ('name', 'format', 'state', 'entrant_count', 'lobby_count',
                  'entrants', 'stagelist', 'config', 'swiss', 'dqs'):
        assert field in data, f"Missing field: {field}"


@pytest.mark.asyncio
async def test_get_tournament_stagelist_ready_when_published(aiohttp_client):
    t = make_tournament()
    t['stagelist_published'] = True
    bot = make_bot(tournament=t)
    client = await authed_client(aiohttp_client, bot)

    resp = await client.get('/api/tournament/tid')
    data = await resp.json()

    assert data['stagelist_ready'] is True


@pytest.mark.asyncio
async def test_get_tournament_stagelist_ready_for_swiss_randomized(aiohttp_client):
    t = make_tournament(fmt='swiss')
    t['stagelist_published'] = False
    t['config']['randomized_stagelist'] = True
    t['stagelist'] = ['ABC']
    bot = make_bot(tournament=t)
    client = await authed_client(aiohttp_client, bot)

    resp = await client.get('/api/tournament/tid')
    data = await resp.json()

    assert data['stagelist_ready'] is True


@pytest.mark.asyncio
async def test_get_tournament_stagelist_not_ready_by_default(aiohttp_client):
    bot = make_bot(tournament=make_tournament())
    client = await authed_client(aiohttp_client, bot)

    resp = await client.get('/api/tournament/tid')
    data = await resp.json()

    assert data['stagelist_ready'] is False


@pytest.mark.asyncio
async def test_get_tournament_swiss_field_none_for_non_swiss(aiohttp_client):
    bot = make_bot(tournament=make_tournament(fmt='double elimination'))
    client = await authed_client(aiohttp_client, bot)

    resp = await client.get('/api/tournament/tid')
    data = await resp.json()

    assert data['swiss'] is None


@pytest.mark.asyncio
async def test_get_tournament_swiss_field_populated_for_swiss(aiohttp_client):
    t = make_tournament(fmt='swiss', state='active')
    swiss_event = {
        '_id': 'eid',
        'current_round': 2,
        'round_limit': 5,
        'players': {
            '100': {'active_match_id': 42, 'dropped': False, 'points': 1.0},
            '200': {'active_match_id': 42, 'dropped': False, 'points': 0.0},
        },
        'matches': [],
        'bye_queue': None,
    }
    bot = make_bot(tournament=t)
    bot.dh.get_swiss_event_by_tournament = AsyncMock(return_value=swiss_event)
    client = await authed_client(aiohttp_client, bot)

    resp = await client.get('/api/tournament/tid')
    data = await resp.json()

    assert data['swiss'] is not None
    assert data['swiss']['current_round'] == 2
    assert data['swiss']['round_limit'] == 5
    assert data['swiss']['active_matches'] == 1
    assert data['swiss']['players_remaining'] == 2


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/tournament/{id}/action — validation
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_action_returns_400_for_invalid_json(aiohttp_client):
    bot = make_bot(tournament=make_tournament())
    client = await authed_client(aiohttp_client, bot)

    resp = await client.post(
        '/api/tournament/tid/action',
        data='not json',
        headers={'Content-Type': 'application/json'},
    )

    assert resp.status == 400


@pytest.mark.asyncio
async def test_action_returns_400_when_action_missing(aiohttp_client):
    bot = make_bot(tournament=make_tournament())
    client = await authed_client(aiohttp_client, bot)

    resp = await client.post('/api/tournament/tid/action', json={})

    assert resp.status == 400


@pytest.mark.asyncio
async def test_action_returns_400_for_unknown_action(aiohttp_client):
    bot = make_bot(tournament=make_tournament())
    client = await authed_client(aiohttp_client, bot)

    resp = await client.post('/api/tournament/tid/action', json={'action': 'explode_everything'})
    data = await resp.json()

    assert resp.status == 400
    assert 'Unknown action' in data['error']


@pytest.mark.asyncio
async def test_action_returns_404_for_unknown_tournament(aiohttp_client):
    bot = make_bot(tournament=None)
    client = await authed_client(aiohttp_client, bot)

    resp = await client.post('/api/tournament/ghost/action', json={'action': 'progress'})

    assert resp.status == 404


@pytest.mark.asyncio
async def test_action_returns_400_when_tm_not_loaded(aiohttp_client):
    bot = make_bot(tournament=make_tournament())
    bot.th.tournaments = {}  # tm missing
    client = await authed_client(aiohttp_client, bot)

    resp = await client.post('/api/tournament/tid/action', json={'action': 'progress'})

    assert resp.status == 400


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/tournament/{id}/action — individual actions
# ═══════════════════════════════════════════════════════════════════════════════

def make_tm_bot(tournament, **tm_overrides):
    """Bot with a loaded TournamentManager mock."""
    bot = make_bot(tournament=tournament)
    tm = MagicMock()
    tm.progress_tournament = AsyncMock()
    tm.open_registration = AsyncMock()
    tm.close_registration = AsyncMock()
    tm.ping_checkin = AsyncMock(return_value=True)
    tm.disqualify_player = AsyncMock(return_value=True)
    tm.undisqualify_player = AsyncMock()
    tm.revert_tournament = AsyncMock()
    tm.delete_tournament = AsyncMock()
    tm.post_final_results = AsyncMock()
    tm.remove_tournament_from_discord = AsyncMock()
    tm.reopen_lobby = AsyncMock()
    tm.format = MagicMock()
    tm.format.manager = MagicMock()
    tm.format.manager.run_pairing_cycle = AsyncMock()
    tm.format.call_match = AsyncMock()
    tm.format.call_matches = AsyncMock()
    tm.format.get_pending_matches = AsyncMock(return_value=[])
    tm.format.autocall_matches = False
    tm.format.invalidate_pending_cache = MagicMock()
    tm.lobbies = {}
    for k, v in tm_overrides.items():
        setattr(tm, k, v)
    bot.th.tournaments[tournament['_id']] = tm
    return bot, tm


@pytest.mark.asyncio
async def test_action_progress_calls_progress_tournament(aiohttp_client):
    t = make_tournament()
    bot, tm = make_tm_bot(t)
    client = await authed_client(aiohttp_client, bot)

    resp = await client.post('/api/tournament/tid/action', json={'action': 'progress'})

    assert resp.status == 200
    tm.progress_tournament.assert_awaited_once()


@pytest.mark.asyncio
async def test_action_open_registration(aiohttp_client):
    t = make_tournament()
    bot, tm = make_tm_bot(t)
    client = await authed_client(aiohttp_client, bot)

    resp = await client.post('/api/tournament/tid/action', json={'action': 'open_registration'})

    assert resp.status == 200
    tm.open_registration.assert_awaited_once()


@pytest.mark.asyncio
async def test_action_close_registration(aiohttp_client):
    t = make_tournament()
    bot, tm = make_tm_bot(t)
    client = await authed_client(aiohttp_client, bot)

    resp = await client.post('/api/tournament/tid/action', json={'action': 'close_registration'})

    assert resp.status == 200
    tm.close_registration.assert_awaited_once()


@pytest.mark.asyncio
async def test_action_ping_checkin_returns_400_when_limit_reached(aiohttp_client):
    t = make_tournament()
    bot, tm = make_tm_bot(t)
    tm.ping_checkin = AsyncMock(return_value=False)
    client = await authed_client(aiohttp_client, bot)

    resp = await client.post('/api/tournament/tid/action', json={'action': 'ping_checkin'})

    assert resp.status == 400


@pytest.mark.asyncio
async def test_action_ping_checkin_returns_200_on_success(aiohttp_client):
    t = make_tournament()
    bot, tm = make_tm_bot(t)
    tm.ping_checkin = AsyncMock(return_value=True)
    client = await authed_client(aiohttp_client, bot)

    resp = await client.post('/api/tournament/tid/action', json={'action': 'ping_checkin'})

    assert resp.status == 200


@pytest.mark.asyncio
async def test_action_next_round_returns_400_for_non_swiss(aiohttp_client):
    t = make_tournament(fmt='double elimination')
    bot, tm = make_tm_bot(t)
    client = await authed_client(aiohttp_client, bot)

    resp = await client.post('/api/tournament/tid/action', json={'action': 'next_round'})

    assert resp.status == 400


@pytest.mark.asyncio
async def test_action_next_round_calls_run_pairing_cycle_for_swiss(aiohttp_client):
    t = make_tournament(fmt='swiss')
    bot, tm = make_tm_bot(t)
    client = await authed_client(aiohttp_client, bot)

    resp = await client.post('/api/tournament/tid/action', json={'action': 'next_round'})

    assert resp.status == 200
    tm.format.manager.run_pairing_cycle.assert_awaited_once()


@pytest.mark.asyncio
async def test_action_dq_player_returns_400_when_discord_id_missing(aiohttp_client):
    t = make_tournament()
    bot, tm = make_tm_bot(t)
    client = await authed_client(aiohttp_client, bot)

    resp = await client.post('/api/tournament/tid/action', json={'action': 'dq_player'})

    assert resp.status == 400


@pytest.mark.asyncio
async def test_action_dq_player_returns_400_when_not_registered(aiohttp_client):
    t = make_tournament()
    bot, tm = make_tm_bot(t)
    tm.disqualify_player = AsyncMock(return_value=False)
    client = await authed_client(aiohttp_client, bot)

    resp = await client.post('/api/tournament/tid/action', json={'action': 'dq_player', 'discord_id': 999})

    assert resp.status == 400


@pytest.mark.asyncio
async def test_action_dq_player_calls_disqualify_with_correct_id(aiohttp_client):
    t = make_tournament()
    bot, tm = make_tm_bot(t)
    client = await authed_client(aiohttp_client, bot)

    await client.post('/api/tournament/tid/action', json={'action': 'dq_player', 'discord_id': 100})

    tm.disqualify_player.assert_awaited_once_with(100)


@pytest.mark.asyncio
async def test_action_undq_player_returns_400_when_discord_id_missing(aiohttp_client):
    t = make_tournament()
    bot, tm = make_tm_bot(t)
    client = await authed_client(aiohttp_client, bot)

    resp = await client.post('/api/tournament/tid/action', json={'action': 'undq_player'})

    assert resp.status == 400


@pytest.mark.asyncio
async def test_action_undq_player_calls_undisqualify(aiohttp_client):
    t = make_tournament()
    bot, tm = make_tm_bot(t)
    client = await authed_client(aiohttp_client, bot)

    await client.post('/api/tournament/tid/action', json={'action': 'undq_player', 'discord_id': 100})

    tm.undisqualify_player.assert_awaited_once_with(100)


@pytest.mark.asyncio
async def test_action_revert_tournament(aiohttp_client):
    t = make_tournament()
    bot, tm = make_tm_bot(t)
    client = await authed_client(aiohttp_client, bot)

    resp = await client.post('/api/tournament/tid/action', json={'action': 'revert_tournament'})

    assert resp.status == 200
    tm.revert_tournament.assert_awaited_once()


@pytest.mark.asyncio
async def test_action_post_results(aiohttp_client):
    t = make_tournament()
    bot, tm = make_tm_bot(t)
    client = await authed_client(aiohttp_client, bot)

    resp = await client.post('/api/tournament/tid/action', json={'action': 'post_results'})

    assert resp.status == 200
    tm.post_final_results.assert_awaited_once()


@pytest.mark.asyncio
async def test_action_unpublish_tournament(aiohttp_client):
    t = make_tournament()
    bot, tm = make_tm_bot(t)
    bot.dh.unpublish_tournament = AsyncMock()
    client = await authed_client(aiohttp_client, bot)

    resp = await client.post('/api/tournament/tid/action', json={'action': 'unpublish_tournament'})

    assert resp.status == 200
    tm.remove_tournament_from_discord.assert_awaited_once()
    bot.dh.unpublish_tournament.assert_awaited_once_with(t['_id'])


@pytest.mark.asyncio
async def test_action_call_match_returns_400_when_match_id_missing(aiohttp_client):
    t = make_tournament()
    bot, tm = make_tm_bot(t)
    client = await authed_client(aiohttp_client, bot)

    resp = await client.post('/api/tournament/tid/action', json={'action': 'call_match'})

    assert resp.status == 400


@pytest.mark.asyncio
async def test_action_call_match_returns_400_when_match_not_in_pending(aiohttp_client):
    t = make_tournament()
    bot, tm = make_tm_bot(t)
    tm.format.get_pending_matches = AsyncMock(return_value=[])
    client = await authed_client(aiohttp_client, bot)

    resp = await client.post('/api/tournament/tid/action', json={'action': 'call_match', 'match_id': 99})

    assert resp.status == 400


@pytest.mark.asyncio
async def test_action_call_match_calls_format_call_match(aiohttp_client):
    t = make_tournament()
    bot, tm = make_tm_bot(t)
    match_data = {'match_id': 42, 'player_1': 100, 'player_2': 200}
    tm.format.get_pending_matches = AsyncMock(return_value=[match_data])
    client = await authed_client(aiohttp_client, bot)

    resp = await client.post('/api/tournament/tid/action', json={'action': 'call_match', 'match_id': 42})

    assert resp.status == 200
    tm.format.call_match.assert_awaited_once_with(match_data)


@pytest.mark.asyncio
async def test_action_reopen_lobby_calls_with_string_match_id(aiohttp_client):
    t = make_tournament()
    bot, tm = make_tm_bot(t)
    client = await authed_client(aiohttp_client, bot)

    resp = await client.post('/api/tournament/tid/action', json={'action': 'reopen_lobby', 'match_id': 42})

    assert resp.status == 200
    tm.reopen_lobby.assert_awaited_once_with('42')


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/tournament/{id}/stages
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_add_stages_returns_400_when_codes_missing(aiohttp_client):
    bot = make_bot(tournament=make_tournament())
    client = await authed_client(aiohttp_client, bot)

    resp = await client.post('/api/tournament/tid/stages', json={})

    assert resp.status == 400


@pytest.mark.asyncio
async def test_add_stages_returns_400_for_invalid_code(aiohttp_client):
    bot = make_bot(tournament=make_tournament())
    client = await authed_client(aiohttp_client, bot)

    with patch('web.web_server.validate_stagecode', return_value=None):
        resp = await client.post('/api/tournament/tid/stages', json={'codes': 'INVALID'})

    assert resp.status == 400


@pytest.mark.asyncio
async def test_add_stages_calls_dh_with_valid_codes(aiohttp_client):
    bot = make_bot(tournament=make_tournament())
    client = await authed_client(aiohttp_client, bot)

    with patch('web.web_server.validate_stagecode', side_effect=lambda c: c.upper() if c else None):
        resp = await client.post('/api/tournament/tid/stages', json={'codes': 'ABC,DEF'})

    assert resp.status == 200
    bot.dh.add_stages_to_tournament.assert_awaited_once()
    args = bot.dh.add_stages_to_tournament.call_args[0]
    assert 'ABC' in args[1]
    assert 'DEF' in args[1]


# ═══════════════════════════════════════════════════════════════════════════════
# DELETE /api/tournament/{id}/stages/{code}
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_remove_stage_returns_404_for_unknown_tournament(aiohttp_client):
    bot = make_bot(tournament=None)
    client = await authed_client(aiohttp_client, bot)

    resp = await client.delete('/api/tournament/ghost/stages/ABC')

    assert resp.status == 404


@pytest.mark.asyncio
async def test_remove_stage_calls_dh(aiohttp_client):
    bot = make_bot(tournament=make_tournament())
    client = await authed_client(aiohttp_client, bot)

    resp = await client.delete('/api/tournament/tid/stages/ABC')

    assert resp.status == 200
    bot.dh.remove_stage_from_tournament.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════════════════════
# DELETE /api/tournament/{id}/upload/{image_type}
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_delete_image_returns_400_for_invalid_type(aiohttp_client):
    bot = make_bot(tournament=make_tournament())
    client = await authed_client(aiohttp_client, bot)

    resp = await client.delete('/api/tournament/tid/upload/avatar')

    assert resp.status == 400


@pytest.mark.asyncio
async def test_delete_image_calls_dh_with_none(aiohttp_client):
    bot = make_bot(tournament=make_tournament())
    client = await authed_client(aiohttp_client, bot)

    resp = await client.delete('/api/tournament/tid/upload/banner')

    assert resp.status == 200
    bot.dh.update_tournament_image_path.assert_awaited_once()
    args = bot.dh.update_tournament_image_path.call_args[0]
    assert args[1] == 'banner'
    assert args[2] is None