from aiohttp import web
from web.auth import get_oauth_url, exchange_code, fetch_discord_user, is_to, SESSION_COOKIE

SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days


async def handle_login(request: web.Request) -> web.Response:
    """Redirect the user to Discord's OAuth page."""
    raise web.HTTPFound(get_oauth_url())


async def handle_callback(request: web.Request) -> web.Response:
    """
    Handle the OAuth callback from Discord.
    Exchanges the code for a token, fetches the user's identity,
    checks they have the TO role, then sets a session cookie.
    """
    code = request.query.get('code')
    if not code:
        return web.Response(status=400, text='Missing OAuth code.')

    token_data = await exchange_code(code)
    if not token_data:
        return web.Response(status=500, text='Failed to exchange OAuth code. Please try again.')

    discord_user = await fetch_discord_user(token_data['access_token'])
    if not discord_user:
        return web.Response(status=500, text='Failed to fetch Discord user. Please try again.')

    bot = request.app['bot']
    discord_id = int(discord_user['id'])

    if not is_to(bot, discord_id):
        return web.Response(status=403, text='Access denied. You do not have the TO role.')

    avatar_hash = discord_user.get('avatar')
    avatar_url = (
        f"https://cdn.discordapp.com/avatars/{discord_id}/{avatar_hash}.png"
        if avatar_hash else None
    )

    session_token = await bot.dh.create_session(
        discord_id=discord_id,
        username=discord_user['username'],
        avatar=avatar_url,
    )

    response = web.HTTPFound('/')
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite='Lax',
    )
    return response


async def handle_logout(request: web.Request) -> web.Response:
    """Clear the session from the DB and delete the cookie."""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await request.app['bot'].dh.delete_session(token)

    response = web.HTTPFound('/auth/login')
    response.del_cookie(SESSION_COOKIE)
    return response