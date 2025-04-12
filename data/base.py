import motor.motor_asyncio

class DataHandlerBase:
    def __init__(self):
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
        
        self.tdb = client['UCHTournamentData']
        self.match_collection = self.tdb['matches']
        self.player_collection = self.tdb['players']
        self.tournament_data_collection = self.tdb['tournaments']