from .base import DataHandlerBase
from .users import UserMethodsMixin
from .tournaments import TournamentMethodsMixin
from .lobby import LobbyMethodsMixin
from .stage import StageMethodsMixin



from utils.errors import *
from utils.emojis import EMOJI_NUMBERS

from datetime import datetime, timezone, timedelta
from collections import defaultdict

import motor.motor_asyncio
import asyncio
import math
import os

from dotenv import load_dotenv

class DataHandler(
    DataHandlerBase, 
    UserMethodsMixin, 
    TournamentMethodsMixin, 
    LobbyMethodsMixin, 
    StageMethodsMixin,
    ):
    def __init__(self):
        super().__init__()    
        load_dotenv()
        mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
        self.client = motor.motor_asyncio.AsyncIOMotorClient(mongo_uri)

        self.db = self.client['ChonkBot']
        self.reaction_collection = self.db['reaction_flags']
        self.tournament_collection = self.db['tournaments']
        self.register_flag_collection = self.db['register_flags']
        self.lobby_collection = self.db['lobbies']
        self.user_collection = self.db['users']


        
        # self.tdb = client['UCHTournamentData']
        # self.match_collection = self.tdb['matches']
        # self.player_collection = self.tdb['players']
        # self.tournament_data_collection = self.tdb['tournaments']