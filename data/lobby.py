from datetime import datetime, timezone, timedelta

class LobbyMethodsMixin:
    pass

    async def create_lobby(self, tournament, match_id, prerequisite_matches, players, stages, num_stage_bans, num_winners, pool=None): #lobby
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

    
    async def delete_lobby(self, lobby): #lobby
        query = {
            'channel_id': lobby['channel_id']
        }
        result = await self.lobby_collection.delete_one(query)
        return result
    
    async def get_dependent_matches(self, match_id): #lobby
        query = {
            'prerequisite_match_ids': int(match_id)
        }
        lobbies = await self.lobby_collection.find(query).to_list(length=None)
        return lobbies
    
    async def get_prerequisite_matches(self, initial_matches): #lobby
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
    
    async def reset_lobby(self, channel_id, state=None): #lobby
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
    
    async def reset_players(self, lobby): #lobby
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
    
    async def undo_last_result(self, channel_id): #lobby
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
    
    async def pick_lobby_stage(self, channel_id, picked_stage): #lobby
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
    
    async def report_match(self, channel_id, winner_id): #lobby
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
    
    async def end_match(self, channel_id): #lobby
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
    
    async def get_lobby_time(self, prerequisite_match_ids): #lobby
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
    
    async def update_lobby_state(self, lobby, state): #lobby
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