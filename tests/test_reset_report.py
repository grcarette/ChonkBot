"""
tests/test_reset_report.py

Tests for TournamentManager.reset_report.

Verifies:
- Swiss events never call ch.reset_match
- DE events do call ch.reset_match
- The lobby's own reset_report is always called regardless of format
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def make_tm_with_lobby(format='double elimination'):
    from tournaments.tournament_manager import TournamentManager

    # Fake lobby object
    mock_lobby = AsyncMock()
    mock_lobby.match_id = 55

    tournament = {
        '_id': 'tid',
        'name': 'Test',
        'format': format,
        'challonge_data': {'id': 'chid'},
    }

    tm = object.__new__(TournamentManager)
    tm.tournament = tournament
    tm.lobbies = {55: mock_lobby}
    tm.ch = AsyncMock()
    tm.bot = MagicMock()
    tm.bot.dh = AsyncMock()
    tm.bot.dh.get_tournament_by_id = AsyncMock(return_value=tournament)

    return tm, mock_lobby


@pytest.mark.asyncio
async def test_de_reset_report_calls_challonge():
    tm, mock_lobby = make_tm_with_lobby(format='double elimination')
    await tm.reset_report({'lobby': {'match_id': 55}})
    tm.ch.reset_match.assert_awaited_once_with('chid', 55)


@pytest.mark.asyncio
async def test_swiss_reset_report_does_not_call_challonge():
    tm, mock_lobby = make_tm_with_lobby(format='swiss')
    await tm.reset_report({'lobby': {'match_id': 55}})
    tm.ch.reset_match.assert_not_awaited()


@pytest.mark.asyncio
async def test_reset_report_always_calls_lobby_reset():
    for fmt in ('double elimination', 'swiss', 'single elimination'):
        tm, mock_lobby = make_tm_with_lobby(format=fmt)
        await tm.reset_report({'lobby': {'match_id': 55}})
        mock_lobby.reset_report.assert_awaited_once()
        mock_lobby.reset_report.reset_mock()