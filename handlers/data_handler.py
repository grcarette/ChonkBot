from utils.errors import *
from utils.emojis import EMOJI_NUMBERS

import motor.motor_asyncio
import asyncio
import random
import re

class DataHandler:
    def __init__(self):
        client = motor.motor_asyncio.AsyncIOMotorClient("mongodb://localhost:27017")
        self.db = client['ChonkBot']
        self.reaction_collection = self.db['reaction_flags']
        self.tournament_collection = self.db['tournaments']
        self.register_flag_collection = self.db['register_flags']
        self.party_map_collection = self.db['party_maps']
        self.lobby_collection = self.db['lobbies']
        self.user_collection = self.db['users']
        
        self.tdb = client['UCHTournamentData']
        self.match_collection = self.tdb['matches']
        self.player_collection = self.tdb['players']
        self.tournament_data_collection = self.tdb['tournaments']
        
    async def add_reaction_flag(self, message_id, flag_type, emojis, user_filter=False, require_all_to_react=False, value=None, timestamp=None):
        if user_filter:
            if not isinstance(user_filter, list):
                user_filter = [user_filter]
            filtered_user_ids = [user for user in user_filter]
        else:
            filtered_user_ids = False
            
        if not isinstance(emojis, list):
            emojis = [emojis]
        emoji_reactions = {}
        for emoji in emojis:
            emoji_reactions[emoji] = []
            
        query = {
            'message_id': message_id,
            'type': flag_type
        }
        flag_exists = await self.reaction_collection.find_one(query)
        
        if flag_exists:
            update = {
                "$set": {
                    f"emojis.{emoji}": [] for emoji in emoji_reactions.keys()
                }
            }
            await self.reaction_collection.update_one(query, update)
        else:
            reaction_flag = {
                'message_id': message_id,
                'type': flag_type,
                'users': filtered_user_ids,
                'has_confirmation': False,
                'require_all_to_react': require_all_to_react,
                'emojis': emoji_reactions,
                'value': value,
                'timestamp': timestamp,
            }
            await self.reaction_collection.insert_one(reaction_flag)
    
    async def update_reaction_to_flag(self, message_id, emoji, userid, reaction_added):
        query = {
            'message_id': message_id
        }
        if reaction_added:
            update = {
                "$push": {
                    f'emojis.{emoji}': userid
                    }
            }
        else:
            update = {
                "$pull": {
                    f'emojis.{emoji}': userid
                }
            }
        result = await self.reaction_collection.update_one(query, update)
        updated_flag = await self.reaction_collection.find_one(query)
        return updated_flag
    
    async def add_confirmation_to_flag(self, message_id):
        query = {
            'message_id': message_id
        }
        update = {
            '$set': {'has_confirmation': True}
        }
        result = await self.reaction_collection.update_one(query, update)
        return result
    
    async def get_reaction_flag(self, payload=False, message_id=False):
        if payload:
            message_id = payload.message_id
            user_id = payload.user_id
            query = {
                'message_id': message_id,
                '$or': [
                    {'users': None},
                    {'users': {'$in': [user_id]}}  
                ]
            }
        if message_id:
            query = {
                'message_id': message_id
            }
        reaction_flags = await self.reaction_collection.find_one(query)
        return reaction_flags
    
    async def remove_reaction_flag(self, message_id):
        query = {
            'message_id': message_id
        }
        result = await self.reaction_collection.delete_one(query)
        return result
    
    async def create_tournament(self, name, date, organizer, message_id=None):
        tournament_exists = await self.tournament_collection.find_one({'name': name})
        if tournament_exists:
            raise TournamentExistsError(f"Error: Tournament name '{name}' already exists.")
        tournament = {
            'name': name,
            'date': date,
            'organizer': organizer,
            'message_id': message_id,
            'format': 'TBA',
            'check-in': False,
            'approved_registration': False,
            'randomized_stagelist': False,
            'require_stage_bans': False,
            'hide_channels': False,
            'stagelist': [],
            'entrants': []
        }
        result = await self.tournament_collection.insert_one(tournament)
        
    async def update_tournament(self, message_id, update):
        query = {
            'message_id': message_id
        }
        result = await self.tournament_collection.update_one(query, update)
        return result
    
    async def add_category_to_tournament(self, tournament_name, category_id):
        query = {
            'name': tournament_name
        }
        update = {
            '$set': {'category_id': category_id}
        }
        result = await self.tournament_collection.update_one(query, update)
        return result
    
    async def add_stages_to_tournament(self, tournament_name, stages):
        stage_codes = [stage['code'] for stage in stages]
        query = {
            'name': tournament_name,
        }
        update = {
            '$push': {
                'stagelist': {
                    '$each': stage_codes
                }
            }
        }
        result = await self.tournament_collection.update_one(query, update)
        return result
    
    async def get_tournament(self, **kwargs):
        tournament = await self.tournament_collection.find_one(kwargs)
        if tournament:
            return tournament
        else:
            key, value = next(iter(kwargs.items()))
            raise TournamentNotFoundError(f"Error: Tournament with {key}: {value} not found")
        
    async def create_registration_flag(self, channel_id, tournament_name, require_approval):
        register_flag_data = {
            'channel_id': channel_id,
            'tournament_name': tournament_name,
            'require_approval': require_approval
        }
        register_flag = await self.register_flag_collection.insert_one(register_flag_data)
        return register_flag
    
    async def remove_registration_flag(self, channel_id):
        query = {
            'channel_id': channel_id
        }
        result = await self.register_flag_collection.delete_one(query)
        return result
    
    async def get_registration_flag(self, channel_id):
        query = {
            'channel_id': channel_id
        }
        registration_flag = await self.register_flag_collection.find_one(query)
        return registration_flag
    
    async def register_player(self, tournament_name, player_id):
        query = {
            'name': tournament_name,
            'entrants': player_id
        }
        player_exists = await self.tournament_collection.find_one(query)
        
        if not player_exists:
            query = {
                'name': tournament_name
            }
            update = {
                "$addToSet": {'entrants': player_id}
            }
            result = await self.tournament_collection.update_one(query, update)
            return result
        else:
            return False
    
    async def unregister_player(self, tournament_name, player_id):
        query = {
            'name': tournament_name
        }
        update = {
            '$pull': {'entrants': player_id}
        }
        result = await self.tournament_collection.update_one(query, update)
        return result
    
    async def get_stage(self, **kwargs):
        map = await self.party_map_collection.find_one(kwargs)
        if map:
            return map
        else:
            key, value = next(iter(kwargs.items()))
            raise TournamentNotFoundError(f"Error: Tournament with {key}: {value} not found")
    
    async def get_random_stages(self, number, user=False):
        if user:
            user_info = await self.user_collection.find_one({'user_id': user.id})
            if not user_info:
                user_info = await self.register_user(user)
            query = {
                'code': {
                    '$nin': user_info['blocked_maps']
                }
            }
        else:
            query = {}
            
        pipeline = [
            {'$match': query},
            {"$sample": {
                "size": number
            }}
        ]
        
        random_stages = await self.party_map_collection.aggregate(pipeline).to_list(None)
        
        if len(random_stages) == 0:
            raise NoStagesFoundError
        return random_stages
    
    async def create_lobby(self, tournament_name, players, pool=None):
        player_ids = [player.id for player in players]
        query = {
            'tournament': tournament_name
        }
        lobby_id = await self.lobby_collection.count_documents(query) + 1
        lobby_data = {
            'lobby_id': lobby_id,
            'tournament': tournament_name,
            'pool': pool,
            'stage': 'initialize',
            'players': player_ids,
            'stage_bans': [],
            'results': [],
        }
        lobby = await self.lobby_collection.insert_one(lobby_data)
        return lobby_id
    
    async def reset_lobby(self, channel_id, last_result_only=False):
        query = {
            'channel_id': channel_id
        }
        if last_result_only:
            update = {
                "$pop": {
                    'results': 1
                },
                "$set": {
                    'stage': 'stage_bans'
                }
            }
        else:
            update = {
                "$set": {
                    'stage': 'checkin',
                    'stage_bans': [],
                    'results': []
                }
            }
        result = await self.lobby_collection.update_one(query, update)
        lobby = await self.lobby_collection.find_one(query)
        return lobby
        
    async def ban_stage(self, channel_id, banned_stage):
        query = {
            'channel_id': channel_id
        }
        update = {
            '$push': {
                'stage_bans': banned_stage
            }
        }
        result = await self.lobby_collection.update_one(query, update)
        lobby = await self.lobby_collection.find_one(query)
        return lobby
    
    async def report_match(self, channel_id, payload):
        query = {
            'channel_id': channel_id
        }
        lobby = await self.lobby_collection.find_one(query)
        
        emoji = payload.emoji.name
        player_index = EMOJI_NUMBERS[emoji] - 1
        winning_player = lobby['players'][player_index]

        update = {
            '$push': {
                'results': winning_player
            }
        }
        result = await self.lobby_collection.update_one(query, update)
        return result
    
    
    async def remove_lobby(self, lobby_id):
        query = {
            'lobby_id': lobby_id
        }
        result = await self.lobby_collection.delete_one(query)
        return result
    
    async def get_lobby(self, lobby_id=False, tournament_name=False, channel_id=False):
        if channel_id:
            query = {
                'channel_id': channel_id
            }
        else:
            query = {
                'lobby_id': lobby_id,
                'tournament': tournament_name
            }
        lobby = await self.lobby_collection.find_one(query)
        return lobby
        
    async def add_channel_to_lobby(self, lobby_id, channel_id):
        query = {
            'lobby_id': lobby_id
        }
        update = {
            "$set": {
                'channel_id': channel_id
            }
        }
        result = await self.lobby_collection.update_one(query, update)
        return result

    async def advance_lobby(self, channel_id, stage):
        query = {
            'channel_id': channel_id
        }
        update = {
            '$set': {
                'stage': stage
            }
        }
        result = await self.lobby_collection.update_one(query, update)
        lobby = await self.lobby_collection.find_one(query)
        return lobby
    
    async def register_user(self, user):
        query = {
            'user_id': user.id
        }
        user_exists = await self.user_collection.find_one(query)
        if not user_exists:
            user_data = {
                'user_id': user.id,
                'name': user.name,
                'mention': user.mention,
                'favorite_maps': [],
                'blocked_maps': []
            }
            result = await self.user_collection.insert_one(user_data)
            user = await self.user_collection.find_one(query)
            return user
    
    async def get_user(self, **kwargs):
        user = await self.user_collection.find_one(kwargs)
        if user:
            return user
        else:
            key, value = next(iter(kwargs.items()))
            raise UserNotFoundError(f"Error: User with {key}: {value} not found")
        
    async def update_map_preference(self, user, map_code, category, reaction_added):
        if reaction_added:
            update_type = "$addToSet"
        else:
            update_type = "$pull"
        if not category == 'favorite_maps' and not category == 'blocked_maps':
            print('error')
            return
        query = {
            'user_id': user.id
        }
        user_exists = await self.user_collection.find_one(query)
        if not user_exists:
            await self.register_user(user)
        update = {
            f'{update_type}': {
                f'{category}': map_code
            }
        }
        result = await self.user_collection.update_one(query, update)
        return result

    async def link_user_to_player(self, user, player_name):
        player = await self.lookup_player(player_name)
        if player:
            query = {
                'user_id': user.id
            }
            user_exists = await self.user_collection.find_one(query)
            if not user_exists:
                await self.register_user(user)
            update = {
                '$set':{
                    'player_id': player['_id']
                }
            }
            result = await self.user_collection.update_one(query, update)
            return result
        else:
            raise PlayerNotFoundError
        
    async def lookup_player(self, name):
        search_regex = "^" + re.escape(name) + "$"
        player_data = await self.player_collection.find_one({
            "$or": [
                {"name": {"$regex": search_regex, "$options": "i"}},
                {"aliases": {"$elemMatch": {"$regex": search_regex, "$options": "i"}}}
            ]
        })
        if player_data:
            return player_data
        else:
            raise PlayerNotFoundError
        
    async def get_player_by_id(self, player_id):
        query = {
            '_id': player_id
        }
        player = await self.player_collection.find_one(query)
        return player
        
    async def check_user_link(self, user):
        query = {
            'user_id': user.id,
            'player_id': {
                '$exists': True
            }
        }
        link_exists = await self.user_collection.find_one(query)
        return link_exists
    
    async def check_player_link(self, player_name):
        player = await self.lookup_player(player_name)
        query = {
            'player_id' : player['_id']
        }
        link_exists = await self.user_collection.find_one(query)
        return link_exists
    
    async def remove_player_link(self, user):
        query = {
            'user_id': user.id
        }
        update = {
            '$unset': {
                'player_id': ''
            }
        }
        result = await self.user_collection.update_one(query, update)
        return result
        
        
        

        
