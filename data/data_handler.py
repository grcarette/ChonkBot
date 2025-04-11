from utils.errors import *
from utils.emojis import EMOJI_NUMBERS

from .player_stats import StatsHandler
from .ranked_handler import RankedHandler

from datetime import datetime, timezone, timedelta
from collections import defaultdict


import motor.motor_asyncio
import asyncio
import math
import random
import re
from fuzzywuzzy import fuzz

class DataHandler:
    def __init__(self):
        client = motor.motor_asyncio.AsyncIOMotorClient("mongodb://localhost:27017")
        self.stats = StatsHandler()
        self.ranked = RankedHandler()
        
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
    
    async def create_tournament(self, tournament):
        tournament_exists = await self.tournament_collection.find_one({'name': tournament['name']})
        if tournament_exists:
            raise TournamentExistsError(f"Error: Tournament name '{tournament['name']}' already exists.")
        config_data = {
            'check-in': tournament['check-in'],
            'approved_registration': tournament['approved_registration'],
            'randomized_stagelist': tournament['randomized_stagelist'],
            'stage_bans': tournament['stage_bans']
        }
        tournament = {
            'name': tournament['name'],
            'date': tournament['date'],
            'organizer': tournament['organizer'],
            'format': tournament['format'],
            'state': 'initialized',
            'config': config_data,
            'stagelist': [],
            'entrants': {}
        }
        result = await self.tournament_collection.insert_one(tournament)
        tournament = await self.get_tournament(name=tournament['name'])
        return tournament
        
    async def delete_tournament(self, category_id):
        query = {
            'category_id': category_id
        }
        result = await self.tournament_collection.delete_one(query)
        
    async def start_tournament(self, category_id):
        query = {
            'category_id': category_id
        }
        update = {
            '$set': {
                'state': 'active'
            }
        }
        result = await self.tournament_collection.update_one(query, update)
        
        
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
    
    async def add_challonge_to_tournament(self, tournament_name, url, tournament_id):
        query = {
            'name': tournament_name
        }
        challonge_data = {
            'url': url,
            'id': tournament_id
        }
        update = {
            '$set': {
                'challonge_data': challonge_data
            }
        }
        result = await self.tournament_collection.update_one(query, update)
        tournament = await self.tournament_collection.find_one(query)
        return tournament
    
    async def get_tournament(self, **kwargs):
        tournament = await self.tournament_collection.find_one(kwargs)
        if tournament:
            return tournament
        else:
            key, value = next(iter(kwargs.items()))
            raise TournamentNotFoundError(key, value, 'get_tournament')
        
    async def get_active_events(self):
        query = {
            '$or': [
                {'state': 'initialized'},
                {'state': 'active'}
            ]
        }
        active_events = await self.tournament_collection.find(query).to_list(None)
        return active_events
        
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
    
    async def get_registration_status(self, tournament_name, user_id):
        query = {
            'name': tournament_name,
            f'entrants.{user_id}': {
                '$exists': True
            }
        }
        player_exists = await self.tournament_collection.find_one(query)
        return player_exists
        
    async def register_player(self, tournament_name, user_id, player_id):
        player_exists = await self.get_registration_status(tournament_name, user_id)
        
        if not player_exists:
            query = {
                'name': tournament_name
            }

            update = {
                "$set": {
                    f"entrants.{user_id}": player_id
                }
            }
            result = await self.tournament_collection.update_one(query, update)
            return result
        else:
            return False
    
    async def unregister_player(self, tournament_name, user_id):
        query = {
            'name': tournament_name
        }
        tournament = await self.get_tournament(name=tournament_name)
        
        update = {}
            
        if str(user_id) in tournament.get('entrants', {}):
            update.setdefault('$unset', {})[f'entrants.{user_id}'] = ""
        
        if 'checked_in' in tournament and user_id in tournament['checked_in']:
            update.setdefault('$pull', {})['checked_in'] = user_id
            
        if update:
            result = await self.tournament_collection.update_one(query, update)
            return result
        else:
            return None
    
    async def checkin_player(self, tournament_name, user_id):
        query = {
            'name': tournament_name
        }
        update = {
            '$addToSet': {
                'checked_in': user_id
            }
        }
        result = await self.tournament_collection.update_one(query, update)
        return result
    
    async def get_stage(self, **kwargs):
        map = await self.party_map_collection.find_one(kwargs)
        if map:
            return map
        else:
            key, value = next(iter(kwargs.items()))
            raise TournamentNotFoundError(key, value, 'get_stage')
    
    async def get_random_stages(self, number, user=False, type='party'):
        if user:
            user_info = await self.user_collection.find_one({'user_id': user.id})
            if not user_info:
                user_info = await self.register_user(user)
            query = {
                'code': {
                    '$nin': user_info['blocked_maps']
                },
                'type': type,
                'tournament_legal': True
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
    
    async def add_legal_stage(self, level_name, creator, code, length, multiple_paths, includes_hazards, imgur):
        query = {
            'code': code
        }
        level_exists = await self.party_map_collection.find_one(query)
        if level_exists:
            raise LevelExistsError
        level_name = level_name.replace("_", " ")
        level_data = {
            'name': level_name,
            'code': code,
            'creator': creator,
            'length': length,
            'multiple_paths': multiple_paths,
            'includes_hazards': includes_hazards,
            'tournament_legal': True,
            'imgur': imgur
        }
        result = await self.party_map_collection.insert_one(level_data)
        new_level = await self.party_map_collection.find_one(query)
        return new_level
    
    async def add_level(self, name, type, creator, code, imgur):
        creator_id = creator.id
        user_query = {
            'user_id': creator_id
        }
        user_exists = await self.user_collection.find_one(user_query)
        if not user_exists:
            await self.register_user(creator)
        query = {
            'code': code
        }
        level_exists = await self.level_collection.find_one(query)
        if level_exists:
            query = {
                '$and': [
                    {'$or': [
                        {'name': name},
                        {'code': code}
                    ]
                    },
                    {'creator': creator_id}
                ]
            }
            creator_matches = await self.level_collection.find_one(query)
            if creator_matches:
                return 'creator_match'
            else:
                return 'creator_mismatch'
        else:
            level_data = {
                'name': name,
                'type': type,
                'code': code,
                'creator': creator_id,
                'imgur': imgur,
            }
            result = await self.level_collection.insert_one(level_data)
            level = await self.level_collection.find_one(query)
            return level
    
    async def get_level(self, **kwargs):
        level = await self.level_collection.find_one(kwargs)
        if level:
            return level
        else:
            key, value = next(iter(kwargs.items()))
            raise LevelNotFoundError(f"Error: User with {key}: {value} not found")
        
    async def get_level_rating(self, map_code, upvotes_only):
        upvote_query = {
            'map_code': map_code,
            'rating': 'upvote'
        }
        downvote_query = {
            'map_code': map_code,
            'rating': 'downvote'
        }
        upvotes = await self.ratings_collection.count_documents(upvote_query)
        downvotes = await self.ratings_collection.count_documents(downvote_query)
        if upvotes_only:
            return upvotes
        else:
            return upvotes, downvotes
        
    async def get_user_map_preference(self, discord_user, map_code):
        is_favorite = False
        is_blocked = False
        rating = None
        query = {
            'user_id': discord_user.id
        }
        user = await self.user_collection.find_one(query)
        if not user:
            await self.register_user(discord_user)
            user = await self.user_collection.find_one(query)
            
        if map_code in user['favorite_maps']:
            is_favorite = True
        if map_code in user['blocked_maps']:
            is_blocked = True
        
        rating_query = {
            'user_id': user['user_id'],
            'map_code': map_code
        }
        user_rating = await self.ratings_collection.find_one(rating_query)
        if user_rating:
            rating = user_rating['rating']
        return is_favorite, is_blocked, rating
            
    async def add_message_to_level(self, code, message_id):
        query = {
            'code': code
        }
        update = {
            '$set': {
                'message_id': message_id
            }
        }
        result = await self.level_collection.update_one(query, update)
        level = await self.level_collection.find_one(query)
        return level
        
    async def create_lobby(self, tournament, match_id, prerequisite_matches, players, stages, num_stage_bans, num_winners, pool=None):
        player_ids = [player.id for player in players]
        query = {
            'tournament': tournament['name']
        }
        lobby_id = await self.lobby_collection.count_documents(query) + 1
        
        config_data = {
            'num_stage_bans': num_stage_bans,
            'num_winners': num_winners,
        }
        
        prerequisite_matches = await self.get_prerequisite_matches(prerequisite_matches)
        
        lobby_data = {
            'lobby_id': lobby_id,
            'tournament': tournament['name'],
            'match_id': match_id,
            'prerequisite_match_ids': prerequisite_matches,
            'pool': pool,
            'state': 'initialize',
            'players': player_ids,
            'stages': stages,
            'config': config_data,
            'results': [],
        }
        lobby = await self.lobby_collection.insert_one(lobby_data)
        return lobby_id
    
    async def delete_lobby(self, lobby):
        query = {
            'channel_id': lobby['channel_id']
        }
        result = await self.lobby_collection.delete_one(query)
        return result
    
    async def get_dependent_matches(self, match_id):
        query = {
            'prerequisite_match_ids': int(match_id)
        }
        lobbies = await self.lobby_collection.find(query).to_list(length=None)
        return lobbies
    
    async def get_prerequisite_matches(self, initial_matches):
        prerequisite_matches = set(initial_matches)
        to_process = initial_matches
        
        while to_process:
            print(to_process)
            current_match_id = to_process.pop()
            print(current_match_id)
            match_data = await self.find_match(current_match_id)
            print(match_data)
            
            if 'prerequisite_match_ids' in match_data:
                new_prereqs = set(match_data['prerequisite_match_ids'])
                prerequisite_matches.update(new_prereqs)
                to_process.extend(new_prereqs)
                
        return list(prerequisite_matches)
    
    async def reset_lobby(self, channel_id, state=None):
        query = {
            'channel_id': channel_id
        }
        lobby = await self.lobby_collection.find_one(query)
        if state == 'last_result':
            await self.undo_last_result(channel_id)
            update = {
                "$set": {
                    'state': 'reporting'
                }
            }
        elif state == 'stage_bans':
            await self.reset_players(lobby)
            update = {
                "$set": {
                    'state': 'stage_bans',
                    'picked_stage': None
                }
            }
        elif state == 'report':
            await self.reset_players(lobby)
            update = {
                "$set": {
                    'state': 'reporting',
                }
            }
        result = await self.lobby_collection.update_one(query, update)
        lobby = await self.lobby_collection.find_one(query)
        return lobby
    
    async def reset_players(self, lobby):
        query = {
            'channel_id': lobby['channel_id']
        }
        update = {
            '$push':{
                'players': {
                    '$each': lobby['results']
                }
            },
            '$set': {
                'results': []
            }
        }
        result = await self.lobby_collection.update_one(query, update)
        lobby = await self.lobby_collection.find_one(query)
        return lobby
    
    async def undo_last_result(self, channel_id):
        query = {
            'channel_id': channel_id
        }
        lobby = await self.lobby_collection.find_one(query)
        if not lobby or not lobby.get('results'):
            return lobby
        
        last_result = lobby['results'][-1]
        update = {
            '$push': {
                'players': last_result
            },
            '$pull': {
                'results': last_result
            }
        }
        result = await self.lobby_collection.update_one(query, update)
        return result
    
    async def find_match(self, match_id):
        query = {
            'match_id': match_id
        }
        match_exists = await self.lobby_collection.find_one(query)
        return match_exists
        
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
    
    async def pick_lobby_stage(self, channel_id, picked_stage):
        query = {
            'channel_id': channel_id
        }
        update = {
            '$set': {
                'picked_stage': picked_stage
            }
        }
        result = await self.lobby_collection.update_one(query, update)
        lobby = await self.lobby_collection.find_one(query)
        return lobby
    
    async def report_match(self, channel_id, winner_id):
        query = {
            'channel_id': channel_id
        }
        update = {
            '$push': {
                'results': winner_id
            },
            '$pull': {
                'players': winner_id
            }
        }
        result = await self.lobby_collection.update_one(query, update)
        lobby = await self.lobby_collection.find_one(query)
        return lobby
    
    async def end_match(self, channel_id):
        query = {
            'channel_id': channel_id
        }
        lobby = await self.lobby_collection.find_one(query)
        remaining_players = lobby['players']
        update = {
            '$set': {
                'players': [],
                'finished_at': datetime.now()
            },
            '$push': {
                'results': {
                    '$each': remaining_players
                }
            }
        }
        result = await self.lobby_collection.update_one(query, update)
        lobby = await self.lobby_collection.find_one(query)
        return lobby
    
    async def get_lobby_time(self, prerequisite_match_ids):
        print(prerequisite_match_ids)
        if len(prerequisite_match_ids) < 1:
            return datetime.now()
        
        pipeline = [
            {
                "$match": {
                    "match_id": {"$in": prerequisite_match_ids}
                }
            },
            {
                "$sort": {
                    "finished_at": -1
                }
            },
            {
                "$limit": 1
            }
]
        most_recent_match = await self.lobby_collection.aggregate(pipeline).to_list(None)
        return most_recent_match[0]['finished_at']
    
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
    
    async def get_active_lobbies(self, tournament_name):
        query = {
            'tournament': tournament_name,
            'state': {
                '$ne': 'finished'
            }
        }
        active_lobbies = await self.lobby_collection.find(query).to_list(None)
        return active_lobbies
        
    async def add_channel_to_lobby(self, lobby_id, tournament_name, channel_id):
        query = {
            'lobby_id': lobby_id,
            'tournament': tournament_name
        }
        update = {
            "$set": {
                'channel_id': channel_id
            }
        }
        result = await self.lobby_collection.update_one(query, update)
        return result

    async def update_lobby_state(self, lobby, state):
        query = {
            'channel_id': lobby['channel_id']
        }
        update = {
            '$set': {
                'state': state,
                'state_timestamp': datetime.now()
            }
        }
        result = await self.lobby_collection.update_one(query, update)
        return result
    
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
        
    async def get_user_by_challonge(self, tournament_name, challonge_id):
        tournament = await self.get_tournament(name=tournament_name)
        for discord_id, player_id in tournament['entrants'].items():
            if player_id == challonge_id:
                return discord_id
        return None
        
    async def update_map_preference(self, user, map_code, category, reaction_added):
        if reaction_added:
            update_type = "$addToSet"
        else:
            update_type = "$pull"
        if not category == 'favorite_maps' and not category == 'blocked_maps':
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
    
    async def update_level_rating(self, user_id, map_code, rating):
        query = {
            'user_id': user_id,
            'map_code': map_code
        }
        user_rating_exists = await self.ratings_collection.find_one(query)
        if user_rating_exists:
            update = {
                '$set': {
                    'rating': rating
                }
            }
            if user_rating_exists['rating'] == rating:
                rating_change = 0
            elif user_rating_exists['rating'] == 'downvote':
                rating_change = 1
            elif user_rating_exists['rating'] == 'upvote':
                rating_change = -1
            result = await self.ratings_collection.update_one(query, update)
            
        else:
            rating_data = {
                'user_id': user_id,
                'map_code': map_code,
                'rating': rating
            }
            if rating == 'upvote':
                rating_change = 1
            else:
                rating_change = 0
            result = await self.ratings_collection.insert_one(rating_data)
        return rating_change

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
            raise PlayerNotFoundError(player_name, 'link_user_to_player')
        
    async def lookup_player(self, name, use_alias=True):
        search_regex = "^" + re.escape(name) + "$"
        if use_alias:
            query = {
                "$or": [
                    {"name": {"$regex": search_regex, "$options": "i"}},
                    {"aliases": {"$elemMatch": {"$regex": search_regex, "$options": "i"}}}
                ]
            }
        else:
            query = {
                "name": {"$regex": search_regex, "$options": "i"}
            }
        player_data = await self.player_collection.find_one(query)

        if player_data:
            return player_data
        else:
            raise PlayerNotFoundError(name, 'lookup_player')
        
    async def find_closest_player_name(self, name):
        all_players = await self.player_collection.find().to_list(None)
        
        best_match = None
        best_score = 0
        
        for player in all_players:
            score = fuzz.ratio(name.lower(), player['name'].lower())
            
            if player.get('aliases'):
                for alias in player['aliases']:
                    alias_score = fuzz.ratio(name.lower(), alias.lower())
                    score = max(score, alias_score)
            
            if score > best_score and score > 60:
                best_score = score
                best_match = player['name']
                
        if best_match:
            return best_match
        else:
            raise PlayerNotFoundError(name, 'find_closest_player_name')
        
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
        if link_exists:
            player_query = {
                '_id': link_exists['player_id']
            }
            player = await self.player_collection.find_one(player_query)
            raise UserLinkExistsError(link_exists['name'], player['name'], 'check_user_link')
    
    async def check_player_link(self, player_name):
        player = await self.lookup_player(player_name)
        query = {
            'player_id' : player['_id']
        }
        link_exists = await self.user_collection.find_one(query)
        if link_exists:
            raise PlayerLinkExistsError(player_name, link_exists['name'], 'check_player_link')
    
    async def remove_player_link(self, user):
        query = {
            'user_id': user.id
        }
        user = await self.user_collection.find_one(query)
        if not 'player_id' in user:
            raise PlayerNotRegisteredError
        update = {
            '$unset': {
                'player_id': ''
            }
        }
        result = await self.user_collection.update_one(query, update)
        return result
    
    async def get_player_stats(self, player_name):
        await self.stats.get_player_stats(self, player_name)
    
    async def get_player_stats(self, player_name):
        player = await self.lookup_player(player_name, use_alias=True)
        if not player:
            return False
        
        start_date = datetime(2025, 1, 14)
        end_date = datetime(2025, 6, 14)
        
        winrate_data = await self.find_winrate_data(player['_id'], start_date, end_date)
        placement_data = await self.find_placement_data(player['_id'])
        bracket_demon, rival = await self.find_special_opponents(player['_id'])

        lifetime_wins = winrate_data['lifetime_wins']
        lifetime_losses = winrate_data['lifetime_losses']
        if lifetime_wins == 0 and lifetime_losses == 0:
            lifetime_winrate = 0
        else:
            lifetime_winrate = lifetime_wins / (lifetime_wins + lifetime_losses)
            
        season_wins = winrate_data['season_wins']
        season_losses = winrate_data['season_losses']      
        if season_wins == 0 and season_losses == 0:
            season_winrate = 0
        else:
            season_winrate = season_wins / (season_wins + season_losses)

        placements = [f"{placement['name']}: {placement['player_result']['placement']}/{placement['total_entrants']}" for placement in placement_data]
        
        if bracket_demon == None:
            bracket_demon_stats = None
        else:
            bracket_demon_player = await self.get_player_by_id(bracket_demon['id'])
            bracket_demon_name = bracket_demon_player['name']
            bracket_demon_wins = bracket_demon['wins']
            bracket_demon_losses = bracket_demon['losses']
            bracket_demon_stats = {
                'name': bracket_demon_name,
                'wins': bracket_demon_wins,
                'losses': bracket_demon_losses
            }
        if rival == None:
            rival_stats = None
        else:
            rival_player = await self.get_player_by_id(rival['id'])
            rival_player_name = rival_player['name']
            rival_wins = rival['wins']
            rival_losses = rival['losses']
            rival_stats = {
                'name': rival_player_name,
                'wins': rival_wins,
                'losses': rival_losses
            }
        
        player_stats = {
            'lifetime': {
                'wins': lifetime_wins,
                'losses': lifetime_losses,
                'winrate': round(lifetime_winrate, 2)
            },
            'season': {
                'wins': season_wins,
                'losses': season_losses,
                'winrate': round(season_winrate, 2)
            },
            'placements': placements,
            'bracket_demon': bracket_demon_stats,
            'rival': rival_stats,
        }
        return player_stats
    
    async def find_winrate_data(self, player_id, start_date, end_date):
        pipeline = [
            {
                "$match": {
                    "is_dq": False,
                    "$or": [
                        {"winner_id": player_id},
                        {"loser_id": player_id}
                    ]
                }
            },
            {
                "$group": {
                    "_id": None,
                    
                    "lifetime_wins": {"$sum": {"$cond": [{"$eq": ["$winner_id", player_id]}, 1, 0]}},
                    "lifetime_losses": {"$sum": {"$cond": [{"$eq": ["$loser_id", player_id]}, 1, 0]}},

                    "season_wins": {
                        "$sum": {
                            "$cond": [
                                {"$and": [
                                    {"$eq": ["$winner_id", player_id]},
                                    {"$gte": ["$date", start_date]},
                                    {"$lte": ["$date", end_date]}
                                ]}, 
                                1, 
                                0
                            ]
                        }
                    },
                    "season_losses": {
                        "$sum": {
                            "$cond": [
                                {"$and": [
                                    {"$eq": ["$loser_id", player_id]},
                                    {"$gte": ["$date", start_date]},
                                    {"$lte": ["$date", end_date]}
                                ]}, 
                                1, 
                                0
                            ]
                        }
                    }
                }
            }
        ]
        
        result = await self.match_collection.aggregate(pipeline).to_list(1)
        
        if result:
            return {
                'lifetime_wins': result[0]['lifetime_wins'],
                'lifetime_losses': result[0]['lifetime_losses'],
                'season_wins': result[0]['season_wins'],
                'season_losses': result[0]['season_losses']
                }
        
        return {
            'lifetime_wins': 0, 
            'lifetime_losses': 0,
            'season_wins': 0,
            'season_losses': 0
            }
        
    async def find_placement_data(self, player_id):
        await self.stats.find_placement_data(player_id)
    
    async def get_head_to_head(self, player1_name, player2_name, set_limit='5'):
        return await self.stats.get_head_to_head
        
    async def get_leaderboard(self, timeframe, start_timestamp=None, end_timestamp=None):
        return await self.stats.get_leaderboard(self, timeframe, start_timestamp=None, end_timestamp=None)

    async def change_name(self, user_id, name):
        name_exists = await self.check_unique_name(name)
        if name_exists:
            raise NameNotUniqueError(name, 'change_name')
        user = await self.get_user(user_id=user_id)
        if 'player_id' in user:
            query = {
                '_id': user['player_id']
            }
            player = await self.player_collection.find_one(query)
            update = {
                '$set': {
                    'name': name
                },
                '$addToSet': {
                    'aliases': player['name']
                }
            }
            result = await self.player_collection.update_one(query, update)
            return result

        else:
            raise PlayerNotRegisteredError
        
    async def get_bracket(self, bracket_name):
        search_regex = "^" + re.escape(bracket_name) + "$"
        bracket_name = bracket_name.strip().lower()
        query = {
            "name": {"$regex": search_regex, "$options": "i"},
        }
        tournament = await self.tournament_data_collection.find_one(query)
        return tournament
        
    async def find_closest_tournament(self, bracket_name):
        bracket_name = bracket_name.strip()
        all_tournaments = await self.tournament_data_collection.find().to_list(None)
        
        best_match = None
        best_score = 0
        
        for tournament in all_tournaments:
            score = fuzz.ratio(bracket_name.lower(), tournament['name'].lower())
            
            if score > best_score and score > 40:
                best_score = score
                best_match = tournament['name']
                
        if best_match:
            print(best_match, best_score)
            return best_match
        else:
            print(best_score)
            raise 
    
    async def check_unique_name(self, name):
        query = {
            'name': name
        }
        name_exists = await self.player_collection.find_one(query)
        if name_exists:
            return True
        else:
            return False
        
    async def clean_reaction_flags(self):
        current_time = datetime.now(timezone.utc)
        query = {
            'timestamp': {
                '$lt': current_time
            }
        }
        result = await self.reaction_collection.delete_many(query)
        
        


 
        
        
        

        
