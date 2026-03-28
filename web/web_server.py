import os
import secrets
import discord
import asyncio
import time
from datetime import datetime, timezone, timedelta
from aiohttp import web
from utils.validate_stagecode import validate_stagecode

from web.auth import (
    require_auth,
    handle_login,
    handle_oauth_redirect,
    handle_oauth_callback,
    handle_logout,
)

# token_store maps token -> { tournament_id, challonge_url, expires_at }
token_store: dict[str, dict] = {}

TOKEN_EXPIRY_MINUTES = 30

def generate_token(tournament_id: str, challonge_url: str) -> str:
    """Generate a one-time access token for a tournament seeding session."""
    token = secrets.token_urlsafe(32)
    token_store[token] = {
        'tournament_id': tournament_id,
        'challonge_url': challonge_url,
        'expires_at': datetime.now(timezone.utc) + timedelta(minutes=TOKEN_EXPIRY_MINUTES)
    }
    return token


def validate_token(token: str) -> dict | None:
    """Return token data if valid and not expired, otherwise None."""
    data = token_store.get(token)
    if not data:
        return None
    if datetime.now(timezone.utc) > data['expires_at']:
        del token_store[token]
        return None
    return data


# ─── Seeding routes (token-auth) ─────────────────────────────────────────────

async def handle_seeding_page(request: web.Request) -> web.Response:
    token = request.query.get('token')
    token_data = validate_token(token) if token else None
    if not token or not token_data:
        return web.Response(
            status=403,
            text="Invalid or expired token. Please generate a new link from Discord."
        )

    bot = request.app['bot']
    tournament = await bot.dh.get_tournament_by_id(token_data['tournament_id'])
    tournament_name = tournament['name'] if tournament else 'Tournament Seeding'

    template_path = os.path.join(os.path.dirname(__file__), 'templates', 'seeding.html')
    with open(template_path, 'r', encoding='utf-8') as f:
        html = f.read()

    html = html.replace('__TOKEN__', token)
    html = html.replace('__TOURNAMENT_NAME__', tournament_name)
    return web.Response(content_type='text/html', charset='utf-8', text=html)


async def handle_get_participants(request: web.Request) -> web.Response:
    """Return participants for the tournament associated with the token, including Discord avatars."""
    token = request.query.get('token')
    token_data = validate_token(token) if token else None
    if not token_data:
        return web.json_response({'error': 'Invalid or expired token'}, status=403)

    bot = request.app['bot']
    challonge_handler = request.app['challonge_handler_factory'](token_data['challonge_url'])

    try:
        participants = await challonge_handler.get_participants(token_data['challonge_url'])
        participants_sorted = sorted(participants, key=lambda p: p.get('seed') or 999)

        tournament = await bot.dh.get_tournament_by_id(token_data['tournament_id'])
        challonge_to_discord = {
            int(challonge_id): int(discord_id)
            for discord_id, challonge_id in tournament.get('entrants', {}).items()
        }

        result = []
        for p in participants_sorted:
            discord_user_id = challonge_to_discord.get(p['id'])
            avatar_url = None
            if discord_user_id:
                member = bot.guild.get_member(discord_user_id)
                if member:
                    avatar_url = str(member.display_avatar.url)
            result.append({
                'id':         p['id'],
                'name':       p['name'],
                'seed':       p.get('seed'),
                'avatar_url': avatar_url,
            })

        return web.json_response(result)

    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)


async def handle_update_seed(request: web.Request) -> web.Response:
    """Update a single participant's seed."""
    token = request.query.get('token')
    token_data = validate_token(token) if token else None
    if not token_data:
        return web.json_response({'error': 'Invalid or expired token'}, status=403)

    try:
        body = await request.json()
        participant_id = body['participant_id']
        new_seed = int(body['seed'])
    except (KeyError, ValueError, Exception):
        return web.json_response({'error': 'Invalid request body'}, status=400)

    challonge_handler = request.app['challonge_handler_factory'](token_data['challonge_url'])
    try:
        await challonge_handler.update_seed(
            token_data['challonge_url'],
            participant_id,
            new_seed
        )
        return web.json_response({'ok': True})
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)


# ─── Main dashboard (session-auth) ───────────────────────────────────────────

@require_auth
async def handle_dashboard(request: web.Request) -> web.Response:
    """Serve the main TO dashboard."""
    session = request['session']

    template_path = os.path.join(os.path.dirname(__file__), 'templates', 'dashboard.html')
    with open(template_path, 'r', encoding='utf-8') as f:
        html = f.read()

    html = html.replace('__USERNAME__', session['discord_username'])
    html = html.replace('__AVATAR_URL__', session.get('avatar') or '')
    return web.Response(content_type='text/html', charset='utf-8', text=html)


@require_auth
async def handle_get_tournaments(request: web.Request) -> web.Response:
    """Return active tournaments and summary stats for the dashboard."""
    bot = request.app['bot']

    tournaments = await bot.dh.get_active_events()

    total_players = 0
    total_lobbies = 0
    tournament_list = []

    for t in tournaments:
        tid = t['_id']
        entrant_count = len(t.get('entrants', {}))
        total_players += entrant_count

        lobbies = await bot.dh.get_active_lobbies(tid)
        lobby_count = len(lobbies) if lobbies else 0
        total_lobbies += lobby_count

        tournament_list.append({
            'id':                str(tid),
            'name':              t.get('name', ''),
            'format':            t.get('format', ''),
            'state':             t.get('state', ''),
            'date':              t.get('date', ''),
            'entrant_count':     entrant_count,
            'lobby_count':       lobby_count,
            'registration_open': t.get('registration_open', False),
            'debug':             t.get('debug', False),
            'banner_url':        t.get('banner_url'),
            'logo_url':          t.get('logo_url'),
        })

    STATE_ORDER = {'active': 0, 'checkin': 1, 'registration': 2, 'setup': 3, 'initialize': 4}
    tournament_list.sort(key=lambda t: (t['debug'], STATE_ORDER.get(t['state'], 9)))

    return web.json_response({
        'tournaments':  tournament_list,
        'active_count': sum(1 for t in tournament_list if t['state'] == 'active'),
        'lobby_count':  total_lobbies,
        'player_count': total_players,
    })


