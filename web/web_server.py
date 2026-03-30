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
_tournament_action_locks: dict[str, asyncio.Lock] = {}

TOKEN_EXPIRY_MINUTES = 30

def _get_phase(tournament: dict, phase_idx: int | None = None) -> dict:
    """Return the phase dict at phase_idx, defaulting to active_phase."""
    phases = tournament.get('phases', [])
    if phase_idx is None:
        phase_idx = tournament.get('active_phase', 0)
    if phase_idx < len(phases):
        return phases[phase_idx]
    return {}


def _get_tournament_lock(tournament_id: str) -> asyncio.Lock:
    if tournament_id not in _tournament_action_locks:
        _tournament_action_locks[tournament_id] = asyncio.Lock()
    return _tournament_action_locks[tournament_id]

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
        phase = _get_phase(tournament)
        challonge_to_discord = {
            int(challonge_id): int(discord_id)
            for discord_id, challonge_id in phase.get('entrants', {}).items()
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

    all_lobbies = await asyncio.gather(
        *[bot.dh.get_active_lobbies(t['_id']) for t in tournaments]
    )

    for t, lobbies in zip(tournaments, all_lobbies):
        tid = t['_id']
        entrant_count = len(t.get('entrants', {}))
        total_players += entrant_count

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
    ranked_reporting           = bool(body.get('ranked_reporting', False))
    teams_mode                 = bool(body.get('teams_mode', False))
    staggered_start            = bool(body.get('staggered_start', False))
    staggered_start_threshold  = max(1, min(int(body.get('staggered_start_threshold', 16)), 999))

    tournament_data = {
        'name':                      name,
        'date':                      body.get('date', ''),
        'organizer':                 session['discord_user_id'],
        'format':                    fmt,
        'approved_registration':     approved_registration,
        'randomized_stagelist':      randomized_stagelist,
        'display_entrants':          display_entrants,
        'round_limit':               round_limit,
        'ranked_reporting':          ranked_reporting,
        'debug':                     debug,
        'teams_mode':                teams_mode,
        'staggered_start':           staggered_start,
        'staggered_start_threshold': staggered_start_threshold,
    }

    if fmt == 'swiss filter':
        tournament_data['round_limit'] = 3
        tournament_data['top_seed_floating'] = bool(body.get('top_seed_floating', False))
        tournament_data['top_seed_floating_count'] = max(0, min(
            int(body.get('top_seed_floating_count', 0)), 999
        ))

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

    phases           = tournament.get('phases', [])
    active_phase_idx = tournament.get('active_phase', 0)
    active_phase     = phases[active_phase_idx] if active_phase_idx < len(phases) else {}
    phase0           = phases[0] if phases else {}

    # For swiss filter events with floating, the Pro bracket shell holds floated
    # players separately from the Swiss entrants. Merge them for display/seeding.
    swiss_filter_pro_entrants: dict = {}
    if fmt == 'swiss filter' and len(phases) > 1:
        swiss_filter_pro_entrants = phases[1].get('entrants') or {}

    # ── Parallel fetches ──────────────────────────────────────────────────────

    async def _fetch_challonge_participants():
        # Only fetch from Challonge for single-phase DE/SE events.
        # Swiss filter uses native seeds; its bracket phases have their own views.
        ch_data = active_phase.get('challonge_data')
        if not (fmt in ('single elimination', 'double elimination') and ch_data):
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
                ch_handler = ChallongeHandler(ch_data['url'])
            return await ch_handler.get_participants(ch_data['url'])
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

    # Resolve entrant IDs — top-level entrants tracks who is registered (no challonge IDs).
    # Phase-level entrants (active_phase) hold the challonge ID mapping for gameplay.
    top_level_entrants = tournament.get('entrants', {})
    entrant_ids = []
    for key in list(top_level_entrants.keys()) + list(swiss_filter_pro_entrants.keys()):
        key_str = str(key)
        if '_' in key_str:
            try:
                p1, p2 = key_str.split('_')
                entrant_ids.extend([p1, p2])
            except ValueError:
                pass
        else:
            entrant_ids.append(key_str)

    request_id_strs = [str(r) for r in (request_ids or [])]
    all_ids  = list(set(entrant_ids + lobby_player_ids + request_id_strs))
    user_map = await bot.dh.get_users_bulk(all_ids)

    # ── Seed data ─────────────────────────────────────────────────────────────
    # Populate seeds for ALL formats, not just bracket.
    # Bracket formats pull from Challonge participants; everything else uses
    # the native tournament.seeds dict.

    seed_by_discord:         dict[str, int | None] = {}
    challonge_id_by_discord: dict[str, int | None] = {}

    if fmt in ('single elimination', 'double elimination') and active_phase.get('challonge_data'):
        challonge_to_discord = {
            int(cid): str(did)
            for did, cid in active_phase.get('entrants', {}).items()
            if cid is not None
        }
        for p in participants:
            discord_id = challonge_to_discord.get(p['id'])
            if discord_id:
                seed_by_discord[discord_id]         = p.get('seed')
                challonge_id_by_discord[discord_id] = p['id']
    else:
        native_seeds    = tournament.get('seeds', {})
        entrant_key_set = (
            {str(k) for k in top_level_entrants.keys()} |
            {str(k) for k in swiss_filter_pro_entrants.keys()}
        )
        for discord_id_str, seed in native_seeds.items():
            key_str = str(discord_id_str)
            if key_str in entrant_key_set:
                seed_by_discord[key_str] = seed

    # ── Entrants ──────────────────────────────────────────────────────────────

    entrants = []
    _all_entrant_keys = list(top_level_entrants.keys()) + [
        k for k in swiss_filter_pro_entrants if str(k) not in {str(x) for x in top_level_entrants.keys()}
    ]
    for key_str in _all_entrant_keys:
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
                    'seed':       seed_by_discord.get(key_str),
                    'challonge_id': active_phase.get('entrants', {}).get(key_str),
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
        # Include phase_transition if the swiss phase is done and bracket phases are waiting
        if swiss_event.get('state') == 'finished':
            has_waiting = any(
                p.get('state') == 'waiting'
                for p in tournament.get('phases', [])[1:]
            )
            if has_waiting:
                swiss_data['phase_transition'] = {
                    'label':           'Start Bracket Phase',
                    'action':          'transition_phase',
                    'confirm_title':   'Start Bracket Phase?',
                    'confirm_message': (
                        'Players will be sorted into brackets based on their Swiss record. '
                        'This cannot be undone.'
                    ),
                }

    # ── autocall / hold_when_ready (Challonge formats only) ──────────────────

    autocall_matches = getattr(tm.format, 'autocall_matches', False) if tm and tm.format else False

    # ── Registration requests ─────────────────────────────────────────────────

    registration_requests = []
    for rid in (request_ids or []):
        user = user_map.get(str(rid))
        registration_requests.append({
            'discord_id': str(rid),
            'name':       user['name'] if user else str(rid),
            'avatar_url': user.get('avatar_url') if user else None,
        })

    # ── Phase data ────────────────────────────────────────────────────────────

    em = bot.th.events.get(tournament['_id'])

    async def _noop():
        return None

    async def _build_phase_summary(i, phase):
        from utils.get_bracket_link import get_bracket_link
        phase_tm = em.phase_managers.get(i) if em else None
        phase_tid = phase.get('tournament_id')

        challonge_url, phase_lobbies, phase_swiss = await asyncio.gather(
            get_bracket_link(phase['challonge_data']['url']) if phase.get('challonge_data') else _noop(),
            bot.dh.get_active_lobbies(phase_tid) if (phase_tid and phase_tid != tournament['_id']) else _noop(),
            bot.dh.get_swiss_event_by_tournament(phase.get('tournament_id', tournament['_id']))
                if (phase_tm and phase['type'] in ('swiss', 'swiss filter')) else _noop(),
        )

        phase_summary = {
            'index': i,
            'type': phase['type'],
            'label': phase.get('label', phase['type'].title()),
            'state': phase['state'],
            'round_limit': phase.get('round_limit'),
            'config_overrides': phase.get('config_overrides', {}),
            'entrant_count': len(phase.get('entrants', {})),
            'autocall_matches': (
                getattr(phase_tm.format, 'autocall_matches', False)
                if phase_tm and phase_tm.format else False
            ),
        }

        if challonge_url is not None:
            phase_summary['challonge_url'] = challonge_url

        if phase_swiss and phase_tm and phase_tm.format:
            phase_summary['swiss'] = await phase_tm.format.get_dashboard_state()

        if phase_lobbies is not None:
            phase_summary['lobby_count'] = len(phase_lobbies)
        else:
            phase_summary['lobby_count'] = len(raw_lobbies) if raw_lobbies else 0

        return phase_summary

    phases_data = list(await asyncio.gather(
        *[_build_phase_summary(i, phase)
          for i, phase in enumerate(tournament.get('phases', []))]
    ))

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
                fmt in ('swiss', 'swiss filter')
                and tournament.get('config', {}).get('randomized_stagelist', False)
                and bool(tournament.get('stagelist'))
            )
        ),
        'registration_requests': registration_requests,
        'banner_url':            tournament.get('banner_url'),
        'logo_url':              tournament.get('logo_url'),
        'ranked_compatible':     getattr(tm.format, 'ranked_compatible', False) if tm and tm.format else False,
        'ranked_reporting':      tournament.get('config', {}).get('ranked_reporting', False),
        'phases':                phases_data,
        'active_phase':          tournament.get('active_phase', 0),
        'is_multi_phase':        len(phases_data) >= 1,
        'brackets_created':      (
            fmt == 'swiss filter'
            and all(
                p.get('challonge_data') is not None
                for p in tournament.get('phases', [])
                if p.get('type') in ('single elimination', 'double elimination')
            )
            and any(
                p.get('type') in ('single elimination', 'double elimination')
                for p in tournament.get('phases', [])
            )
        ),
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
        'dq_player', 'undq_player', 'unregister_player',
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
        'sync_floated_players',
        'toggle_hold_when_ready',
        'unpublish_tournament',
        'reopen_lobby',
        'transition_phase',
        'create_bracket_shells',
    }
    if action not in VALID_ACTIONS:
        return web.json_response({'error': f'Unknown action: {action!r}'}, status=400)

    # ── Acquire per-tournament lock to prevent concurrent state mutations ──
    lock = _get_tournament_lock(tournament_id)
    if lock.locked():
        return web.json_response(
            {'error': 'Another action is already in progress for this tournament'},
            status=409
        )

    async with lock:
        # Re-fetch tournament inside the lock to get the latest state
        tournament = await bot.dh.get_tournament_by_id(tournament_id)
        if not tournament:
            return web.json_response({'error': 'Tournament not found'}, status=404)
        tm = bot.th.tournaments.get(tournament['_id'])

        # If a phase_index is provided, route to the phase's TM instead
        phase_index_raw = body.get('phase_index')
        if phase_index_raw is not None:
            em_lookup = bot.th.events.get(tournament['_id'])
            if em_lookup:
                phase_tm_lookup = em_lookup.phase_managers.get(int(phase_index_raw))
                if phase_tm_lookup:
                    tm = phase_tm_lookup

        # Top-level entrants tracks who is registered; use it to resolve discord IDs
        _all_phase_entrant_keys = list(tournament.get('entrants', {}).keys())

        # Normalize discord_id to string to survive JS 64-bit precision loss
        if 'discord_id' in body and body['discord_id'] is not None:
            body['discord_id'] = str(body['discord_id'])

        def need_tm():
            if not tm:
                raise ValueError('Tournament manager not loaded — bot may need restart')

        try:
            if action == 'progress':
                need_tm()
                if tournament.get('state') == 'registration':
                    config = tournament.get('config', {})
                    if not config.get('randomized_stagelist', False):
                        stages = tournament.get('stagelist', [])
                        if len(stages) < 5:
                            return web.json_response(
                                {'error': f'At least 5 stages are required to start check-in (currently {len(stages)}).'},
                                status=400
                            )
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
                discord_id_raw = body.get('discord_id')
                if discord_id_raw is None:
                    return web.json_response({'error': 'discord_id is required'}, status=400)
                discord_id = next(
                    (k for k in _all_phase_entrant_keys if str(k) == str(discord_id_raw)),
                    discord_id_raw
                )
                result = await tm.disqualify_player(int(discord_id))
                if result is False:
                    return web.json_response(
                        {'error': 'Player not registered or tournament is not active'},
                        status=400
                    )

            elif action == 'undq_player':
                need_tm()
                discord_id_raw = body.get('discord_id')
                if discord_id_raw is None:
                    return web.json_response({'error': 'discord_id is required'}, status=400)
                discord_id = next(
                    (k for k in _all_phase_entrant_keys if str(k) == str(discord_id_raw)),
                    discord_id_raw
                )
                await tm.undisqualify_player(int(discord_id))

            elif action == 'unregister_player':
                need_tm()
                discord_id_raw = body.get('discord_id')
                if discord_id_raw is None:
                    return web.json_response({'error': 'discord_id is required'}, status=400)
                discord_id = next(
                    (k for k in _all_phase_entrant_keys if str(k) == str(discord_id_raw)),
                    discord_id_raw
                )
                await tm.unregister_player(int(discord_id))

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
                    # Check both the DB state AND the in-memory resolved flag
                    lobby_data = await match_lobby.get_lobby()
                    if lobby_data.get('state') == 'finished':
                        return web.json_response(
                            {'error': 'Lobby is already finished — cannot force-advance again'},
                            status=400
                        )
                    if getattr(match_lobby, 'resolved', False):
                        return web.json_response(
                            {'error': 'Lobby result is already being processed'},
                            status=409
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
                if 'staggered_start' in body:
                    updates['config.staggered_start'] = bool(body['staggered_start'])
                if 'staggered_start_threshold' in body:
                    updates['config.staggered_start_threshold'] = max(1, min(int(body['staggered_start_threshold']), 999))
                if 'top_seed_floating' in body:
                    updates['config.top_seed_floating'] = bool(body['top_seed_floating'])
                if 'top_seed_floating_count' in body:
                    try:
                        val = int(body['top_seed_floating_count'])
                    except (TypeError, ValueError):
                        val = 0
                    updates['config.top_seed_floating_count'] = max(0, min(val, 999))
                if 'info_links' in body:
                    raw = body['info_links']
                    if not isinstance(raw, list):
                        return web.json_response({'error': 'info_links must be a list'}, status=400)
                    links = []
                    for item in raw:
                        label = str(item.get('label') or '').strip()[:80]
                        url   = str(item.get('url')   or '').strip()
                        if not label or not url:
                            continue
                        if not url.startswith(('http://', 'https://')):
                            return web.json_response(
                                {'error': f'Invalid URL (must start with http:// or https://): {url}'},
                                status=400
                            )
                        links.append({'label': label, 'url': url})
                    updates['config.info_links'] = links
                if updates:
                    await bot.dh.edit_tournament_config(tournament['_id'], **updates)
                    needs_embed_refresh = {'config.display_entrants', 'config.info_links'} & updates.keys()
                    print(f'[update_config] updates={list(updates.keys())} needs_embed_refresh={bool(needs_embed_refresh)} tm={tm!r}')
                    if tm and needs_embed_refresh:
                        has_category = bool(tournament.get('category_id'))
                        has_category_obj = bool(tm.get_tournament_category())
                        print(f'[update_config] has_category={has_category} has_category_obj={has_category_obj} tournament_id={tournament["_id"]}')
                        if has_category and has_category_obj:
                            print(f'[update_config] calling edit_event_info()')
                            await tm.edit_event_info()

            elif action == 'delete_tournament':
                need_tm()

                confirm_name = body.get('confirm_name', '').strip()
                if confirm_name != tournament.get('name', ''):
                    return web.json_response(
                        {'error': 'Tournament name does not match. Deletion cancelled.'},
                        status=400
                    )

                # Delete ALL Challonge brackets from this event, regardless of
                # EventManager state. Reads directly from the DB document so
                # this works even if the EM isn't loaded or is stale.
                from tournaments.challonge_handler import ChallongeHandler
                ch = ChallongeHandler()

                # Phase-level brackets (swiss filter Pro/Intermediate/Beginner)
                for phase in tournament.get('phases', []):
                    ch_data = phase.get('challonge_data')
                    if ch_data:
                        try:
                            await ch.delete_tournament(ch_data['id'])
                            print(f'[DELETE] Deleted Challonge bracket: {ch_data["url"]}')
                        except Exception as e:
                            print(f'[DELETE] Failed to delete Challonge bracket {ch_data.get("url")}: {e}')

                # Top-level bracket (single/double elim events)
                top_ch = tournament.get('challonge_data')
                if top_ch:
                    try:
                        await ch.delete_tournament(top_ch['id'])
                        print(f'[DELETE] Deleted top-level Challonge bracket: {top_ch["url"]}')
                    except Exception as e:
                        print(f'[DELETE] Failed to delete top-level Challonge bracket {top_ch.get("url")}: {e}')

                await tm.delete_tournament()

                # Also clean up the EventManager reference
                bot.th.events.pop(tournament['_id'], None)

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
                locked_map = {}
                for ls in body.get('locked_seeds', []):
                    try:
                        locked_map[int(ls['discord_id'])] = int(ls['seed'])
                    except (KeyError, ValueError, TypeError):
                        continue

                entrant_ids  = list(tournament.get('entrants', {}).keys())
                unlocked_ids = [did for did in entrant_ids if int(did) not in locked_map]
                total        = len(entrant_ids)
                taken_slots  = set(locked_map.values())
                free_slots   = [s for s in range(1, total + 1) if s not in taken_slots]
                shuffled     = random.sample(free_slots, len(free_slots))
                seeds        = dict(locked_map)
                for did, slot in zip(unlocked_ids, shuffled):
                    seeds[int(did)] = slot
                await bot.dh.update_all_seeds(tournament['_id'], seeds)
                em = bot.th.events.get(tournament['_id'])
                print(f'[FLOAT] randomize_seeds: em={em}, format={tournament.get("format")}, id={tournament["_id"]}')
                if em and tournament.get('format') == 'swiss filter':
                    await em.sync_floated_players()

            elif action == 'seed_by_rank':
                locked_map = {}
                for ls in body.get('locked_seeds', []):
                    try:
                        locked_map[int(ls['discord_id'])] = int(ls['seed'])
                    except (KeyError, ValueError, TypeError):
                        continue

                entrant_ids  = set(int(did) for did in tournament.get('entrants', {}).keys())
                unlocked_ids = {did for did in entrant_ids if did not in locked_map}
                leaderboard  = await bot.uchranked_api.get_leaderboard(10000)
                elo_map = {}
                for p in leaderboard:
                    try:
                        discord_id = int(p['discord_id'])
                        if discord_id in unlocked_ids:
                            elo_map[discord_id] = p['elo']
                    except (ValueError, TypeError, KeyError):
                        continue
                for discord_id in unlocked_ids:
                    if discord_id not in elo_map:
                        elo_map[discord_id] = 0
                sorted_ids  = sorted(unlocked_ids, key=lambda uid: elo_map[uid], reverse=True)
                total       = len(entrant_ids)
                taken_slots = set(locked_map.values())
                free_slots  = sorted(s for s in range(1, total + 1) if s not in taken_slots)
                seeds       = dict(locked_map)
                for discord_id, slot in zip(sorted_ids, free_slots):
                    seeds[discord_id] = slot
                await bot.dh.update_all_seeds(tournament['_id'], seeds)
                em = bot.th.events.get(tournament['_id'])
                print(f'[FLOAT] seed_by_rank: em={em}, format={tournament.get("format")}, id={tournament["_id"]}')
                if em and tournament.get('format') == 'swiss filter':
                    await em.sync_floated_players()

            elif action == 'revert_tournament':
                need_tm()
                await tm.revert_tournament()

            elif action == 'call_match':
                need_tm()
                match_id = body.get('match_id')
                if match_id is None:
                    return web.json_response({'error': 'match_id is required'}, status=400)
                pending = await tm.format.get_pending_matches()
                match_data = next((m for m in pending if m['match_id'] == match_id), None)
                if not match_data:
                    return web.json_response({'error': 'Match not found or already called'}, status=400)
                try:
                    await tm.format.call_match(match_data)
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    return web.json_response({'error': str(e)}, status=500)
                if hasattr(tm.format, 'invalidate_pending_cache'):
                    tm.format.invalidate_pending_cache()
                    
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
                if hasattr(tm.format, 'invalidate_pending_cache'):
                    tm.format.invalidate_pending_cache()

            elif action == 'call_all_matches':
                need_tm()
                await tm.format.call_matches()
                if hasattr(tm.format, 'invalidate_pending_cache'):
                    tm.format.invalidate_pending_cache()

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
                if tournament.get('format') == 'swiss filter':
                    em = bot.th.events.get(tournament['_id'])
                    if not em:
                        return web.json_response({'error': 'Event manager not loaded'}, status=400)
                    # Post in reverse order: Beginner (3) → Intermediate (2) → Pro (1)
                    # so Pro shows first in the channel (most recent message at top)
                    for phase_index in [3, 2, 1]:
                        phase_tm = em.phase_managers.get(phase_index)
                        if phase_tm and phase_tm.format:
                            phase = em.event['phases'][phase_index]
                            if phase.get('challonge_data') and phase.get('entrants'):
                                await phase_tm.post_final_results()
                else:
                    need_tm()
                    await tm.post_final_results()

            elif action == 'refresh_event_info':
                need_tm()
                await tm.edit_event_info()

            elif action == 'sync_floated_players':
                em = bot.th.events.get(tournament['_id'])
                print(f'[FLOAT] sync_floated_players action received — em={em}, tournament_id={tournament["_id"]}')
                if em:
                    await em.sync_floated_players()
                else:
                    print(f'[FLOAT] no EventManager found for {tournament["_id"]} — keys={list(bot.th.events.keys())[:5]}')

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
                em = bot.th.events.get(tournament['_id'])
                if em and tournament.get('format') in ('swiss filter', 'single elimination', 'double elimination'):
                    await em.destroy_bracket_shells()
                await tm.remove_tournament_from_discord()
                await bot.dh.unpublish_tournament(tournament['_id'])

            elif action == 'reopen_lobby':
                need_tm()
                match_id_str = str(body.get('match_id'))
                await tm.reopen_lobby(match_id_str)

            elif action == 'create_bracket_shells':
                if tournament.get('format') != 'swiss filter':
                    return web.json_response({'error': 'Only swiss filter events have bracket shells'}, status=400)
                em = bot.th.events.get(tournament['_id'])
                if not em:
                    return web.json_response({'error': 'Event manager not loaded'}, status=400)
                # Refresh EM from DB so the challonge_data guard is reliable
                em.event = await bot.dh.get_tournament_by_id(tournament['_id'])
                bracket_phases = [
                    p for p in em.event.get('phases', [])
                    if p.get('type') in ('single elimination', 'double elimination')
                ]
                if bracket_phases and all(p.get('challonge_data') for p in bracket_phases):
                    return web.json_response({'error': 'Bracket shells already exist'}, status=400)
                await em.create_bracket_shells()

            elif action == 'transition_phase':
                em = bot.th.events.get(tournament['_id'])
                if not em:
                    return web.json_response({'error': 'Event manager not loaded'}, status=400)
                if tournament.get('format') == 'swiss filter':
                    await em.transition_to_brackets()
                else:
                    await em.transition_to_next_phase()
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
    if fmt not in ('single elimination', 'double elimination', 'swiss filter', 'swiss'):
        return web.json_response({'error': 'Seeding not available for this format'}, status=400)

    _seeds_ch_data = _get_phase(tournament).get('challonge_data')
    if _seeds_ch_data:
        try:
            ch = bot.th.tournaments.get(tournament['_id'])
            ch_handler = (
                ch.format.ch
                if ch and hasattr(ch, 'format') and ch.format and hasattr(ch.format, 'ch')
                else None
            )
            if ch_handler is None:
                from tournaments.challonge_handler import ChallongeHandler
                ch_handler = ChallongeHandler(_seeds_ch_data['url'])
            for entry in seeds:
                try:
                    challonge_id = int(entry['challonge_id'])
                    seed         = int(entry['seed'])
                except (KeyError, ValueError, TypeError):
                    continue
                await ch_handler.update_seed(_seeds_ch_data['url'], challonge_id, seed)
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

        print(f"[BYE DEBUG] current_round={current_round}, total matches in event={len(all_matches)}")

        # Collect all player IDs referenced in any match this round
        round_matches = [m for m in all_matches if m.get('round_number') == current_round]
        matched_ids   = (
            {str(m['player_1']) for m in round_matches} |
            {str(m['player_2']) for m in round_matches}
        )

        print(f"[BYE DEBUG] round_matches this round={len(round_matches)}, matched_ids={matched_ids}")

        # Detect bye players: participated this round but not in any match
        bye_player_ids = []
        if current_round > 0:
            print(f"[BYE DEBUG] scanning {len(swiss_event.get('players', {}))} players for byes...")
            for pid, pdata in swiss_event.get('players', {}).items():
                is_dropped = pdata.get('dropped', False)
                is_matched = pid in matched_ids
                rounds_played = pdata.get('rounds_played', 0)
                byes = pdata.get('byes', 0)
                has_bye = pdata.get('has_bye', False)
                active_match = pdata.get('active_match_id')

                if not is_dropped and not is_matched:
                    print(f"[BYE DEBUG] unmatched player pid={pid}: rounds_played={rounds_played}, "
                          f"byes={byes}, has_bye={has_bye}, active_match={active_match}, "
                          f"dropped={is_dropped}, passes_round_check={rounds_played >= current_round}")

                if is_dropped:
                    continue
                if is_matched:
                    continue
                if rounds_played >= current_round:
                    bye_player_ids.append(pid)
        else:
            print(f"[BYE DEBUG] skipping bye detection — current_round is 0")

        print(f"[BYE DEBUG] bye_player_ids={bye_player_ids}")

        # Build user map including bye players
        all_player_ids = list(matched_ids | set(bye_player_ids))
        user_map       = await bot.dh.get_users_bulk(all_player_ids) if all_player_ids else {}

        raw_lobbies    = await bot.dh.get_all_lobbies(tournament['_id'])
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

        # Add synthetic bye entries
        for bp_id in bye_player_ids:
            bp_user = user_map.get(bp_id)
            bp_name = bp_user['name'] if bp_user else bp_id
            print(f"[BYE DEBUG] adding bye card for {bp_name} (id={bp_id})")
            matches.append({
                'match_id':          f'bye-{bp_id}',
                'round':             current_round,
                'bracket':           '',
                'state':             'complete',
                'lobby_state':       None,
                'p1_name':           bp_name,
                'p2_name':           'Bye',
                'p1_discord_id':     bp_id,
                'p2_discord_id':     None,
                'p1_avatar_url':     bp_user.get('avatar_url') if bp_user else None,
                'p2_avatar_url':     None,
                'winner_name':       bp_name,
                'winner_discord_id': bp_id,
                'picked_stage':      None,
                'prereq_ids':        [],
                'has_lobby':         False,
                'hold_when_ready':   False,
                'is_bye':            True,
            })

        print(f"[BYE DEBUG] returning {len(matches)} total entries ({len(round_matches)} matches + {len(bye_player_ids)} byes)")

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

    _bracket_phase     = _get_phase(tournament)
    _bracket_ch_data   = _bracket_phase.get('challonge_data')
    _bracket_entrants  = _bracket_phase.get('entrants', {})
    if not _bracket_ch_data:
        return web.json_response(
            {'error': 'No Challonge bracket linked to this tournament yet'},
            status=400
        )

    challonge_url = _bracket_ch_data['url']

    is_teams = tournament.get('config', {}).get('teams_mode', False)

    # Build challonge_id → discord_id/team_id map
    # In teams mode, the "discord_id" side is a team_id string like "101_102"
    challonge_to_discord = {}
    for key, challonge_id in _bracket_entrants.items():
        if challonge_id is None:
            continue
        try:
            challonge_to_discord[int(challonge_id)] = key  # keep as string — may be team_id
        except (ValueError, TypeError):
            pass

    # Build the user_map — resolve individual discord IDs from entrant keys
    individual_ids = []
    for key in _bracket_entrants.keys():
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


@require_auth
async def handle_get_phase_bracket(request: web.Request) -> web.Response:
    """Interactive bracket data for a specific phase (Pro / Intermediate / Beginner)."""
    tournament_id  = request.match_info['tournament_id']
    phase_index    = int(request.match_info['phase_index'])
    bot            = request.app['bot']

    tournament = await bot.dh.get_tournament_by_id(tournament_id)
    if not tournament:
        return web.json_response({'error': 'Tournament not found'}, status=404)

    phases = tournament.get('phases', [])
    if phase_index >= len(phases):
        return web.json_response({'error': 'Phase not found'}, status=404)

    phase   = phases[phase_index]
    ch_data = phase.get('challonge_data')
    if not ch_data:
        return web.json_response({'error': 'No Challonge bracket for this phase yet'}, status=404)

    fmt           = phase['type']
    challonge_url = ch_data['url']

    # challonge participant id → discord id
    challonge_to_discord: dict[int, str] = {}
    for did, cid in (phase.get('entrants') or {}).items():
        if cid is not None:
            try:
                challonge_to_discord[int(cid)] = str(did)
            except (ValueError, TypeError):
                pass

    # User name / avatar map — users collection first, Swiss username as fallback
    discord_ids = list({str(k) for k in (phase.get('entrants') or {}).keys()})
    user_map    = await bot.dh.get_users_bulk(discord_ids)

    swiss_name_map: dict[str, str] = {}
    if phases:
        swiss_phase  = phases[0]
        swiss_event  = await bot.dh.get_swiss_event_by_tournament(
            swiss_phase.get('tournament_id') or tournament['_id']
        )
        if swiss_event:
            swiss_name_map = {
                pid: p.get('username', '')
                for pid, p in swiss_event.get('players', {}).items()
            }

    discord_to_name:   dict[str, str]       = {}
    discord_to_avatar: dict[str, str | None] = {}
    for did, user in user_map.items():
        discord_to_name[did]   = user['name']
        discord_to_avatar[did] = user.get('avatar_url')
    for did, uname in swiss_name_map.items():
        if did not in discord_to_name and uname:
            discord_to_name[did] = uname

    # Fetch matches from Challonge
    em       = bot.th.events.get(tournament['_id'])
    phase_tm = em.phase_managers.get(phase_index) if em else None
    try:
        if phase_tm and hasattr(phase_tm, 'format') and phase_tm.format and hasattr(phase_tm.format, 'ch'):
            challonge_handler = phase_tm.format.ch
        else:
            from tournaments.challonge_handler import ChallongeHandler
            challonge_handler = ChallongeHandler(challonge_url)
        raw_matches = await challonge_handler.get_all_matches(challonge_url)
    except Exception as e:
        return web.json_response({'error': f'Challonge error: {str(e)}'}, status=502)

    # Lobbies for this phase
    phase_tid   = (phase_tm.tournament['_id'] if phase_tm else None) or tournament['_id']
    raw_lobbies = await bot.dh.get_all_lobbies(phase_tid)
    lobby_by_match = {l['match_id']: l for l in (raw_lobbies or [])}

    hold_when_ready: set = set()
    if phase_tm and phase_tm.format:
        hold_when_ready = getattr(phase_tm.format, 'hold_when_ready', set()) or set()

    def _pname(cid):
        if cid is None: return None
        key = challonge_to_discord.get(int(cid))
        return discord_to_name.get(key, f'#{cid}') if key else f'#{cid}'

    def _pdiscord(cid):
        if cid is None: return None
        return challonge_to_discord.get(int(cid))

    def _pavatar(cid):
        if cid is None: return None
        key = challonge_to_discord.get(int(cid))
        return discord_to_avatar.get(key) if key else None

    matches = []
    for m in raw_matches:
        match_id  = m['id']
        round_num = m['round']
        p1_cid    = m.get('player1_id')
        p2_cid    = m.get('player2_id')
        winner_cid = m.get('winner_id')

        bracket = ('Winners' if round_num > 0 else 'Losers') if fmt == 'double elimination' else ''

        pre_raw = m.get('prerequisite_match_ids_csv', '')
        if not pre_raw:
            prereq_ids = []
        elif isinstance(pre_raw, (int, float)):
            prereq_ids = [int(pre_raw)]
        else:
            prereq_ids = [int(x) for x in str(pre_raw).split(',') if x.strip()]

        lobby  = lobby_by_match.get(match_id)
        is_bye = p1_cid is None or p2_cid is None
        matches.append({
            'match_id':          match_id,
            'round':             round_num,
            'bracket':           bracket,
            'state':             m['state'],
            'lobby_state':       lobby['state'] if lobby else None,
            'p1_name':           _pname(p1_cid),
            'p2_name':           _pname(p2_cid),
            'p1_discord_id':     _pdiscord(p1_cid),
            'p2_discord_id':     _pdiscord(p2_cid),
            'p1_avatar_url':     _pavatar(p1_cid),
            'p2_avatar_url':     _pavatar(p2_cid),
            'winner_name':       _pname(winner_cid) if winner_cid else None,
            'winner_discord_id': _pdiscord(winner_cid),
            'picked_stage':      lobby.get('picked_stage') if lobby else None,
            'prereq_ids':        prereq_ids,
            'has_lobby':         lobby is not None,
            'hold_when_ready':   match_id in hold_when_ready,
            'is_bye':            is_bye,
        })

    matches.sort(key=lambda x: (0 if x['bracket'] == 'Winners' else 1, abs(x['round'])))

    return web.json_response({'format': fmt, 'matches': matches, 'phase_index': phase_index})


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
    app.router.add_get(   '/api/tournament/{tournament_id}/phase/{phase_index}/bracket', handle_get_phase_bracket)

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