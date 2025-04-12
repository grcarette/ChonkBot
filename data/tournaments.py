from utils.errors import *

class TournamentMethodsMixin:
    pass

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
        
    async def checkin_player(self, tournament_name, user_id): #tournament
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