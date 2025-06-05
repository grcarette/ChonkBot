from utils.errors import *
from bson import ObjectId, SON

class TournamentMethodsMixin:
    pass

    async def create_tournament(self, tournament):
        tournament_exists = await self.tournament_collection.find_one({'name': tournament['name']})
        if tournament_exists:
            raise TournamentExistsError(f"Error: Tournament name '{tournament['name']}' already exists.")
        config_data = {
            'approved_registration': tournament['approved_registration'],
            'randomized_stagelist': tournament['randomized_stagelist'],
            'display_entrants': tournament['display_entrants'],
        }
        tournament = {
            'name': tournament['name'],
            'date': tournament['date'],
            'organizers': [tournament['organizer']],
            'format': tournament['format'],
            'state': 'initialize',
            'config': config_data,
            'stagelist': [],
            'entrants': {},
            'dqs': [],
        }
        result = await self.tournament_collection.insert_one(tournament)
        tournament = await self.get_tournament(name=tournament['name'])
        return tournament
    
    async def edit_tournament_config(self, tournament_id, **kwargs):
        query = {
            '_id': ObjectId(tournament_id)
        }
        update = {
            '$set': kwargs
        }
        result = await self.tournament_collection.update_one(query, update)
    
    async def delete_tournament(self, tournament_id): 
        query = {
            '_id': ObjectId(tournament_id)
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
    
    async def add_stages_to_tournament(self, tournament_id, stage_codes):
        query = {
            '_id': ObjectId(tournament_id),
        }
        update = {
            '$addToSet': {
                'stagelist': {
                    '$each': stage_codes
                }
            }
        }
        result = await self.tournament_collection.update_one(query, update)
        return result
    
    async def remove_stage_from_tournament(self, tournament_id, map_code):
        query = {
            '_id': ObjectId(tournament_id)
        }
        update = {
            '$pull': {
                'stagelist': map_code
            }
        }
        result = await self.tournament_collection.update_one(query, update)
    
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
            "state": {
                '$nin': [
                    "finished",
                    "finalized"
                ]
            }
        }
        active_events = await self.tournament_collection.find(query).to_list(None)
        return active_events
    
    async def get_registration_status(self, tournament_id, user_id):
        query = {
            '_id': ObjectId(tournament_id),
            f'entrants.{user_id}': {
                '$exists': True
            }
        }
        player_exists = await self.tournament_collection.find_one(query)
        return player_exists
    
    async def register_player(self, tournament_id, user_id, player_id):
        player_exists = await self.get_registration_status(tournament_id, user_id)
        
        if not player_exists:
            query = {
                '_id': ObjectId(tournament_id)
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
        
    async def unregister_player(self, tournament_id, user_id):
        query = {
            '_id': ObjectId(tournament_id)
        }
        tournament = await self.get_tournament_by_id(tournament_id)
        
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
        
    async def get_tournament_by_id(self, tournament_id):
        query = {
            '_id': ObjectId(tournament_id)
        }
        tournament = await self.tournament_collection.find_one(query)
        return tournament
        
    async def get_tournament_by_channel(self, channel):
        if channel.category == None:
            lobby = await self.get_lobby(channel_id=channel.id)
            query = {
                'name': lobby['tournament']
            }
        else:
            category_id = channel.category.id
            query = {
                'category_id': category_id
            }
        tournament = await self.tournament_collection.find_one(query)
        return tournament
        
    async def disqualify_player(self, tournament_id, user_id):
        query = {
            '_id': ObjectId(tournament_id)
        }
        tournament = await self.tournament_collection.find_one(query)
        if str(user_id) not in tournament['entrants']:
            return False
        if tournament['state'] != 'active':
            return False

        update = {
            '$addToSet': {
                'dqs': user_id
            }
        }
        result = await self.tournament_collection.update_one(query, update)
        return True

    async def undisqualify_player(self, tournament_id, user_id):
        query = {
            '_id': ObjectId(tournament_id)
        }
        update = {
            '$pull': {
                'dqs': user_id
            }
        }
        result = await self.tournament_collection.update_one(query, update)
        return True
    
    async def update_tournament_state(self, tournament_id, state):
        query = {
            '_id': ObjectId(tournament_id)
        }
        update = {
            '$set': {
                'state': state
            }
        }
        result = await self.tournament_collection.update_one(query, update)
        
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
    
    async def set_tournament_color(self, tournament_id, color):
        query = {
            '_id': ObjectId(tournament_id)
        }
        update = {
            '$set': {
                'config.color': color
            }
        }
        result = await self.tournament_collection.update_one(query, update)
    
    async def add_assistant(self, tournament_id, user_id):
        query = {
            '_id': ObjectId(tournament_id)
        }
        update = {
            '$push': {
                'organizers': user_id
            }
        }
        result = await self.tournament_collection.update_one(query, update)