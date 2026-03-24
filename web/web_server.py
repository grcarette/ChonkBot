import os
import secrets
import discord
import asyncio
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
                'id':        p['id'],
                'name':      p['name'],
                'seed':      p.get('seed'),
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

    tournament_data = {
        'name':                  name,
        'date':                  body.get('date', ''),
        'organizer':             session['discord_user_id'],
        'format':                fmt,
        'approved_registration': approved_registration,
        'randomized_stagelist':  randomized_stagelist,
        'display_entrants':      display_entrants,
        'round_limit':           round_limit,
        'debug':                 debug,
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

    lobby_player_ids = [int(uid) for l in (raw_lobbies or []) for uid in l.get('players', [])]
    entrant_ids      = [int(d) for d in tournament.get('entrants', {}).keys()]
    all_ids          = list(set(entrant_ids + lobby_player_ids))
    user_map         = await bot.dh.get_users_bulk(all_ids)

    # ── Seed data ─────────────────────────────────────────────────────────────

    seed_by_discord:         dict[int, int | None] = {}
    challonge_id_by_discord: dict[int, int | None] = {}
    if is_bracket_fmt:
        if 'challonge_data' in tournament:
            challonge_to_discord = {
                int(cid): int(did)
                for did, cid in tournament.get('entrants', {}).items()
                if cid is not None
            }
            for p in participants:
                discord_id = challonge_to_discord.get(p['id'])
                if discord_id:
                    seed_by_discord[discord_id]         = p.get('seed')
                    challonge_id_by_discord[discord_id] = p['id']
        else:
            native_seeds = tournament.get('seeds', {})
            entrant_keys = {str(k): k for k in [int(d) for d in tournament.get('entrants', {}).keys()]}
            for discord_id_str, seed in native_seeds.items():
                matched_id = entrant_keys.get(discord_id_str)
                if matched_id is not None:
                    seed_by_discord[matched_id] = seed

    # ── Entrants ──────────────────────────────────────────────────────────────

    entrants = []
    for discord_id_str in tournament.get('entrants', {}).keys():
        discord_id_int = int(discord_id_str)
        user = user_map.get(discord_id_int)
        entrants.append({
            'discord_id':   str(discord_id_int),
            'name':         user['name'] if user else f'Unknown ({discord_id_str})',
            'seed':         seed_by_discord.get(discord_id_int),
            'challonge_id': challonge_id_by_discord.get(discord_id_int),
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
            uid_int = int(uid)
            user    = user_map.get(uid_int)
            player_names.append(user['name'] if user else str(uid))
            player_ids.append(uid_int)
        lobbies.append({
            'match_id':     l.get('match_id'),
            'lobby_name':   l.get('lobby_name', ''),
            'state':        l.get('state', ''),
            'player_names': player_names,
            'player_ids':   player_ids,
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

    swiss_data = None
    if swiss_event:
        players           = swiss_event.get('players', {})
        active_matches    = sum(
            1 for p in players.values()
            if p.get('active_match_id') is not None and not p.get('dropped')
        ) // 2
        players_remaining = sum(1 for p in players.values() if not p.get('dropped'))
        round_ready       = (
            tournament.get('state') == 'active'
            and active_matches == 0
            and players_remaining > 1
        )
        swiss_data = {
            'current_round':     swiss_event.get('current_round', 0),
            'round_limit':       swiss_event.get('round_limit', tournament.get('round_limit', 8)),
            'active_matches':    active_matches,
            'players_remaining': players_remaining,
            'round_ready':       round_ready,
        }

    # ── Registration requests ─────────────────────────────────────────────────

    registration_requests = []
    for rid in (request_ids or []):
        user = user_map.get(rid) or await bot.dh.get_user(user_id=rid)
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
        'checked_in': [str(x) for x in tournament.get('checked_in', [])],
        'dqs':        [str(x) for x in tournament.get('dqs', [])],
        'lobbies':               lobbies,
        'stagelist':             stagelist,
        'config':                tournament.get('config', {}),
        'swiss':                 swiss_data,
        'debug':                 tournament.get('debug', False),
        'stagelist_published':   tournament.get('stagelist_published', False),
        'registration_requests': registration_requests,
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
        'update_config',
        'refresh_event_info',
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
            if not hasattr(tm, 'format') or not tm.format:
                return web.json_response({'error': 'Format not initialised'}, status=500)
            await tm.format.manager.run_pairing_cycle()

        elif action == 'dq_player':
            need_tm()
            discord_id = int(body.get('discord_id', 0))
            if not discord_id:
                return web.json_response({'error': 'discord_id is required'}, status=400)
            result = await tm.disqualify_player(discord_id)
            if result is False:
                return web.json_response(
                    {'error': 'Player not registered or tournament is not active'},
                    status=400
                )

        elif action == 'undq_player':
            discord_id = int(body.get('discord_id', 0))
            if not discord_id:
                return web.json_response({'error': 'discord_id is required'}, status=400)
            await bot.dh.undisqualify_player(tournament['_id'], discord_id)

        elif action == 'force_advance':
            need_tm()
            match_id     = body.get('match_id')
            target_state = body.get('target_state', '')
            winner_id    = body.get('winner_id')

            if match_id is None or not target_state:
                return web.json_response(
                    {'error': 'match_id and target_state are required'}, status=400
                )
            match_lobby = tm.lobbies.get(match_id)
            if not match_lobby:
                return web.json_response(
                    {'error': 'Lobby not found in memory — bot may have restarted'},
                    status=404
                )

            if target_state == 'winner':
                # Update DB immediately so dashboard reflects finished state right away,
                # then fire the rest of the chain in the background
                await match_lobby.dh.update_lobby_state(match_id, 'finished')
                asyncio.create_task(match_lobby.force_advance(target_state, winner_id=winner_id))
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
            for key in ('approved_registration', 'randomized_stagelist', 'display_entrants'):
                if key in body:
                    updates[f'config.{key}'] = bool(body[key])
            if updates:
                await bot.dh.edit_tournament_config(tournament['_id'], **updates)
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
            
            # Remove from requests first
            await bot.dh.remove_registration_request(tournament['_id'], discord_id)
            
            # Register directly, bypassing the approval check
            await tm.register_player_direct(discord_id)
            
            # DM the player
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
            # DM the player
            member = bot.guild.get_member(discord_id)
            if member:
                try:
                    desc = f"Your registration for **{tournament['name']}** has been denied."
                    if reason:
                        desc += f"\n**Reason:** {reason}"
                    embed = discord.Embed(title='Registration Denied', description=desc, color=discord.Color.red())
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
            pending = await tm.get_pending_matches()
            match_data = next((m for m in pending if m['match_id'] == match_id), None)
            if not match_data:
                return web.json_response({'error': 'Match not found or already called'}, status=400)
            await tm.call_match(match_data)

        elif action == 'hold_match':
            need_tm()
            match_id = body.get('match_id')
            if match_id is None:
                return web.json_response({'error': 'match_id is required'}, status=400)
            pending = await tm.get_pending_matches()
            match_data = next((m for m in pending if m['match_id'] == match_id), None)
            if not match_data:
                return web.json_response({'error': 'Match not found or already called'}, status=400)
            await tm.call_match(match_data, hold_match=True)

        elif action == 'call_all_matches':
            need_tm()
            await tm.call_matches()

        elif action == 'set_autocall':
            need_tm()
            enabled = bool(body.get('enabled', False))
            tm.autocall_matches = enabled
            if enabled:
                await tm.call_matches()
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
            tm.invalidate_pending_cache()
        elif action == 'post_results':
            need_tm()
            await tm.post_final_results()
        elif action == 'update_config':
            updates = {}
            if 'name' in body:
                name = body['name'].strip()
                if not name:
                    return web.json_response({'error': 'Name cannot be empty'}, status=400)
                updates['name'] = name
            if 'date' in body:
                updates['date'] = body['date'].strip()
            for key in ('approved_registration', 'randomized_stagelist', 'display_entrants'):
                if key in body:
                    updates[f'config.{key}'] = bool(body[key])
            if updates:
                await bot.dh.edit_tournament_config(tournament['_id'], **updates)
                if tm and 'config.display_entrants' in updates:
                    await tm.post_event_info()
        elif action == 'refresh_event_info':
            need_tm()
            await tm.post_event_info()
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
        # Challonge-backed — update seeds via Challonge API
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
    """
    Return all bracket matches for a DE/SE tournament, enriched with
    lobby state from our own DB and player display names.
    """
    tournament_id = request.match_info['tournament_id']
    bot           = request.app['bot']

    tournament = await bot.dh.get_tournament_by_id(tournament_id)
    if not tournament:
        return web.json_response({'error': 'Tournament not found'}, status=404)

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

    # Build challonge_id → discord_id lookup
    challonge_to_discord = {
        int(challonge_id): int(discord_id)
        for discord_id, challonge_id in tournament.get('entrants', {}).items()
    }

    # Bulk fetch all entrant user docs
    entrant_ids = [int(d) for d in tournament.get('entrants', {}).keys()]
    user_map    = await bot.dh.get_users_bulk(entrant_ids)

    # Build discord_id → name and avatar lookups
    discord_to_name   = {}
    discord_to_avatar = {}
    for discord_id_int, user in user_map.items():
        discord_to_name[discord_id_int]   = user['name']
        discord_to_avatar[discord_id_int] = user.get('avatar_url')

    # Fetch all matches from Challonge
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

    # Build lobby state lookup keyed by match_id
    raw_lobbies = await bot.dh.get_all_lobbies(tournament['_id'])
    lobby_by_match = {}
    for l in (raw_lobbies or []):
        mid = l.get('match_id')
        if mid is not None:
            lobby_by_match[mid] = l

    def player_name(challonge_pid):
        if challonge_pid is None:
            return None
        discord_id = challonge_to_discord.get(int(challonge_pid))
        if discord_id is None:
            return f'#{challonge_pid}'
        return discord_to_name.get(discord_id, f'#{challonge_pid}')

    def player_discord_id(challonge_pid):
        if challonge_pid is None:
            return None
        return challonge_to_discord.get(int(challonge_pid))

    def player_avatar(challonge_pid):
        if challonge_pid is None:
            return None
        discord_id = challonge_to_discord.get(int(challonge_pid))
        if discord_id is None:
            return None
        return discord_to_avatar.get(discord_id)

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
        # fall back to individual lookups
        stages = []
        for code in codes:
            s = await bot.dh.get_stage(code=code)
            if s:
                stages.append(s)

    # Preserve the order from the tournament's stagelist
    stage_map = {s['code']: s for s in (stages or [])}
    ordered = []
    for code in codes:
        s = stage_map.get(code)
        ordered.append({
            'code':               code,
            'name':               s.get('name', code) if s else code,
            'imgur_url':          s.get('imgur_url', '') if s else '',
            'mode':               s.get('mode', '') if s else '',
            'tournament_legal':   s.get('tournament_legal', True) if s else True,
            'creators':           s.get('creators', []) if s else [],
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
            'code':           s.get('code', ''),
            'name':           s.get('name', ''),
            'imgur_url':      s.get('imgur_url', ''),
            'mode':           s.get('mode', ''),
            'tournament_legal': s.get('tournament_legal', True),
            'creators':       s.get('creators', []),
        })

    return web.json_response({'stages': result})

@require_auth
async def handle_get_pending_matches(request: web.Request) -> web.Response:
    """Return all Challonge matches that haven't been called yet."""
    tournament_id = request.match_info['tournament_id']
    bot           = request.app['bot']

    tournament = await bot.dh.get_tournament_by_id(tournament_id)
    if not tournament:
        return web.json_response({'error': 'Tournament not found'}, status=404)

    tm = bot.th.tournaments.get(tournament['_id'])
    if not tm:
        return web.json_response({'error': 'Tournament manager not loaded'}, status=500)

    try:
        pending = await tm.get_pending_matches()
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

    all_player_ids = list({m['player_1'] for m in pending} | {m['player_2'] for m in pending})
    user_map = await bot.dh.get_users_bulk(all_player_ids)

    result = []
    for m in pending:
        p1 = user_map.get(m['player_1'])
        p2 = user_map.get(m['player_2'])
        result.append({
            'match_id': m['match_id'],
            'round':    m['round'],
            'bracket':  m['bracket'],
            'p1_name':  p1['name'] if p1 else str(m['player_1']),
            'p2_name':  p2['name'] if p2 else str(m['player_2']),
        })

    return web.json_response({'pending': result})

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

    # Event dashboard
    app.router.add_get(   '/dashboard/{tournament_id}', handle_event_dashboard)
    app.router.add_get(   '/api/tournament/{tournament_id}', handle_get_tournament)
    app.router.add_post(  '/api/tournament/{tournament_id}/action', handle_tournament_action)
    app.router.add_post(  '/api/tournament/{tournament_id}/stages', handle_add_stages)
    app.router.add_delete('/api/tournament/{tournament_id}/stages/{code}', handle_remove_stage)
    app.router.add_get('/api/tournament/{tournament_id}/bracket', handle_get_bracket)
    app.router.add_get('/api/tournament/{tournament_id}/stagelist', handle_get_stagelist)
    app.router.add_get('/api/stages/browse', handle_browse_stages)
    app.router.add_post('/api/tournament/{tournament_id}/seed', handle_set_seed)
    app.router.add_get('/api/tournament/{tournament_id}/pending_matches', handle_get_pending_matches)

    # Seeding
    app.router.add_get( '/seeding',          handle_seeding_page)
    app.router.add_get( '/api/participants',  handle_get_participants)
    app.router.add_post('/api/seed',          handle_update_seed)

    assets_path = os.path.join(os.path.dirname(__file__), '..', 'assets')
    app.router.add_static('/assets', path=assets_path, name='assets')

    static_path = os.path.join(os.path.dirname(__file__), 'static')
    app.router.add_static('/static', path=static_path, name='static')


    return app


async def start_server(challonge_handler_factory, bot):
    """Start the aiohttp server. Called from bot.py on_ready."""
    host = os.getenv('WEB_HOST', '0.0.0.0')
    port = int(os.getenv('PORT', os.getenv('WEB_PORT', 8080)))

    app = create_app(challonge_handler_factory, bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    print(f"Web server running on {host}:{port}")