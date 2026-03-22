import os
import secrets
from datetime import datetime, timezone, timedelta
from aiohttp import web

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


# ─── Seeding routes (existing, token-auth) ───────────────────────────────────

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
    with open(template_path, 'r') as f:
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
                'id': p['id'],
                'name': p['name'],
                'seed': p.get('seed'),
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


# ─── Dashboard route (session-auth) ──────────────────────────────────────────

@require_auth
async def handle_dashboard(request: web.Request) -> web.Response:
    """Serve the main TO dashboard."""
    session = request['session']

    bot = request.app['bot']
    tournaments = await bot.dh.get_active_events()

    template_path = os.path.join(os.path.dirname(__file__), 'templates', 'dashboard.html')
    with open(template_path, 'r') as f:
        html = f.read()

    html = html.replace('__USERNAME__', session['discord_username'])
    html = html.replace('__AVATAR_URL__', session.get('avatar') or '')
    return web.Response(content_type='text/html', charset='utf-8', text=html)


# ─── App factory ─────────────────────────────────────────────────────────────

def create_app(challonge_handler_factory, bot) -> web.Application:
    """
    Create and configure the aiohttp app.
    challonge_handler_factory: callable that takes a tournament_url and returns a ChallongeHandler
    bot: the ChonkBot instance
    """
    app = web.Application()
    app['challonge_handler_factory'] = challonge_handler_factory
    app['bot'] = bot

    # Auth routes
    app.router.add_get('/auth/login', handle_login)
    app.router.add_get('/auth/redirect', handle_oauth_redirect)
    app.router.add_get('/auth/callback', handle_oauth_callback)
    app.router.add_get('/auth/logout', handle_logout)

    # Dashboard
    app.router.add_get('/dashboard', handle_dashboard)

    # Seeding (existing token-based routes)
    app.router.add_get('/seeding', handle_seeding_page)
    app.router.add_get('/api/participants', handle_get_participants)
    app.router.add_post('/api/seed', handle_update_seed)

    assets_path = os.path.join(os.path.dirname(__file__), '..', 'assets')
    app.router.add_static('/assets', path=assets_path, name='assets')

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
    print(f"Server running on {host}:{port}")