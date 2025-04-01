from utils.errors import *
from utils.emojis import EMOJI_NUMBERS

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
            raise TournamentNotFoundError(key, value, 'get_tournament')
        
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
            raise TournamentNotFoundError(key, value, 'get_stage')
    
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
        query = {
            '_id': player_id
        }
        player = await self.player_collection.find_one(query)
        
        if not player or "tournaments" not in player:
            return []
        
        tournament_ids = player["tournaments"]

        pipeline = [
            {
                "$match": {
                    "id": {"$in": tournament_ids} 
                }
            },
            {
                "$project": {
                    "tournament_id": 1,
                    "name": 1,
                    "date": 1,
                    "total_entrants": {"$size": "$results"},
                    "player_result": {
                        "$arrayElemAt": [
                            {
                                "$filter": {
                                    "input": "$results",
                                    "as": "result",
                                    "cond": {"$eq": ["$$result.id", player_id]}
                                }
                            },
                            0
                        ]
                    }
                }
            },
            {
                "$match": {
                    "player_result": {"$ne": None}
                }
            },
            {
                "$addFields": {
                    "placement_ratio": {
                        "$divide": ["$player_result.placement", "$total_entrants"]
                    }
                }
            },
            {
                "$sort": {"placement_ratio": 1}
            },
            {
                "$limit": 4
            }
        ]
        
        result = await self.tournament_data_collection.aggregate(pipeline).to_list(None)
        return result
    
    async def find_special_opponents(self, player_id):
        query = {
            '$or': [
                {'winner_id': player_id},
                {'loser_id': player_id}
            ],
            'is_dq': False
        }
        matches = await self.match_collection.find(query).to_list(None)
        
        head_to_head = defaultdict(lambda: {'wins': 0, 'losses': 0})
        
        for match in matches:
            if match['loser_id'] == player_id:
                opponent_id = match['winner_id']
                head_to_head[opponent_id]['losses'] += 1
            else:
                opponent_id = match['loser_id']
                head_to_head[opponent_id]['wins'] += 1
                
        worst_ratio = None
        bracket_demon = None
        rival = None
        max_rival_matches = 0
        match_threshold = 2
        ratio_offset = 1
        closeness_factor = 2
        
        for opponent, record in head_to_head.items():
            total_matches = record['wins'] + record['losses']
            if total_matches < match_threshold:
                continue
            
            win_ratio = (record['wins'] + ratio_offset) / (total_matches + ratio_offset)

            if worst_ratio is None or win_ratio < worst_ratio:
                worst_ratio = win_ratio
                bracket_demon = {'id': opponent, 'wins': record['wins'], 'losses': record['losses']}
            
            win_loss_diff = abs(record['wins'] - record['losses'])
            if win_loss_diff <= total_matches / closeness_factor:
                if total_matches > max_rival_matches:
                    max_rival_matches = total_matches
                    rival = {'id': opponent, 'wins': record['wins'], 'losses': record['losses']}
                
        return bracket_demon, rival
    
    async def get_head_to_head(self, player1_name, player2_name, set_limit='5'):
        if set_limit.lower() == "all":
            set_limit = 999
        else:
            try:
                set_limit = int(set_limit)
            except ValueError:
                raise ValueError
        try: 
            player1 = await self.lookup_player(player1_name)
            p1_id = player1['_id']
            
            player2 = await self.lookup_player(player2_name)
            p2_id = player2['_id']

            p1_query = {
                'winner_id': p1_id, 
                'loser_id': p2_id,
                'is_dq': False
            }
            p2_query = {
                'winner_id': p2_id,
                'loser_id': p1_id,
                'is_dq': False
            }
            player_1_wins = await self.match_collection.count_documents(p1_query)
            player_2_wins = await self.match_collection.count_documents(p2_query)
            
            query = {
                '$or': [
                    {'winner_id': p1_id, 'loser_id': p2_id},
                    {'winner_id': p2_id, 'loser_id': p1_id}
                ],
                'is_dq': False
            }
            
            recent_matches = await self.match_collection.find(query).sort('date', -1).limit(set_limit).to_list(None)
            recent_matches_text = ''
            
            max_tourney_name_length = 21
            player_indent_position = 25
            result_indent_position = max(len(player1_name), len(player2_name))
            
            for match in recent_matches:
                if match['winner_id'] == p1_id:
                    winner_name = player1_name
                    loser_name = player2_name
                else:
                    winner_name = player2_name
                    loser_name = player1_name
                query = {
                    'id': match['tournament_id']
                }
                tournament = await self.tournament_data_collection.find_one(query)
                tournament_name = tournament['name'][:max_tourney_name_length]
                if len(tournament['name']) > max_tourney_name_length:
                    tournament_name += '...'
                formatted_string = (
                    f"{tournament_name:<{player_indent_position}}"
                    f"{winner_name:<{result_indent_position}} W-L {loser_name}"
                )
                recent_matches_text += f"```{formatted_string}```"
            return player_1_wins, player_2_wins, recent_matches_text
        except PlayerNotFoundError as e:
            raise PlayerNotFoundError(e.player_name, 'get_head_to_head') from e
        
    async def get_leaderboard(self, timeframe, start_timestamp=None, end_timestamp=None):
        min_match_count = 16
        leaderboard_length = 10
        
        if timeframe.lower() == 'season':
            start_timestamp=datetime(2025,1,1)
            end_timestamp=datetime(2025,7,1)
        elif timeframe.lower() == 'year':
            start_timestamp=datetime.now(timezone.utc) - timedelta(days=365)
            end_timestamp=datetime.now(timezone.utc)
        elif timeframe.lower() == 'custom':
            start_timestamp=start_timestamp
            end_timestamp=end_timestamp
            min_match_count = 8
        else:
            start_timestamp=datetime(2000,1,1)
            end_timestamp=datetime(2030,1,1)
            
        valid_tournaments = await self.tournament_data_collection.find(
            {
                "amateur": False, 
                "date": {"$gte": start_timestamp, "$lte": end_timestamp} 
            },
            {"_id": 0, "id": 1}
        ).to_list(length=None)
        valid_tournament_ids = [tournament["id"] for tournament in valid_tournaments]

        pipeline = [
            {"$match": {
                "is_dq": {"$ne": True},
                "tournament_id": {"$in": valid_tournament_ids}
            }},
            {
                "$project": {
                    "players": [
                        {"player_id": "$winner_id", "win": 1},
                        {"player_id": "$loser_id", "win": 0}
                    ]
                }
            },
            {"$unwind": "$players"},

            {
                "$group": {
                    "_id": "$players.player_id",
                    "total_wins": {"$sum": "$players.win"},
                    "total_matches": {"$sum": 1}
                }
            },

            {
                "$project": {
                    "player_id": "$_id",
                    "_id": 0,
                    "total_wins": 1,
                    "total_matches": 1,
                    "win_rate": {
                        "$cond": {
                            "if": {"$gt": ["$total_matches", 0]},
                            "then": {"$divide": ["$total_wins", "$total_matches"]},
                            "else": 0
                        }
                    }
                }
            },

            {"$match": {"total_matches": {"$gte": min_match_count}}},
            {"$sort": {"win_rate": -1}},
            {"$limit": leaderboard_length}
        ]
        
        result = await self.match_collection.aggregate(pipeline).to_list(length=None)
        leaderboard = []
        for player in result:
            query = {
                '_id': player['player_id']
            }
            player_data = await self.player_collection.find_one(query)
            losses = player['total_matches'] - player['total_wins']
            leaderboard_data = {
                'name': player_data['name'],
                'wins': player['total_wins'],
                'losses': losses,
                'winrate': round(player['win_rate'], 2)
            }
            leaderboard.append(leaderboard_data)
        return leaderboard

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
        
        



        
        
        
        

        
