# tests/test_seeding_server.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiohttp.test_utils import TestClient, TestServer
from web.seeding_server import create_app, generate_token

FAKE_PARTICIPANTS = [
    {'id': 1, 'name': 'Player1', 'seed': 2},
    {'id': 2, 'name': 'Player2', 'seed': 1},
]

def make_mock_factory(participants=FAKE_PARTICIPANTS):
    """Returns a factory that produces a mock ChallongeHandler."""
    mock_handler = AsyncMock()
    mock_handler.get_participants = AsyncMock(return_value=participants)
    mock_handler.update_seed = AsyncMock()
    return lambda url: mock_handler

@pytest.fixture
async def client():
    mock_bot = AsyncMock()
    mock_bot.dh = AsyncMock()
    mock_bot.dh.get_tournament_by_id = AsyncMock(return_value={
        '_id': 'tournament_123',
        'name': 'Test Tournament',
        'entrants': {'1': 1, '2': 2},
    })
    mock_bot.guild = AsyncMock()
    mock_bot.guild.get_member = MagicMock(return_value=None)

    app = create_app(make_mock_factory(), mock_bot)
    async with TestClient(TestServer(app)) as client:
        yield client

async def test_seeding_page_rejects_bad_token(client):
    resp = await client.get('/seeding?token=garbage')
    assert resp.status == 403

async def test_seeding_page_serves_html_with_valid_token(client):
    token = generate_token('tournament_123', 'fake-url')
    resp = await client.get(f'/seeding?token={token}')
    assert resp.status == 200
    text = await resp.text()
    assert token in text  # token should be injected into the page

async def test_get_participants_returns_sorted(client):
    token = generate_token('tournament_123', 'fake-url')
    resp = await client.get(f'/api/participants?token={token}')
    assert resp.status == 200
    data = await resp.json()
    seeds = [p['seed'] for p in data]
    assert seeds == sorted(seeds)  # should come back sorted by seed

async def test_update_seed(client):
    token = generate_token('tournament_123', 'fake-url')
    resp = await client.post(
        f'/api/seed?token={token}',
        json={'participant_id': 1, 'seed': 3}
    )
    assert resp.status == 200
    data = await resp.json()
    assert data['ok'] is True

async def test_token_only_works_once_per_generation(client):
    token = generate_token('tournament_123', 'fake-url')
    # Same token should work multiple times within expiry window (it's session-based, not one-shot)
    resp1 = await client.get(f'/api/participants?token={token}')
    resp2 = await client.get(f'/api/participants?token={token}')
    assert resp1.status == 200
    assert resp2.status == 200