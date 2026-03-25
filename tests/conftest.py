# tests/conftest.py
"""
Shared fixtures and factories used across the test suite.
"""
# tests/conftest.py
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))



def make_player_doc(discord_id, points=0, elo=1000, dropped=False,
                    active_match_id=None, match_history=None, wins=None, losses=0):
    return {
        'discord_id': discord_id,
        'username': f'player_{discord_id}',
        'elo': elo,
        'points': float(points),
        'wins': int(points) if wins is None else wins,
        'losses': losses,
        'rounds_played': int(points) if wins is None else wins,
        'active_match_id': active_match_id,
        'dropped': dropped,
        'match_history': match_history or [],
    }


def make_tournament_doc(fmt='double elimination', state='active', tid='tid001', debug=False):
    return {
        '_id': tid,
        'name': 'Test Tournament',
        'format': fmt,
        'state': state,
        'entrants': {},
        'checked_in': [],
        'dqs': [],
        'stagelist': ['s1', 's2', 's3'],
        'organizers': [999],
        'config': {
            'approved_registration': False,
            'randomized_stagelist': False,
            'display_entrants': False,
            'ranked_reporting': False,
        },
        'registration_open': False,
        'debug': debug,
        'round_limit': 3,
    }


def make_swiss_event(players=None, current_round=0, round_limit=3, state='active'):
    if players is None:
        players = {
            str(i): make_player_doc(i)
            for i in range(4)
        }
    return {
        '_id': 'eid',
        'tournament_id': 'tid001',
        'state': state,
        'current_round': current_round,
        'round_limit': round_limit,
        'players': players,
        'matches': [],
        'bye_queue': None,
        'next_match_sequence': 0,
    }