@require_auth
async def handle_create_tournament(request: web.Request) -> web.Response:
    """Create a new tournament from the web dashboard."""
    session = request['session']
    bot     = request.app['bot']

    try:
        body = await request.json()
    except Exception:
        return web.json_response({'error': 'Invalid JSON body'}, status=400)

    name = (body.get('name') or '').strip()
    fmt  = (body.get('format') or '').strip()

    VALID_FORMATS = {'single elimination', 'double elimination', 'swiss', 'swiss filter'}

    if not name:
        return web.json_response({'error': 'Tournament name is required'}, status=400)
    if fmt not in VALID_FORMATS:
        return web.json_response({'error': f'Invalid format: {fmt!r}'}, status=400)

    approved_registration = bool(body.get('approved_registration', False))
    randomized_stagelist  = bool(body.get('randomized_stagelist', False))
    display_entrants      = bool(body.get('display_entrants', False))
    round_limit           = max(1, min(int(body.get('round_limit', 8)), 99))
    debug                 = bool(body.get('debug', False))
    ranked_reporting      = bool(body.get('ranked_reporting', False))
    teams_mode = bool(body.get('teams_mode', False))

    tournament_data = {
        'name':                  name,
        'date':                  body.get('date', ''),
        'organizer':             session['discord_user_id'],
        'format':                fmt,
        'approved_registration': approved_registration,
        'randomized_stagelist':  randomized_stagelist,
        'display_entrants':      display_entrants,
        'round_limit':           round_limit,
        'ranked_reporting':      ranked_reporting,
        'debug':                 debug,
        'teams_mode':            teams_mode,
    }

    try:
        result = await bot.th.create_tournament_record(tournament_data)
        if not result:
            return web.json_response({'error': 'Tournament name already exists'}, status=400)
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

    return web.json_response({'ok': True, 'name': name})


# ─── Event dashboard (session-auth) ──────────────────────────────────────────

@require_auth
async def handle_event_dashboard(request: web.Request) -> web.Response:
    """Serve the per-tournament management dashboard."""
    session       = request['session']
    tournament_id = request.match_info['tournament_id']
    bot           = request.app['bot']

    tournament = await bot.dh.get_tournament_by_id(tournament_id)
    if not tournament:
        raise web.HTTPNotFound(reason='Tournament not found')

    template_path = os.path.join(os.path.dirname(__file__), 'templates', 'event_dashboard.html')
    with open(template_path, 'r', encoding='utf-8') as f:
        html = f.read()

    html = html.replace('__TOURNAMENT_ID__',   tournament_id)
    html = html.replace('__TOURNAMENT_NAME__', tournament.get('name', ''))
    html = html.replace('__USERNAME__',        session['discord_username'])
    html = html.replace('__AVATAR_URL__',      session.get('avatar') or '')
    return web.Response(content_type='text/html', charset='utf-8', text=html)


