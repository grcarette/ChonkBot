import re
from fuzzywuzzy import fuzz

from utils.errors import *

class StatsDataMethodsMixin:
    pass

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