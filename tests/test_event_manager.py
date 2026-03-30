"""Unit tests for EventManager — phase creation, config inheritance, player distribution."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId

from tournaments.event_manager import EventManager, _default_label


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_bot():
    bot = MagicMock()
    bot.guild = MagicMock()
    bot.dh = MagicMock()
    return bot


def _make_single_phase_event(fmt='swiss'):
    eid = ObjectId()
    return {
        '_id': eid,
        'name': 'Test Event',
        'date': 'Saturday',
        'organizers': [1],
        'category_id': None,
        'debug': False,
        'state': 'active',
        'active_phase': 0,
        'registration_open': False,
        'checked_in': ['100'],
        'dqs': [],
        'entrants': {'100': None, '200': None},
        'pending_teams': [],
        'config': {
            'approved_registration': False,
            'randomized_stagelist': True,
            'display_entrants': True,
            'ranked_reporting': False,
            'teams_mode': False,
            'staggered_start': False,
            'staggered_start_threshold': 16,
        },
        'stagelist': ['AAAA-BBBB'],
        'format': fmt,
        'round_limit': 3,
        'phases': [
            {
                'index': 0,
                'type': fmt,
                'label': _default_label(fmt),
                'state': 'active',
                'tournament_id': eid,
                'config_overrides': {},
                'round_limit': 3,
                'entrants': {'100': 1, '200': 2},
                **({'challonge_data': None} if fmt in ('single elimination', 'double elimination') else {}),
            }
        ],
    }


def _make_swiss_filter_event():
    eid = ObjectId()
    return {
        '_id': eid,
        'name': 'Swiss Filter Event',
        'date': 'Saturday',
        'organizers': [1],
        'category_id': None,
        'debug': False,
        'state': 'active',
        'active_phase': 0,
        'registration_open': False,
        'checked_in': [],
        'dqs': [],
        'entrants': {str(i): None for i in range(1, 17)},
        'pending_teams': [],
        'config': {
            'approved_registration': False,
            'randomized_stagelist': True,
            'display_entrants': True,
            'ranked_reporting': False,
            'teams_mode': False,
            'staggered_start': False,
            'staggered_start_threshold': 16,
        },
        'stagelist': ['AAAA-BBBB'],
        'format': 'swiss filter',
        'round_limit': 3,
        'phases': [
            {
                'index': 0,
                'type': 'swiss',
                'label': 'Swiss Rounds',
                'state': 'finished',
                'tournament_id': eid,
                'config_overrides': {},
                'round_limit': 3,
                'entrants': {str(i): i for i in range(1, 17)},
            },
            {
                'index': 1,
                'type': 'double elimination',
                'label': 'Top Bracket',
                'state': 'waiting',
                'tournament_id': None,
                'config_overrides': {},
                'player_source': {'phase_index': 0, 'placement': 'top', 'count': 8},
            },
            {
                'index': 2,
                'type': 'double elimination',
                'label': 'Middle Bracket',
                'state': 'waiting',
                'tournament_id': None,
                'config_overrides': {},
                'player_source': {'phase_index': 0, 'placement': 'middle', 'count': 4},
            },
            {
                'index': 3,
                'type': 'double elimination',
                'label': 'Lower Bracket',
                'state': 'waiting',
                'tournament_id': None,
                'config_overrides': {},
                'player_source': {'phase_index': 0, 'placement': 'bottom', 'count': None},
            },
        ],
    }


# ── Default label tests ───────────────────────────────────────────────────────

def test_default_label_known_formats():
    assert _default_label('swiss') == 'Swiss Rounds'
    assert _default_label('double elimination') == 'Double Elimination'
    assert _default_label('single elimination') == 'Single Elimination'
    assert _default_label('swiss filter') == 'Swiss Rounds'


def test_default_label_unknown_format():
    assert _default_label('some format') == 'Some Format'


# ── EventManager property tests ───────────────────────────────────────────────

def test_active_phase_index_default():
    bot = _make_bot()
    event = _make_single_phase_event()
    em = EventManager(bot, event)
    assert em.active_phase_index == 0


def test_active_phase_returns_correct_phase():
    bot = _make_bot()
    event = _make_swiss_filter_event()
    event['active_phase'] = 1
    em = EventManager(bot, event)
    assert em.active_phase['label'] == 'Top Bracket'


def test_is_multi_phase_false_for_single():
    bot = _make_bot()
    event = _make_single_phase_event()
    em = EventManager(bot, event)
    assert em.is_multi_phase is False


def test_is_multi_phase_true_for_swiss_filter():
    bot = _make_bot()
    event = _make_swiss_filter_event()
    em = EventManager(bot, event)
    assert em.is_multi_phase is True


def test_active_tm_none_when_not_initialized():
    bot = _make_bot()
    event = _make_single_phase_event()
    em = EventManager(bot, event)
    assert em.active_tm is None


# ── Config inheritance tests ──────────────────────────────────────────────────

def test_get_phase_config_uses_event_level():
    bot = _make_bot()
    event = _make_single_phase_event()
    em = EventManager(bot, event)
    assert em.get_phase_config(0, 'teams_mode') is False


def test_get_phase_config_override_wins():
    bot = _make_bot()
    event = _make_single_phase_event()
    event['phases'][0]['config_overrides']['teams_mode'] = True
    em = EventManager(bot, event)
    assert em.get_phase_config(0, 'teams_mode') is True


def test_get_phase_config_missing_key_returns_none():
    bot = _make_bot()
    event = _make_single_phase_event()
    em = EventManager(bot, event)
    assert em.get_phase_config(0, 'nonexistent_key') is None


def test_get_phase_stagelist_uses_event_level():
    bot = _make_bot()
    event = _make_single_phase_event()
    em = EventManager(bot, event)
    assert em.get_phase_stagelist(0) == ['AAAA-BBBB']


def test_get_phase_stagelist_override_wins():
    bot = _make_bot()
    event = _make_single_phase_event()
    event['phases'][0]['config_overrides']['stagelist'] = ['XXXX-YYYY']
    em = EventManager(bot, event)
    assert em.get_phase_stagelist(0) == ['XXXX-YYYY']


# ── _build_phase_tournament_doc tests ─────────────────────────────────────────

def test_build_phase_tournament_doc_basic():
    bot = _make_bot()
    event = _make_single_phase_event()
    em = EventManager(bot, event)
    doc = em._build_phase_tournament_doc(0)

    assert doc['format'] == 'swiss'
    assert doc['round_limit'] == 3
    assert doc['registration_open'] is False
    assert doc['stagelist'] == ['AAAA-BBBB']
    assert doc['name'] == 'Test Event'
    assert doc['debug'] is False


def test_build_phase_tournament_doc_merges_config_overrides():
    bot = _make_bot()
    event = _make_single_phase_event()
    event['phases'][0]['config_overrides']['teams_mode'] = True
    em = EventManager(bot, event)
    doc = em._build_phase_tournament_doc(0)
    assert doc['config']['teams_mode'] is True


def test_build_phase_tournament_doc_no_round_limit_for_de():
    bot = _make_bot()
    event = _make_swiss_filter_event()
    em = EventManager(bot, event)
    doc = em._build_phase_tournament_doc(1)  # DE phase
    assert 'round_limit' not in doc


# ── Player distribution tests ─────────────────────────────────────────────────

def _make_standings(n: int) -> list[dict]:
    """Generate n standings entries."""
    return [
        {'discord_id': str(i + 1), 'points': n - i, 'dropped': False}
        for i in range(n)
    ]


def test_select_players_top():
    bot = _make_bot()
    event = _make_swiss_filter_event()
    em = EventManager(bot, event)
    standings = _make_standings(16)
    phase_def = event['phases'][1]  # top, count=8
    result = em._select_players_for_phase(standings, phase_def)
    assert len(result) == 8
    assert result[0] == '1'
    assert result[7] == '8'


def test_select_players_middle():
    bot = _make_bot()
    event = _make_swiss_filter_event()
    em = EventManager(bot, event)
    standings = _make_standings(16)
    phase_def = event['phases'][2]  # middle, count=4
    result = em._select_players_for_phase(standings, phase_def)
    assert len(result) == 4
    # Middle starts at top_count (=count=4) through 4+4=8
    assert result[0] == '5'
    assert result[3] == '8'


def test_select_players_bottom_remaining():
    bot = _make_bot()
    event = _make_swiss_filter_event()
    em = EventManager(bot, event)
    standings = _make_standings(16)
    phase_def = event['phases'][3]  # bottom, count=None
    result = em._select_players_for_phase(standings, phase_def)
    # claimed = top(8) + middle(4) = 12, remaining = 4
    assert len(result) == 4
    assert result[0] == '13'


def test_select_players_excludes_dropped():
    bot = _make_bot()
    event = _make_swiss_filter_event()
    em = EventManager(bot, event)
    standings = _make_standings(10)
    # Drop first 2 players
    standings[0]['dropped'] = True
    standings[1]['dropped'] = True
    phase_def = event['phases'][1]  # top, count=8
    result = em._select_players_for_phase(standings, phase_def)
    assert len(result) == 8
    assert '1' not in result
    assert '2' not in result
    assert '3' in result