@require_auth
async def handle_get_tournament(request: web.Request) -> web.Response:
    """Return full tournament data for the event dashboard."""
    tournament_id = request.match_info['tournament_id']
    bot           = request.app['bot']

    tournament = await bot.dh.get_tournament_by_id(tournament_id)
    if not tournament:
        return web.json_response({'error': 'Tournament not found'}, status=404)

    fmt            = tournament.get('format', '')
    is_bracket_fmt = fmt in ('single elimination', 'double elimination', 'swiss filter')

    # ── Parallel fetches ──────────────────────────────────────────────────────

    async def _fetch_challonge_participants():
        if not (is_bracket_fmt and 'challonge_data' in tournament):
            return []
        try:
            ch = bot.th.tournaments.get(tournament['_id'])
            ch_handler = (
                ch.format.ch
                if ch and hasattr(ch, 'format') and ch.format and hasattr(ch.format, 'ch')
                else None
            )
            if ch_handler is None:
                from tournaments.challonge_handler import ChallongeHandler
                ch_handler = ChallongeHandler(tournament['challonge_data']['url'])
            return await ch_handler.get_participants(tournament['challonge_data']['url'])
        except Exception:
            return []

    async def _fetch_swiss():
        if fmt not in ('swiss', 'swiss filter'):
            return None
        return await bot.dh.get_swiss_event_by_tournament(tournament['_id'])

    async def _fetch_registration_requests():
        if not tournament.get('config', {}).get('approved_registration'):
            return []
        return await bot.dh.get_registration_requests(tournament['_id'])

    raw_lobbies, participants, swiss_event, request_ids = await asyncio.gather(
        bot.dh.get_all_lobbies(tournament['_id']),
        _fetch_challonge_participants(),
        _fetch_swiss(),
        _fetch_registration_requests(),
    )

    is_teams = tournament.get('config', {}).get('teams_mode', False)

    # Resolve lobby player IDs — in teams mode these are "p1_p2" strings
    lobby_player_ids = []
    for l in (raw_lobbies or []):
        for uid in l.get('players', []):
            uid_str = str(uid)
            if '_' in uid_str:
                try:
                    p1, p2 = uid_str.split('_')
                    lobby_player_ids.extend([p1, p2])
                except ValueError:
                    pass
            else:
                lobby_player_ids.append(uid_str)

    # Resolve entrant IDs — in teams mode keys are "p1_p2" strings
    entrant_ids = []
    for key in tournament.get('entrants', {}).keys():
        key_str = str(key)
        if '_' in key_str:
            try:
                p1, p2 = key_str.split('_')
                entrant_ids.extend([p1, p2])
            except ValueError:
                pass
        else:
            entrant_ids.append(key_str)

    all_ids  = list(set(entrant_ids + lobby_player_ids))
    user_map = await bot.dh.get_users_bulk(all_ids)

    # ── Seed data ─────────────────────────────────────────────────────────────

    seed_by_discord:         dict[str, int | None] = {}
    challonge_id_by_discord: dict[str, int | None] = {}
    if is_bracket_fmt:
        if 'challonge_data' in tournament:
            challonge_to_discord = {
                int(cid): str(did)
                for did, cid in tournament.get('entrants', {}).items()
                if cid is not None
            }
            for p in participants:
                discord_id = challonge_to_discord.get(p['id'])
                if discord_id:
                    seed_by_discord[discord_id]         = p.get('seed')
                    challonge_id_by_discord[discord_id] = p['id']
        else:
            native_seeds    = tournament.get('seeds', {})
            entrant_key_set = {str(k) for k in tournament.get('entrants', {}).keys()}
            for discord_id_str, seed in native_seeds.items():
                key_str = str(discord_id_str)
                if key_str in entrant_key_set:
                    seed_by_discord[key_str] = seed

    # ── Entrants ──────────────────────────────────────────────────────────────

    entrants = []
    for key_str in tournament.get('entrants', {}).keys():
        key_str = str(key_str)
        if '_' in key_str:
            # Teams mode — show team name
            try:
                p1, p2 = key_str.split('_')
                u1 = user_map.get(p1)
                u2 = user_map.get(p2)
                n1 = u1['name'] if u1 else p1
                n2 = u2['name'] if u2 else p2
                entrants.append({
                    'discord_id': key_str,
                    'name':       f"{n1} / {n2}",
                    'seed':       None,
                    'challonge_id': tournament.get('entrants', {}).get(key_str),
                    'avatar_url': None,
                })
            except ValueError:
                pass
        else:
            user = user_map.get(key_str)
            entrants.append({
                'discord_id':   key_str,
                'name':         user['name'] if user else key_str,
                'seed':         seed_by_discord.get(key_str),
                'challonge_id': challonge_id_by_discord.get(key_str),
                'avatar_url':   user.get('avatar_url') if user else None,
            })
    if is_bracket_fmt:
        entrants.sort(key=lambda e: e['seed'] if e['seed'] is not None else 9999)

    # ── Lobbies ───────────────────────────────────────────────────────────────

    lobbies = []
    for l in (raw_lobbies or []):
        player_names = []
        player_ids   = []
        for uid in l.get('players', []):
            uid_str = str(uid)
            if '_' in uid_str:
                try:
                    p1, p2 = uid_str.split('_')
                    u1 = user_map.get(p1)
                    u2 = user_map.get(p2)
                    n1 = u1['name'] if u1 else p1
                    n2 = u2['name'] if u2 else p2
                    player_names.append(f"{n1} / {n2}")
                    player_ids.append(uid_str)
                except ValueError:
                    player_names.append(uid_str)
                    player_ids.append(uid_str)
            else:
                user = user_map.get(uid_str)
                player_names.append(user['name'] if user else uid_str)
                player_ids.append(uid_str)

        # Resolve winner name from results[0] if present
        winner_id  = None
        winner_name = None
        results = l.get('results', [])
        if results:
            raw_winner = results[0]
            uid_str = str(raw_winner)
            if '_' in uid_str:
                try:
                    p1, p2 = uid_str.split('_')
                    u1 = user_map.get(p1)
                    u2 = user_map.get(p2)
                    n1 = u1['name'] if u1 else p1
                    n2 = u2['name'] if u2 else p2
                    winner_name = f"{n1} / {n2}"
                    winner_id = uid_str
                except ValueError:
                    pass
            else:
                try:
                    uid_str_w = str(int(raw_winner))
                    wu = user_map.get(uid_str_w)
                    winner_name = wu['name'] if wu else uid_str_w
                    winner_id = uid_str_w
                except (ValueError, TypeError):
                    pass

        lobbies.append({
            'match_id':     str(l.get('match_id')),
            'lobby_name':   l.get('lobby_name', ''),
            'state':        l.get('state', ''),
            'player_names': player_names,
            'player_ids':   player_ids,
            'round':        l.get('round'),
            'winner_id':    winner_id,
            'winner_name':  winner_name,
        })

    # ── Stagelist ─────────────────────────────────────────────────────────────

    stagelist   = []
    stage_codes = tournament.get('stagelist', [])
    if stage_codes:
        stages_bulk = await bot.dh.get_stages_from_list(stage_codes)
        stage_map   = {s['code']: s for s in (stages_bulk or [])}
        for code in stage_codes:
            s = stage_map.get(code)
            stagelist.append({
                'code': code,
                'name': s.get('name', code) if s else code,
            })

    # ── Swiss data ────────────────────────────────────────────────────────────

    tm = bot.th.tournaments.get(tournament['_id'])
    swiss_data = None
    if swiss_event and tm and tm.format:
        swiss_data = await tm.format.get_dashboard_state()
    elif swiss_event:
        # Fallback if tm not loaded (shouldn't happen during active events)
        players           = swiss_event.get('players', {})
        active_matches    = sum(
            1 for p in players.values()
            if p.get('active_match_id') is not None and not p.get('dropped')
        ) // 2
        players_remaining = sum(1 for p in players.values() if not p.get('dropped'))
        current_round     = swiss_event.get('current_round', 0)
        round_limit       = swiss_event.get('round_limit', tournament.get('round_limit', 8))
        swiss_data = {
            'current_round':      current_round,
            'round_limit':        round_limit,
            'active_matches':     active_matches,
            'players_remaining':  players_remaining,
            'round_ready':        False,  # Safe default when TM not loaded
            'final_round_active': current_round >= round_limit,
        }

    # ── autocall / hold_when_ready (Challonge formats only) ──────────────────

    autocall_matches = getattr(tm.format, 'autocall_matches', False) if tm and tm.format else False

    # ── Registration requests ─────────────────────────────────────────────────

    registration_requests = []
    for rid in (request_ids or []):
        user = user_map.get(str(rid)) or await bot.dh.get_user(user_id=int(rid))
        registration_requests.append({
            'discord_id': str(rid),
            'name':       user['name'] if user else str(rid),
            'avatar_url': user.get('avatar_url') if user else None,
        })

    return web.json_response({
        'id':                    str(tournament['_id']),
        'name':                  tournament.get('name', ''),
        'format':                fmt,
        'state':                 tournament.get('state', ''),
        'date':                  tournament.get('date', ''),
        'registration_open':     tournament.get('registration_open', False),
        'entrant_count':         len(entrants),
        'checkin_count':         len(tournament.get('checked_in', [])),
        'lobby_count':           len(lobbies),
        'entrants':              entrants,
        'checked_in':            [str(x) for x in tournament.get('checked_in', [])],
        'dqs':                   [str(x) for x in tournament.get('dqs', [])],
        'lobbies':               lobbies,
        'stagelist':             stagelist,
        'config':                tournament.get('config', {}),
        'swiss':                 swiss_data,
        'autocall_matches':      autocall_matches,
        'debug':                 tournament.get('debug', False),
        'stagelist_published':   tournament.get('stagelist_published', False),
        'stagelist_ready':       (
            tournament.get('stagelist_published', False)
            or (
                fmt in ('swiss')
                and tournament.get('config', {}).get('randomized_stagelist', False)
                and bool(tournament.get('stagelist'))
            )
        ),
        'registration_requests': registration_requests,
        'banner_url':            tournament.get('banner_url'),
        'logo_url':              tournament.get('logo_url'),
        'ranked_compatible':     getattr(tm.format, 'ranked_compatible', False) if tm and tm.format else False,
        'ranked_reporting':      tournament.get('config', {}).get('ranked_reporting', False),
    })


