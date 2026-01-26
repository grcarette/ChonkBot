from .base import DataHandlerBase
from .users import UserMethodsMixin
from .tournaments import TournamentMethodsMixin
from .stats import StatsMethodsMixin
from .lobby import LobbyMethodsMixin
from .stage import StageMethodsMixin
from .stats_data import StatsDataMethodsMixin
from .tsc import TSCDataMethodsMixin


from utils.errors import *
from utils.emojis import EMOJI_NUMBERS

from datetime import datetime, timezone, timedelta
from collections import defaultdict

import motor.motor_asyncio
import asyncio
import math

class DataHandler(
    DataHandlerBase, 
    UserMethodsMixin, 
    TournamentMethodsMixin, 
    StatsMethodsMixin, 
    LobbyMethodsMixin, 
    StageMethodsMixin,
    StatsDataMethodsMixin,
    TSCDataMethodsMixin,
    ):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()    
        client = motor.motor_asyncio.AsyncIOMotorClient("mongodb://localhost:27017")
        
        self.db = client['ChonkBot']
        self.reaction_collection = self.db['reaction_flags']
        self.tournament_collection = self.db['tournaments']
        self.register_flag_collection = self.db['register_flags']
        self.party_map_collection = self.db['party_maps']
        self.level_collection = self.db['levels']
        self.lobby_collection = self.db['lobbies']
        self.user_collection = self.db['users']
        self.ratings_collection = self.db['level_ratings']
        self.tsc_collection = self.db['tsc']
        self.time_collection = self.db['tsc_times']
        
        self.tdb = client['UCHTournamentData']
        self.match_collection = self.tdb['matches']
        self.player_collection = self.tdb['players']
        self.tournament_data_collection = self.tdb['tournaments']