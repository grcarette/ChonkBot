from datetime import datetime, timezone, timedelta
from bson import ObjectId, SON

class LobbyMethodsMixin:
    pass

    async def create_lobby(self, tournament, match_id, lobby_name, prereq_matches, players, stages, num_winners, pool=None): #lobby
        query = {
            'tournament': tournament['name']
        }
        lobby_id = await self.lobby_collection.count_documents(query) + 1
        
        prereq_matches = await self.get_prereq_matches(prereq_matches)
        
        lobby_data = {
            'lobby_id': lobby_id,
            'tournament': tournament['_id'],
            'match_id': match_id,
            'lobby_name': lobby_name,
            'prereq_matches': prereq_matches,
            'pool': pool,
            'state': 'initialize',
            'players': players,
            'stages': stages,
            'num_winners': num_winners,
            'results': [],
            'checked_in': [],
        }
        lobby = await self.lobby_collection.insert_one(lobby_data)
        return lobby_id

    async def delete_lobby(self, match_id):
        query = {
            'match_id': match_id
        }
        result = await self.lobby_collection.delete_one(query)
        return result
    
    async def get_dependent_matches(self, match_id): #lobby
        query = {
            'prereq_match_ids': int(match_id)
        }
        lobbies = await self.lobby_collection.find(query).to_list(length=None)
        return lobbies
    
    async def get_prereq_matches(self, initial_matches): #lobby
        prereq_matches = set(initial_matches)
        to_process = initial_matches
        
        while to_process:
            current_match_id = to_process.pop()
            match_data = await self.find_match(current_match_id)
            print(match_data)
            
            if 'prereq_match_ids' in match_data:
                new_prereqs = set(match_data['prereq_match_ids'])
                prereq_matches.update(new_prereqs)
                to_process.extend(new_prereqs)
                
        return list(prereq_matches)

    async def lobby_checkin_player(self, match_id, player_id):
        query = {
            'match_id': match_id
        }
        update = {
            '$addToSet': {
                'checked_in': player_id
            }
        }
        result = await self.lobby_collection.update_one(query, update)
        lobby = await self.get_lobby(match_id)
        return lobby
    
    async def reset_lobby(self, match_id, state=None): #lobby
        query = { 
            'match_id': match_id
        }
        lobby = await self.lobby_collection.find_one(query)
        if state == 'last_result':
            await self.undo_last_result(match_id)
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
            'match_id': lobby['match_id']
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
    
    async def undo_last_result(self, match_id):
        query = {
            'match_id': match_id
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
    
    async def find_match(self, match_id): #lobby
        query = {
            'match_id': match_id
        }
        match_exists = await self.lobby_collection.find_one(query)
        return match_exists
    
    async def ban_stage(self, channel_id, banned_stage): #lobby
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
    
    async def pick_lobby_stage(self, match_id, picked_stage): #lobby
        query = {
            'match_id': match_id
        }
        update = {
            '$set': {
                'picked_stage': picked_stage
            }
        }
        result = await self.lobby_collection.update_one(query, update)
        lobby = await self.lobby_collection.find_one(query)
        return lobby
    
    async def report_match(self, match_id, winner_id):
        query = {
            'match_id': match_id
        }
        update = {
            '$push': {
                'results': int(winner_id)
            }
        }
        result = await self.lobby_collection.update_one(query, update)
        lobby = await self.lobby_collection.find_one(query)
        return lobby
    
    async def end_match(self, match_id): #lobby
        query = {
            'match_id': match_id
        }
        lobby = await self.lobby_collection.find_one(query)
        remaining_players = lobby['players']
        update = {
            '$set': {
                'finished_at': datetime.now()
            },
            '$addToSet': {
                'results': {
                    '$each': remaining_players
                }
            }
        }
        result = await self.lobby_collection.update_one(query, update)
        lobby = await self.lobby_collection.find_one(query)
        return lobby
    
    async def get_lobby_time(self, prereq_match_ids):
        print(prereq_match_ids)
        if len(prereq_match_ids) < 1:
            return datetime.now()
        
        pipeline = [
            {
                "$match": {
                    "match_id": {"$in": prereq_match_ids}
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
    
    async def remove_lobby(self, match_id):
        query = {
            'match_id': match_id
        }
        result = await self.lobby_collection.delete_one(query)
        return result
    
    async def get_lobby(self, match_id):
        query = {
            'match_id': match_id
        }
        lobby = await self.lobby_collection.find_one(query)
        return lobby
    
    async def get_lobby_by_channel(self, channel_id):
        query = {
            'channel_id': channel_id
        }
        lobby = await self.lobby_collection.find_one(query)
        return lobby
    
    async def get_active_lobbies(self, tournament_id): 
        query = {
            'tournament': ObjectId(tournament_id),
            'state': {
                '$ne': 'closed'
            }
        }
        active_lobbies = await self.lobby_collection.find(query).to_list(None)
        return active_lobbies
    
    async def add_channel_to_lobby(self, match_id, channel): 
        channel_id = channel.id
        query = {
            'match_id': match_id
        }
        update = {
            "$set": {
                'channel_id': channel_id
            }
        }
        result = await self.lobby_collection.update_one(query, update)
        return result
    
    async def update_lobby_state(self, match_id, state): #lobby
        query = {
            'match_id': match_id
        }
        update = {
            '$set': {
                'state': state,
                'state_timestamp': datetime.now()
            }
        }
        result = await self.lobby_collection.update_one(query, update)
        return result