@require_auth
async def handle_tournament_action(request: web.Request) -> web.Response:
    """Execute a control action on a tournament."""
    tournament_id = request.match_info['tournament_id']
    bot           = request.app['bot']

    try:
        body = await request.json()
    except Exception:
        return web.json_response({'error': 'Invalid JSON'}, status=400)

    action = body.get('action', '').strip()
    if not action:
        return web.json_response({'error': 'action is required'}, status=400)

    tournament = await bot.dh.get_tournament_by_id(tournament_id)
    if not tournament:
        return web.json_response({'error': 'Tournament not found'}, status=404)

    fmt = tournament.get('format', '')
    tm  = bot.th.tournaments.get(tournament['_id'])

    VALID_ACTIONS = {
        'progress', 'open_registration', 'close_registration',
        'ping_checkin', 'next_round',
        'dq_player', 'undq_player',
        'force_advance', 'update_config',
        'reset_match', 'delete_tournament',
        'publish_stagelist',
        'approve_registration',
        'deny_registration',
        'seed_by_rank',
        'randomize_seeds',
        'revert_tournament',
        'call_match',
        'hold_match',
        'call_all_matches',
        'set_autocall',
        'start_held_match',
        'reset_lobby',
        'post_results',
        'refresh_event_info',
        'toggle_hold_when_ready',
        'unpublish_tournament',
        'reopen_lobby',
    }
    if action not in VALID_ACTIONS:
        return web.json_response({'error': f'Unknown action: {action!r}'}, status=400)

    def need_tm():
        if not tm:
            raise ValueError('Tournament manager not loaded — bot may need restart')

    try:
        if action == 'progress':
            need_tm()
            await tm.progress_tournament()

        elif action == 'open_registration':
            need_tm()
            await tm.open_registration()

        elif action == 'close_registration':
            need_tm()
            await tm.close_registration()

        elif action == 'ping_checkin':
            need_tm()
            result = await tm.ping_checkin()
            if not result:
                return web.json_response(
                    {'error': 'Ping limit reached or fewer than 10 players remain unchecked'},
                    status=400
                )

        elif action == 'next_round':
            need_tm()
            if fmt not in ('swiss', 'swiss filter'):
                return web.json_response({'error': 'next_round is only valid for Swiss'}, status=400)
            if not tm.format:
                return web.json_response({'error': 'Format not initialised'}, status=500)
            if tm.format.manager._get_pairing_lock().locked():
                return web.json_response({'error': 'Round is already being started'}, status=409)
            await tm.format.manager.run_pairing_cycle()

        elif action == 'dq_player':
            need_tm()
            discord_id = body.get('discord_id')
            if discord_id is None:
                return web.json_response({'error': 'discord_id is required'}, status=400)
            discord_id = int(discord_id)
            result = await tm.disqualify_player(discord_id)
            if result is False:
                return web.json_response(
                    {'error': 'Player not registered or tournament is not active'},
                    status=400
                )

        elif action == 'undq_player':
            need_tm()
            discord_id = body.get('discord_id')
            if discord_id is None:
                return web.json_response({'error': 'discord_id is required'}, status=400)
            discord_id = int(discord_id)
            await tm.undisqualify_player(discord_id)

        elif action == 'force_advance':
            need_tm()
            match_id     = body.get('match_id')
            target_state = body.get('target_state', '')
            winner_id    = body.get('winner_id')

            if match_id is None or not target_state:
                return web.json_response(
                    {'error': 'match_id and target_state are required'}, status=400
                )

            match_id_str = str(match_id)
            match_lobby  = next(
                (lobby for key, lobby in tm.lobbies.items() if str(key) == match_id_str),
                None
            )
            if not match_lobby:
                return web.json_response(
                    {'error': 'Lobby not found in memory — bot may have restarted'},
                    status=404
                )

            if target_state == 'winner':
                lobby_data = await match_lobby.get_lobby()
                if lobby_data.get('state') == 'finished':
                    return web.json_response(
                        {'error': 'Lobby is already finished — cannot force-advance again'},
                        status=400
                    )

                # Resolve winner_id to the exact key stored in the swiss event,
                # since large Discord IDs can lose precision passing through JS JSON.
                # We match by string comparison of integer values.
                if winner_id is not None:
                    fmt = tournament.get('format', '')
                    if fmt in ('swiss', 'swiss filter'):
                        swiss_event = await bot.dh.get_swiss_event_by_tournament(tournament['_id'])
                        if swiss_event:
                            stored_keys = list(swiss_event.get('players', {}).keys())
                            try:
                                winner_id = next(
                                    k for k in stored_keys
                                    if int(k) == int(winner_id)
                                )
                            except (StopIteration, ValueError):
                                pass  # fall through with original value

                await match_lobby.force_advance(target_state, winner_id=winner_id)
            else:
                await match_lobby.force_advance(target_state, winner_id=winner_id)

        elif action == 'update_config':
            updates = {}
            if 'name' in body:
                name = body['name'].strip()
                if not name:
                    return web.json_response({'error': 'Name cannot be empty'}, status=400)
                updates['name'] = name
            if 'date' in body:
                updates['date'] = body['date'].strip()
            for key in ('approved_registration', 'randomized_stagelist', 'display_entrants', 'ranked_reporting'):
                if key in body:
                    updates[f'config.{key}'] = bool(body[key])
            if updates:
                await bot.dh.edit_tournament_config(tournament['_id'], **updates)
                if tm and 'config.display_entrants' in updates:
                    await tm.edit_event_info()

        elif action == 'delete_tournament':
            need_tm()
            await tm.delete_tournament()
            return web.json_response({'ok': True})

        elif action == 'publish_stagelist':
            need_tm()
            await tm.publish_stagelist()

        elif action == 'approve_registration':
            need_tm()
            discord_id = int(body.get('discord_id', 0))
            if not discord_id:
                return web.json_response({'error': 'discord_id is required'}, status=400)
            await bot.dh.remove_registration_request(tournament['_id'], discord_id)
            await tm.register_player_direct(discord_id)
            member = bot.guild.get_member(discord_id)
            if member:
                try:
                    embed = discord.Embed(
                        title='Registration Approved',
                        description=f"Your registration for **{tournament['name']}** has been approved.",
                        color=discord.Color.green()
                    )
                    await member.send(embed=embed)
                except discord.Forbidden:
                    pass

        elif action == 'deny_registration':
            need_tm()
            discord_id = int(body.get('discord_id', 0))
            reason     = body.get('reason', '').strip()
            if not discord_id:
                return web.json_response({'error': 'discord_id is required'}, status=400)
            await bot.dh.remove_registration_request(tournament['_id'], discord_id)
            member = bot.guild.get_member(discord_id)
            if member:
                try:
                    desc = f"Your registration for **{tournament['name']}** has been denied."
                    if reason:
                        desc += f"\n**Reason:** {reason}"
                    embed = discord.Embed(
                        title='Registration Denied', description=desc, color=discord.Color.red()
                    )
                    await member.send(embed=embed)
                except discord.Forbidden:
                    pass

        elif action == 'randomize_seeds':
            import random
            entrant_ids = list(tournament.get('entrants', {}).keys())
            shuffled    = random.sample(entrant_ids, len(entrant_ids))
            seeds       = {int(did): i + 1 for i, did in enumerate(shuffled)}
            await bot.dh.update_all_seeds(tournament['_id'], seeds)

        elif action == 'seed_by_rank':
            entrant_ids = set(int(did) for did in tournament.get('entrants', {}).keys())
            leaderboard = await bot.uchranked_api.get_leaderboard(10000)
            elo_map = {}
            for p in leaderboard:
                try:
                    discord_id = int(p['discord_id'])
                    if discord_id in entrant_ids:
                        elo_map[discord_id] = p['elo']
                except (ValueError, TypeError, KeyError):
                    continue
            for discord_id in entrant_ids:
                if discord_id not in elo_map:
                    elo_map[discord_id] = 0
            sorted_ids = sorted(elo_map.keys(), key=lambda uid: elo_map[uid], reverse=True)
            seeds      = {discord_id: i + 1 for i, discord_id in enumerate(sorted_ids)}
            await bot.dh.update_all_seeds(tournament['_id'], seeds)

        elif action == 'revert_tournament':
            need_tm()
            await tm.revert_tournament()

        elif action == 'call_match':
            need_tm()
            match_id = body.get('match_id')
            if match_id is None:
                return web.json_response({'error': 'match_id is required'}, status=400)
            pending    = await tm.format.get_pending_matches()
            match_data = next((m for m in pending if m['match_id'] == match_id), None)
            if not match_data:
                return web.json_response({'error': 'Match not found or already called'}, status=400)
            await tm.format.call_match(match_data)

        elif action == 'hold_match':
            need_tm()
            match_id = body.get('match_id')
            if match_id is None:
                return web.json_response({'error': 'match_id is required'}, status=400)
            pending    = await tm.format.get_pending_matches()
            match_data = next((m for m in pending if m['match_id'] == match_id), None)
            if not match_data:
                return web.json_response({'error': 'Match not found or already called'}, status=400)
            await tm.format.call_match(match_data, hold_match=True)

        elif action == 'call_all_matches':
            need_tm()
            await tm.format.call_matches()

        elif action == 'set_autocall':
            need_tm()
            enabled = bool(body.get('enabled', False))
            if not hasattr(tm.format, 'autocall_matches'):
                return web.json_response({'error': 'autocall not supported for this format'}, status=400)
            tm.format.autocall_matches = enabled
            if enabled:
                await tm.format.call_matches()

        elif action == 'start_held_match':
            need_tm()
            match_id = body.get('match_id')
            if match_id is None:
                return web.json_response({'error': 'match_id is required'}, status=400)
            match_lobby = tm.lobbies.get(match_id)
            if not match_lobby:
                return web.json_response({'error': 'Lobby not found'}, status=404)
            await match_lobby.start_match()

        elif action == 'reset_lobby':
            need_tm()
            match_id = body.get('match_id')
            if match_id is None:
                return web.json_response({'error': 'match_id is required'}, status=400)
            await tm.reset_lobby_to_active(match_id)
            # invalidate_pending_cache now lives on the format
            if hasattr(tm.format, 'invalidate_pending_cache'):
                tm.format.invalidate_pending_cache()

        elif action == 'post_results':
            need_tm()
            await tm.post_final_results()

        elif action == 'refresh_event_info':
            need_tm()
            await tm.edit_event_info()

        elif action == 'toggle_hold_when_ready':
            need_tm()
            match_id = body.get('match_id')
            if match_id is None:
                return web.json_response({'error': 'match_id is required'}, status=400)
            if not hasattr(tm.format, 'toggle_hold_when_ready'):
                return web.json_response({'error': 'hold_when_ready not supported for this format'}, status=400)
            is_flagged = tm.format.toggle_hold_when_ready(match_id)
            return web.json_response({'ok': True, 'flagged': is_flagged})

        elif action == 'unpublish_tournament':
            need_tm()
            await tm.remove_tournament_from_discord()
            await bot.dh.unpublish_tournament(tournament['_id'])

        elif action == 'reopen_lobby':
            need_tm()
            match_id_str = str(body.get('match_id'))
            await tm.reopen_lobby(match_id_str)
    except ValueError as e:
        return web.json_response({'error': str(e)}, status=400)
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

    return web.json_response({'ok': True})


