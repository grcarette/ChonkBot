# tests/test_challonge_handler.py
import pytest
import asyncio
from unittest.mock import patch, MagicMock
from tournaments.challonge_handler import ChallongeHandler

# A fake tournament object the mock will return
FAKE_TOURNAMENT = {
    'id': 123,
    'url': 'fake-tournament-url',
    'state': 'pending',
    'name': 'Test Tournament'
}

FAKE_PARTICIPANTS = [
    {'id': 1, 'name': 'Player1', 'final_rank': 1},
    {'id': 2, 'name': 'Player2', 'final_rank': 2},
]

@pytest.mark.asyncio
async def test_start_tournament_calls_start():
    with patch('challonge.tournaments.show', return_value=FAKE_TOURNAMENT) as mock_show, \
         patch('challonge.tournaments.start') as mock_start:
        
        ch = ChallongeHandler('fake-url')
        await ch.start_tournament(123)
        
        mock_show.assert_called_once_with(123)
        mock_start.assert_called_once_with(123)

@pytest.mark.asyncio
async def test_start_tournament_skips_if_not_pending():
    already_started = {**FAKE_TOURNAMENT, 'state': 'underway'}
    with patch('challonge.tournaments.show', return_value=already_started), \
         patch('challonge.tournaments.start') as mock_start:
        
        ch = ChallongeHandler('fake-url')
        await ch.start_tournament(123)
        
        mock_start.assert_not_called()  # Should bail out early

@pytest.mark.asyncio
async def test_get_final_results_sorted():
    shuffled = [
        {'id': 2, 'name': 'Player2', 'final_rank': 2},
        {'id': 1, 'name': 'Player1', 'final_rank': 1},
    ]
    with patch('challonge.participants.index', return_value=shuffled):
        ch = ChallongeHandler('fake-url')
        results = await ch.get_final_results(123)
        
        assert results[0]['final_rank'] == 1  # Should be sorted
        assert results[1]['final_rank'] == 2