import os
import asyncio
import secrets
from datetime import datetime, timezone, timedelta
from aiohttp import web
 
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
 
 
async def handle_seeding_page(request: web.Request) -> web.Response:
    """Serve the seeding HTML page if the token is valid."""
    token = request.query.get('token')
    if not token or not validate_token(token):
        return web.Response(
            status=403,
            text="Invalid or expired token. Please generate a new link from Discord."
        )
 
    template_path = os.path.join(os.path.dirname(__file__), 'templates', 'seeding.html')
    with open(template_path, 'r') as f:
        html = f.read()
 
    # Inject the token into the page so JS can use it for API calls
    html = html.replace('__TOKEN__', token)
    return web.Response(content_type='text/html', text=html)
 
 
async def handle_get_participants(request: web.Request) -> web.Response:
    """Return participants for the tournament associated with the token."""
    token = request.query.get('token')
    token_data = validate_token(token) if token else None
    if not token_data:
        return web.json_response({'error': 'Invalid or expired token'}, status=403)
 
    challonge_handler = request.app['challonge_handler_factory'](token_data['challonge_url'])
    try:
        participants = await challonge_handler.get_participants(token_data['challonge_url'])
        participants_sorted = sorted(participants, key=lambda p: p.get('seed') or 999)
        result = [
            {'id': p['id'], 'name': p['name'], 'seed': p.get('seed')}
            for p in participants_sorted
        ]
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
 
 
def create_app(challonge_handler_factory) -> web.Application:
    """
    Create and configure the aiohttp app.
    challonge_handler_factory: callable that takes a tournament_url and returns a ChallongeHandler
    """
    app = web.Application()
    app['challonge_handler_factory'] = challonge_handler_factory
 
    app.router.add_get('/seeding', handle_seeding_page)
    app.router.add_get('/api/participants', handle_get_participants)
    app.router.add_post('/api/seed', handle_update_seed)
 
    return app
 
 
async def start_server(challonge_handler_factory):
    """Start the aiohttp server. Called from bot.py on_ready."""
    host = os.getenv('WEB_HOST', '0.0.0.0')
    port = int(os.getenv('PORT', os.getenv('WEB_PORT', 8080)))
 
    app = create_app(challonge_handler_factory)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    print(f"Seeding server running on {host}:{port}")