@require_auth
async def handle_add_stages(request: web.Request) -> web.Response:
    """Add one or more stages to a tournament by code."""
    tournament_id = request.match_info['tournament_id']
    bot           = request.app['bot']

    try:
        body = await request.json()
    except Exception:
        return web.json_response({'error': 'Invalid JSON'}, status=400)

    raw = body.get('codes', '').strip()
    if not raw:
        return web.json_response({'error': 'codes is required'}, status=400)

    tournament = await bot.dh.get_tournament_by_id(tournament_id)
    if not tournament:
        return web.json_response({'error': 'Tournament not found'}, status=404)

    valid   = []
    invalid = []
    for part in raw.split(','):
        code = validate_stagecode(part.strip())
        if code:
            valid.append(code)
        else:
            invalid.append(part.strip())

    if invalid:
        return web.json_response(
            {'error': f'Invalid stage code(s): {", ".join(invalid)}'},
            status=400
        )

    await bot.dh.add_stages_to_tournament(tournament['_id'], valid)
    return web.json_response({'ok': True, 'added': valid})


@require_auth
async def handle_remove_stage(request: web.Request) -> web.Response:
    """Remove a stage from a tournament by code."""
    tournament_id = request.match_info['tournament_id']
    code          = request.match_info['code'].upper().strip()
    bot           = request.app['bot']

    tournament = await bot.dh.get_tournament_by_id(tournament_id)
    if not tournament:
        return web.json_response({'error': 'Tournament not found'}, status=404)

    await bot.dh.remove_stage_from_tournament(tournament['_id'], code)
    return web.json_response({'ok': True})


