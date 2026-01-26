import motor.motor_asyncio
from data.level_api import LevelAPI

class DataHandlerBase:
    def __init__(self):
        client = motor.motor_asyncio.AsyncIOMotorClient("mongodb://localhost:27017")
        
        self.db = client['ChonkBot']
        self.reaction_collection = self.db['reaction_flags']
        self.tournament_collection = self.db['tournaments']
        self.lobby_collection = self.db['lobbies']
        self.user_collection = self.db['users']

        self.level_api = LevelAPI()