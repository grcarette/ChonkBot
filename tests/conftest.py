# tests/conftest.py

import pytest


# ─── pytest-asyncio mode ─────────────────────────────────────────────────────
# Requires: pip install pytest-asyncio
# Add to pytest.ini or pyproject.toml:
#   [tool.pytest.ini_options]
#   asyncio_mode = "auto"
#
# Or keep this here to set it programmatically.

def pytest_configure(config):
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )


# ─── Shared player factory (mirrors test_swiss_pairing.py) ───────────────────

def make_player(discord_id, points, elo, match_history=None, dropped=False, active_match_id=None):
    return {
        'discord_id': discord_id,
        'username': f'player_{discord_id}',
        'points': float(points),
        'elo': elo,
        'wins': int(points),
        'losses': 0,
        'rounds_played': int(points),
        'match_history': match_history or [],
        'dropped': dropped,
        'active_match_id': active_match_id,
    }


# ─── Shared tournament factory ────────────────────────────────────────────────

def make_tournament_doc(format='double elimination', state='active', tid='tid001'):
    return {
        '_id': tid,
        'name': 'Test Tournament',
        'format': format,
        'state': state,
        'entrants': {},
        'checked_in': [],
        'dqs': [],
        'stagelist': [],
        'organizers': [],
        'config': {
            'approved_registration': False,
            'randomized_stagelist': False,
        },
        'registration_open': False,
        'debug': False,
    }