@require_auth
async def handle_set_seed(request: web.Request) -> web.Response:
    """Update entrant seeds — Challonge or native depending on tournament type."""
    tournament_id = request.match_info['tournament_id']
    bot           = request.app['bot']

    try:
        body  = await request.json()
        seeds = body.get('seeds')
    except Exception:
        return web.json_response({'error': 'Invalid JSON'}, status=400)

    if not seeds or not isinstance(seeds, list):
        return web.json_response({'error': 'seeds must be a non-empty list'}, status=400)

    tournament = await bot.dh.get_tournament_by_id(tournament_id)
    if not tournament:
        return web.json_response({'error': 'Tournament not found'}, status=404)

    fmt = tournament.get('format', '')
    if fmt not in ('single elimination', 'double elimination', 'swiss filter'):
        return web.json_response({'error': 'Seeding only available for DE/SE/Swiss Filter'}, status=400)

    if 'challonge_data' in tournament:
        try:
            ch = bot.th.tournaments.get(tournament['_id'])
            ch_handler = (
                ch.format.ch
                if ch and hasattr(ch, 'format') and ch.format and hasattr(ch.format, 'ch')
                else None
            )
            if ch_handler is None:
                from tournaments.challonge_handler import ChallongeHandler
                ch_handler = ChallongeHandler(tournament['challonge_data']['url'])
            for entry in seeds:
                try:
                    challonge_id = int(entry['challonge_id'])
                    seed         = int(entry['seed'])
                except (KeyError, ValueError, TypeError):
                    continue
                await ch_handler.update_seed(tournament['challonge_data']['url'], challonge_id, seed)
        except Exception as e:
            return web.json_response({'error': str(e)}, status=502)
    else:
        for entry in seeds:
            try:
                discord_id = int(entry['discord_id'])
                seed       = int(entry['seed'])
            except (KeyError, ValueError, TypeError):
                continue
            await bot.dh.update_entrant_seed(tournament['_id'], discord_id, seed)

    return web.json_response({'ok': True})


@require_auth
async def handle_get_bracket(request: web.Request) -> web.Response:
    tournament_id = request.match_info['tournament_id']
    bot           = request.app['bot']

    tournament = await bot.dh.get_tournament_by_id(tournament_id)
    if not tournament:
        return web.json_response({'error': 'Tournament not found'}, status=404)

    fmt = tournament.get('format', '')

    # ── Swiss: return current-round matches as a flat bracket ─────────────────
    if fmt == 'swiss':
        swiss_event = await bot.dh.get_swiss_event_by_tournament(tournament['_id'])
        if not swiss_event:
            return web.json_response({'format': fmt, 'matches': [], 'round': 0})

        current_round = swiss_event.get('current_round', 0)
        all_matches   = swiss_event.get('matches', [])

        # Collect all player IDs referenced in any match this round
        round_matches = [m for m in all_matches if m.get('round_number') == current_round]
        player_ids    = list({str(m['player_1']) for m in round_matches} |
                             {str(m['player_2']) for m in round_matches})
        user_map      = await bot.dh.get_users_bulk(player_ids) if player_ids else {}

        raw_lobbies   = await bot.dh.get_all_lobbies(tournament['_id'])
        lobby_by_match = {l['match_id']: l for l in (raw_lobbies or [])}

        matches = []
        for m in round_matches:
            p1_id  = str(m['player_1'])
            p2_id  = str(m['player_2'])
            u1     = user_map.get(p1_id)
            u2     = user_map.get(p2_id)
            lobby  = lobby_by_match.get(m['match_id'])

            winner_id   = m.get('winner')
            winner_disc = str(winner_id) if winner_id else None

            matches.append({
                'match_id':          m['match_id'],
                'round':             current_round,
                'bracket':           '',
                'state':             'complete' if m.get('state') == 'finished' else 'open',
                'lobby_state':       lobby['state'] if lobby else None,
                'p1_name':           u1['name'] if u1 else p1_id,
                'p2_name':           u2['name'] if u2 else p2_id,
                'p1_discord_id':     p1_id,
                'p2_discord_id':     p2_id,
                'p1_avatar_url':     u1.get('avatar_url') if u1 else None,
                'p2_avatar_url':     u2.get('avatar_url') if u2 else None,
                'winner_name':       user_map.get(winner_disc, {}).get('name') if winner_disc else None,
                'winner_discord_id': winner_disc,
                'picked_stage':      lobby.get('picked_stage') if lobby else None,
                'prereq_ids':        [],
                'has_lobby':         lobby is not None,
                'hold_when_ready':   False,
            })

        return web.json_response({
            'format':        fmt,
            'matches':       matches,
            'round':         current_round,
            'round_limit':   swiss_event.get('round_limit', 8),
        })

    # ── DE/SE: existing Challonge bracket path ────────────────────────────────

    fmt = tournament.get('format', '')
    if fmt not in ('single elimination', 'double elimination'):
        return web.json_response(
            {'error': 'Bracket view is only available for DE/SE tournaments'},
            status=400
        )

    if 'challonge_data' not in tournament:
        return web.json_response(
            {'error': 'No Challonge bracket linked to this tournament yet'},
            status=400
        )

    challonge_url = tournament['challonge_data']['url']

    is_teams = tournament.get('config', {}).get('teams_mode', False)

    # Build challonge_id → discord_id/team_id map
    # In teams mode, the "discord_id" side is a team_id string like "101_102"
    challonge_to_discord = {}
    for key, challonge_id in tournament.get('entrants', {}).items():
        if challonge_id is None:
            continue
        try:
            challonge_to_discord[int(challonge_id)] = key  # keep as string — may be team_id
        except (ValueError, TypeError):
            pass

    # Build the user_map — resolve individual discord IDs from entrant keys
    individual_ids = []
    for key in tournament.get('entrants', {}).keys():
        key_str = str(key)
        if '_' in key_str:
            try:
                p1, p2 = key_str.split('_')
                individual_ids.extend([p1, p2])
            except ValueError:
                pass
        else:
            individual_ids.append(key_str)

    user_map = await bot.dh.get_users_bulk(individual_ids)

    discord_to_name   = {}
    discord_to_avatar = {}
    for discord_id_str, user in user_map.items():
        discord_to_name[discord_id_str]   = user['name']
        discord_to_avatar[discord_id_str] = user.get('avatar_url')

    try:
        ch = bot.th.tournaments.get(tournament['_id'])
        if ch and hasattr(ch, 'format') and ch.format and hasattr(ch.format, 'ch'):
            challonge_handler = ch.format.ch
        else:
            from tournaments.challonge_handler import ChallongeHandler
            challonge_handler = ChallongeHandler(challonge_url)

        raw_matches = await challonge_handler.get_all_matches(challonge_url)
    except Exception as e:
        return web.json_response({'error': f'Challonge error: {str(e)}'}, status=502)

    raw_lobbies = await bot.dh.get_all_lobbies(tournament['_id'])
    lobby_by_match = {}
    for l in (raw_lobbies or []):
        mid = l.get('match_id')
        if mid is not None:
            lobby_by_match[mid] = l

    # hold_when_ready now lives on the format
    tm = bot.th.tournaments.get(tournament['_id'])
    hold_when_ready = getattr(tm.format, 'hold_when_ready', set()) if tm and tm.format else set()

    def _resolve_display(key):
        """Given a team_id string or discord_id string, return (name, discord_id_str, avatar)."""
        key_str = str(key)
        if '_' in key_str:
            try:
                p1, p2 = key_str.split('_')
                u1 = discord_to_name.get(p1, p1)
                u2 = discord_to_name.get(p2, p2)
                av = discord_to_avatar.get(p1)
                return f"{u1} / {u2}", key_str, av
            except ValueError:
                return key_str, key_str, None
        else:
            return discord_to_name.get(key_str, f'#{key_str}'), key_str, discord_to_avatar.get(key_str)

    def player_name(challonge_pid):
        if challonge_pid is None:
            return None
        key = challonge_to_discord.get(int(challonge_pid))
        if key is None:
            return f'#{challonge_pid}'
        name, _, _ = _resolve_display(key)
        return name

    def player_discord_id(challonge_pid):
        if challonge_pid is None:
            return None
        key = challonge_to_discord.get(int(challonge_pid))
        return str(key) if key is not None else None

    def player_avatar(challonge_pid):
        if challonge_pid is None:
            return None
        key = challonge_to_discord.get(int(challonge_pid))
        if key is None:
            return None
        _, _, av = _resolve_display(key)
        return av

    matches = []
    for m in raw_matches:
        match_id   = m['id']
        ch_state   = m['state']
        round_num  = m['round']
        p1_cid     = m.get('player1_id')
        p2_cid     = m.get('player2_id')
        winner_cid = m.get('winner_id')

        if fmt == 'double elimination':
            bracket = 'Winners' if round_num > 0 else 'Losers'
        else:
            bracket = ''

        pre_reqs_raw = m.get('prerequisite_match_ids_csv', '')
        if not pre_reqs_raw:
            prereq_ids = []
        elif isinstance(pre_reqs_raw, (int, float)):
            prereq_ids = [int(pre_reqs_raw)]
        else:
            prereq_ids = [int(x) for x in str(pre_reqs_raw).split(',') if x.strip()]

        lobby        = lobby_by_match.get(match_id)
        lobby_state  = lobby['state'] if lobby else None
        picked_stage = lobby.get('picked_stage') if lobby else None

        winner_discord = player_discord_id(winner_cid)
        winner_name    = player_name(winner_cid) if winner_cid else None

        matches.append({
            'match_id':          match_id,
            'round':             round_num,
            'bracket':           bracket,
            'state':             ch_state,
            'lobby_state':       lobby_state,
            'p1_name':           player_name(p1_cid),
            'p2_name':           player_name(p2_cid),
            'p1_discord_id':     player_discord_id(p1_cid),
            'p2_discord_id':     player_discord_id(p2_cid),
            'p1_avatar_url':     player_avatar(p1_cid),
            'p2_avatar_url':     player_avatar(p2_cid),
            'winner_name':       winner_name,
            'winner_discord_id': winner_discord,
            'picked_stage':      picked_stage,
            'prereq_ids':        prereq_ids,
            'has_lobby':         lobby is not None,
            'hold_when_ready':   match_id in hold_when_ready,
        })

    matches.sort(key=lambda m: (
        0 if m['bracket'] == 'Winners' else 1,
        abs(m['round'])
    ))

    return web.json_response({
        'format':  fmt,
        'matches': matches,
    })


