import pytest
from unittest.mock import AsyncMock
from utils.errors import *
from handlers.data_handler import DataHandler

@pytest.mark.asyncio
async def test_get_tournament_not_found():
    mock_collection = AsyncMock()
    mock_collection.find_one.return_value = None

    data_handler = DataHandler()
    data_handler.tournament_collection = mock_collection

    with pytest.raises(TournamentNotFoundError):
        await data_handler.get_tournament(name='test')

@pytest.mark.asyncio
async def test_get_tournament_found():
    mock_collection = AsyncMock()
    mock_collection.find_one.return_value = {'name': 'test', 'date': '2025-01-01'}

    data_handler = DataHandler()
    data_handler.tournament_collection = mock_collection
    tournament = await data_handler.get_tournament(name='test')
    assert tournament['name'] == 'test'
    
@pytest.mark.asyncio
async def test_get_tournament():
    dh = DataHandler()
    t = await dh.get_tournament(message_id=1352637591756738713)
    