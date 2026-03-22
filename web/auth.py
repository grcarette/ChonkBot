import os
import secrets
import httpx
from datetime import datetime, timezone, timedelta
from aiohttp import web
from functools import wraps

DISCORD_API_BASE = 'https://discord.com/api/v10'
SESSION_EXPIRY_DAYS = 7


# ─── Discord OAuth helpers ────────────────────────────────────────────────────

def get_discord_oauth_url() -> str:
    client_id = os.getenv('DISCORD_CLIENT_ID')
    redirect_uri = os.getenv('DISCORD_REDIRECT_URI')
    scope = 'identify'
    return (
        f'https://discord.com/oauth2/authorize'
        f'?client_id={client_id}'
        f'&redirect_uri={redirect_uri}'
        f'&response_type=code'
        f'&scope={scope}'
    )


async def exchange_code_for_token(code: str) -> dict | None:
    """Exchange an OAuth code for an access token from Discord."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f'{DISCORD_API_BASE}/oauth2/token',
            data={
                'client_id': os.getenv('DISCORD_CLIENT_ID'),
                'client_secret': os.getenv('DISCORD_CLIENT_SECRET'),
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': os.getenv('DISCORD_REDIRECT_URI'),
            },
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
        )
        if response.status_code != 200:
            return None
        return response.json()


async def get_discord_user(access_token: str) -> dict | None:
    """Fetch the Discord user's identity using their access token."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f'{DISCORD_API_BASE}/users/@me',
            headers={'Authorization': f'Bearer {access_token}'},
        )
        if response.status_code != 200:
            return None
        return response.json()


def is_tournament_organizer(bot, discord_user_id: int) -> bool:
    """Check whether the Discord user has the TO role in the guild."""
    member = bot.guild.get_member(discord_user_id)
    if not member:
        return False
    organizer_role_name = os.getenv('ORGANIZER_ROLE_NAME', 'Tournament Organizer')
    return any(role.name == organizer_role_name for role in member.roles)


# ─── Session helpers ──────────────────────────────────────────────────────────

async def create_session(dh, discord_user_id: int, discord_username: str, avatar: str | None) -> str:
    """Create a new session in the DB and return the session token."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=SESSION_EXPIRY_DAYS)
    await dh.create_session(token, discord_user_id, discord_username, avatar, expires_at)
    return token


async def get_session(dh, token: str) -> dict | None:
    """Return the session document if valid and not expired."""
    if not token:
        return None
    session = await dh.get_session(token)
    if not session:
        return None
    expires_at = session['expires_at']
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires_at:
        await dh.delete_session(token)
        return None
    return session


# ─── Auth middleware / decorator ──────────────────────────────────────────────

def require_auth(handler):
    """Decorator for aiohttp route handlers that require a valid session."""
    @wraps(handler)
    async def wrapper(request: web.Request):
        token = request.cookies.get('session')
        dh = request.app['bot'].dh
        session = await get_session(dh, token)
        if not session:
            raise web.HTTPFound('/auth/login')
        request['session'] = session
        return await handler(request)
    return wrapper


# ─── Route handlers ───────────────────────────────────────────────────────────

async def handle_login(request: web.Request) -> web.Response:
    """Serve the login page, or redirect to dashboard if already logged in."""
    token = request.cookies.get('session')
    if token:
        dh = request.app['bot'].dh
        session = await get_session(dh, token)
        if session:
            raise web.HTTPFound('/dashboard')

    error = request.query.get('error')
    error_messages = {
        'missing_code': 'OAuth code missing. Please try again.',
        'token_exchange_failed': 'Failed to communicate with Discord. Please try again.',
        'user_fetch_failed': 'Could not retrieve your Discord profile. Please try again.',
        'unauthorized': 'You do not have the Tournament Organizer role.',
    }
    error_message = error_messages.get(error, '')

    template_path = os.path.join(os.path.dirname(__file__), 'templates', 'login.html')
    with open(template_path, 'r') as f:
        html = f.read()
    html = html.replace('__ERROR_MESSAGE__', error_message)
    return web.Response(content_type='text/html', charset='utf-8', text=html)


async def handle_oauth_redirect(request: web.Request) -> web.Response:
    """Redirect the browser to Discord's OAuth authorization URL."""
    raise web.HTTPFound(get_discord_oauth_url())


async def handle_oauth_callback(request: web.Request) -> web.Response:
    """Handle the OAuth callback: exchange code, verify TO role, set session cookie."""
    code = request.query.get('code')
    if not code:
        raise web.HTTPFound('/auth/login?error=missing_code')

    token_data = await exchange_code_for_token(code)
    if not token_data:
        raise web.HTTPFound('/auth/login?error=token_exchange_failed')

    discord_user = await get_discord_user(token_data['access_token'])
    if not discord_user:
        raise web.HTTPFound('/auth/login?error=user_fetch_failed')

    bot = request.app['bot']
    discord_user_id = int(discord_user['id'])

    if not is_tournament_organizer(bot, discord_user_id):
        raise web.HTTPFound('/auth/login?error=unauthorized')

    avatar_hash = discord_user.get('avatar')
    avatar_url = (
        f"https://cdn.discordapp.com/avatars/{discord_user['id']}/{avatar_hash}.png"
        if avatar_hash else None
    )

    session_token = await create_session(
        dh=bot.dh,
        discord_user_id=discord_user_id,
        discord_username=discord_user['username'],
        avatar=avatar_url,
    )

    response = web.HTTPFound('/dashboard')
    response.set_cookie(
        'session',
        session_token,
        max_age=SESSION_EXPIRY_DAYS * 86400,
        httponly=True,
        samesite='Lax',
    )
    raise response


async def handle_logout(request: web.Request) -> web.Response:
    """Clear the session from the DB and delete the cookie."""
    token = request.cookies.get('session')
    if token:
        await request.app['bot'].dh.delete_session(token)
    response = web.HTTPFound('/auth/login')
    response.del_cookie('session')
    raise response