@require_auth
async def handle_get_stagelist(request: web.Request) -> web.Response:
    """Return full stage objects for a tournament's stagelist."""
    tournament_id = request.match_info['tournament_id']
    bot           = request.app['bot']

    tournament = await bot.dh.get_tournament_by_id(tournament_id)
    if not tournament:
        return web.json_response({'error': 'Tournament not found'}, status=404)

    codes = tournament.get('stagelist', [])
    if not codes:
        return web.json_response({'stages': []})

    stages = await bot.dh.get_stages_from_list(codes)
    if not stages:
        stages = []
        for code in codes:
            s = await bot.dh.get_stage(code=code)
            if s:
                stages.append(s)

    stage_map = {s['code']: s for s in (stages or [])}
    ordered = []
    for code in codes:
        s = stage_map.get(code)
        ordered.append({
            'code':             code,
            'name':             s.get('name', code) if s else code,
            'imgur_url':        s.get('imgur_url', '') if s else '',
            'mode':             s.get('mode', '') if s else '',
            'tournament_legal': s.get('tournament_legal', True) if s else True,
            'creators':         s.get('creators', []) if s else [],
        })

    return web.json_response({'stages': ordered})


@require_auth
async def handle_browse_stages(request: web.Request) -> web.Response:
    """Return all tournament-legal stages for the browser panel."""
    bot  = request.app['bot']
    mode = request.query.get('mode', None)

    stages = await bot.dh.get_all_levels(tournament_legal=True, mode=mode or None)

    result = []
    for s in (stages or []):
        result.append({
            'code':             s.get('code', ''),
            'name':             s.get('name', ''),
            'imgur_url':        s.get('imgur_url', ''),
            'mode':             s.get('mode', ''),
            'tournament_legal': s.get('tournament_legal', True),
            'creators':         s.get('creators', []),
        })

    return web.json_response({'stages': result})


