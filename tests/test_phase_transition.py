"""Unit tests for EventManager phase transitions."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from bson import ObjectId

from tournaments.event_manager import EventManager


def _make_bot():
    bot = MagicMock()
    bot.guild = MagicMock()
    bot.dh = MagicMock()
    bot.dh.edit_tournament_config = AsyncMock()
    bot.dh.update_tournament_state = AsyncMock()
    bot.dh.get_swiss_event_by_tournament = AsyncMock(return_value=None)
    bot.dh.swiss_get_standings = AsyncMock(return_value=[])
    bot.dh.get_user = AsyncMock(return_value={'name': 'test_user'})
    bot.dh.tournament_collection = MagicMock()
    bot.dh.tournament_collection.update_one = AsyncMock()
    return bot


def _make_swiss_filter_event_with_standings():
    eid = ObjectId()
    return {
        '_id': eid,
        'name': 'Swiss Filter Test',
        'date': 'Saturday',
        'organizers': [1],
        'category_id': None,
        'debug': False,
        'state': 'active',
        'active_phase': 0,
        'registration_open': False,
        'entrants': {str(i): i for i in range(1, 17)},
        'checked_in': [],
        'dqs': [],
        'pending_teams': [],
        'config': {
            'approved_registration': False,
            'randomized_stagelist': False,
            'display_entrants': True,
            'ranked_reporting': False,
            'teams_mode': False,
            'staggered_start': False,
            'staggered_start_threshold': 16,
        },
        'stagelist': [],
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


def _make_standings(n: int = 16) -> list[dict]:
    return [
        {'discord_id': str(i + 1), 'points': n - i, 'dropped': False}
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_transition_raises_if_phase_not_finished():
    bot = _make_bot()
    event = _make_swiss_filter_event_with_standings()
    event['phases'][0]['state'] = 'active'  # not finished
    em = EventManager(bot, event)

    with pytest.raises(ValueError, match='not finished'):
        await em.transition_to_next_phase()


@pytest.mark.asyncio
async def test_transition_finishes_event_when_no_next_phases():
    bot = _make_bot()
    event = _make_swiss_filter_event_with_standings()
    # Remove waiting phases
    for p in event['phases']:
        p['state'] = 'finished'
    event['phases'][0]['state'] = 'finished'

    em = EventManager(bot, event)

    await em.transition_to_next_phase()

    bot.dh.update_tournament_state.assert_called_once_with(event['_id'], 'finished')


@pytest.mark.asyncio
async def test_get_phase_standings_returns_empty_without_tm():
    bot = _make_bot()
    event = _make_swiss_filter_event_with_standings()
    em = EventManager(bot, event)
    # No phase_managers loaded
    standings = await em._get_phase_standings(0)
    assert standings == []


@pytest.mark.asyncio
async def test_get_phase_standings_calls_swiss_get_standings():
    bot = _make_bot()
    event = _make_swiss_filter_event_with_standings()
    swiss_event = {'_id': ObjectId(), 'players': {}}
    bot.dh.get_swiss_event_by_tournament = AsyncMock(return_value=swiss_event)
    bot.dh.swiss_get_standings = AsyncMock(return_value=_make_standings())

    em = EventManager(bot, event)
    # Inject a mock TM for phase 0
    mock_tm = MagicMock()
    em.phase_managers[0] = mock_tm

    standings = await em._get_phase_standings(0)
    assert len(standings) == 16
    bot.dh.swiss_get_standings.assert_called_once_with(swiss_event['_id'])


@pytest.mark.asyncio
async def test_update_phase_state():
    bot = _make_bot()
    event = _make_swiss_filter_event_with_standings()
    em = EventManager(bot, event)

    await em._update_phase_state(1, 'active')

    bot.dh.tournament_collection.update_one.assert_called_once_with(
        {'_id': event['_id']},
        {'$set': {'phases.1.state': 'active'}}
    )


@pytest.mark.asyncio
async def test_finish_event_updates_state():
    bot = _make_bot()
    event = _make_swiss_filter_event_with_standings()
    em = EventManager(bot, event)

    await em._finish_event()

    bot.dh.update_tournament_state.assert_called_once_with(event['_id'], 'finished')