@require_auth
async def handle_get_pending_matches(request: web.Request) -> web.Response:
    """Return all pending matches that haven't been called yet (Challonge formats only)."""
    tournament_id = request.match_info['tournament_id']
    bot           = request.app['bot']

    tournament = await bot.dh.get_tournament_by_id(tournament_id)
    if not tournament:
        return web.json_response({'error': 'Tournament not found'}, status=404)

    tm = bot.th.tournaments.get(tournament['_id'])
    if not tm:
        return web.json_response({'error': 'Tournament manager not loaded'}, status=500)

    try:
        pending = await tm.format.get_pending_matches()
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

    all_player_ids = list(
        {str(m['player_1_id']) for m in pending} | {str(m['player_2_id']) for m in pending}
    )
    user_map = await bot.dh.get_users_bulk(all_player_ids)

    result = []
    for m in pending:
        p1 = user_map.get(str(m['player_1_id']))
        p2 = user_map.get(str(m['player_2_id']))
        result.append({
            'match_id': m['match_id'],
            'round':    m['round'],
            'bracket':  m['bracket'],
            'p1_name':  p1['name'] if p1 else str(m['player_1_id']),
            'p2_name':  p2['name'] if p2 else str(m['player_2_id']),
        })

    return web.json_response({'pending': result})


@require_auth
async def handle_upload_image(request: web.Request) -> web.Response:
    """Handle banner or logo image upload for a tournament."""
    tournament_id = request.match_info['tournament_id']
    image_type    = request.match_info['image_type']  # 'banner' or 'logo'
    bot           = request.app['bot']

    if image_type not in ('banner', 'logo'):
        return web.json_response({'error': 'Invalid image type'}, status=400)

    tournament = await bot.dh.get_tournament_by_id(tournament_id)
    if not tournament:
        return web.json_response({'error': 'Tournament not found'}, status=404)

    try:
        reader = await request.multipart()
        field  = await reader.next()
        if not field or field.name != 'image':
            return web.json_response({'error': 'No image field in request'}, status=400)

        data = b''
        while True:
            chunk = await field.read_chunk()
            if not chunk:
                break
            data += chunk

        if not data:
            return web.json_response({'error': 'Empty file'}, status=400)

        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(data))
            img.verify()
            img = Image.open(io.BytesIO(data))

            max_dims = (1920, 480) if image_type == 'banner' else (512, 512)
            img.thumbnail(max_dims, Image.LANCZOS)

            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')

            out = io.BytesIO()
            img.save(out, format='JPEG', quality=85, optimize=True)
            data = out.getvalue()
        except Exception as e:
            return web.json_response({'error': f'Invalid image: {e}'}, status=400)

        upload_dir = os.path.join(os.path.dirname(__file__), 'static', 'uploads', f'{image_type}s')
        filepath   = os.path.join(upload_dir, f'{tournament_id}.jpg')
        with open(filepath, 'wb') as f:
            f.write(data)

        clean_path = f'/static/uploads/{image_type}s/{tournament_id}.jpg'
        await bot.dh.update_tournament_image_path(tournament['_id'], image_type, clean_path)
        return web.json_response({'ok': True, 'url': f'{clean_path}?v={int(time.time())}'})

    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)


@require_auth
async def handle_delete_image(request: web.Request) -> web.Response:
    """Delete a tournament's banner or logo image."""
    tournament_id = request.match_info['tournament_id']
    image_type    = request.match_info['image_type']
    bot           = request.app['bot']

    if image_type not in ('banner', 'logo'):
        return web.json_response({'error': 'Invalid image type'}, status=400)

    filepath = os.path.join(
        os.path.dirname(__file__), 'static', 'uploads',
        f'{image_type}s', f'{tournament_id}.jpg'
    )
    if os.path.exists(filepath):
        os.remove(filepath)

    await bot.dh.update_tournament_image_path(
        (await bot.dh.get_tournament_by_id(tournament_id))['_id'],
        image_type, None
    )
    return web.json_response({'ok': True})


# ─── App factory ──────────────────────────────────────────────────────────────

def create_app(challonge_handler_factory, bot) -> web.Application:
    app = web.Application()
    app['challonge_handler_factory'] = challonge_handler_factory
    app['bot'] = bot

    # Auth
    app.router.add_get('/auth/login',    handle_login)
    app.router.add_get('/auth/redirect', handle_oauth_redirect)
    app.router.add_get('/auth/callback', handle_oauth_callback)
    app.router.add_get('/auth/logout',   handle_logout)

    # Main dashboard
    app.router.add_get( '/dashboard',      handle_dashboard)
    app.router.add_get( '/api/tournaments', handle_get_tournaments)
    app.router.add_post('/api/tournaments', handle_create_tournament)
    app.router.add_post(  '/api/tournament/{tournament_id}/upload/{image_type}', handle_upload_image)
    app.router.add_delete('/api/tournament/{tournament_id}/upload/{image_type}', handle_delete_image)

    # Event dashboard
    app.router.add_get(   '/dashboard/{tournament_id}',              handle_event_dashboard)
    app.router.add_get(   '/api/tournament/{tournament_id}',          handle_get_tournament)
    app.router.add_post(  '/api/tournament/{tournament_id}/action',   handle_tournament_action)
    app.router.add_post(  '/api/tournament/{tournament_id}/stages',   handle_add_stages)
    app.router.add_delete('/api/tournament/{tournament_id}/stages/{code}', handle_remove_stage)
    app.router.add_get(   '/api/tournament/{tournament_id}/bracket',  handle_get_bracket)
    app.router.add_get(   '/api/tournament/{tournament_id}/stagelist', handle_get_stagelist)
    app.router.add_get(   '/api/stages/browse',                       handle_browse_stages)
    app.router.add_post(  '/api/tournament/{tournament_id}/seed',     handle_set_seed)
    app.router.add_get(   '/api/tournament/{tournament_id}/pending_matches', handle_get_pending_matches)

    # Seeding
    app.router.add_get( '/seeding',         handle_seeding_page)
    app.router.add_get( '/api/participants', handle_get_participants)
    app.router.add_post('/api/seed',         handle_update_seed)

    assets_path = os.path.join(os.path.dirname(__file__), '..', 'assets')
    app.router.add_static('/assets', path=assets_path, name='assets')

    static_path = os.path.join(os.path.dirname(__file__), 'static')
    app.router.add_static('/static', path=static_path, name='static')

    return app


async def start_server(challonge_handler_factory, bot):
    host = os.getenv('WEB_HOST', '0.0.0.0')
    port = int(os.getenv('PORT', os.getenv('WEB_PORT', 8080)))

    base = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
    os.makedirs(os.path.join(base, 'banners'), exist_ok=True)
    os.makedirs(os.path.join(base, 'logos'),   exist_ok=True)

    app = create_app(challonge_handler_factory, bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    print(f"Web server running on {host}:{port}")