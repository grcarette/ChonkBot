import motor.motor_asyncio
import asyncio

class DataHandler:
    def __init__(self):
        client = motor.motor_asyncio.AsyncIOMotorClient("mongodb://localhost:27017")
        self.db = client['ChonkBot']
        self.reaction_collection = self.db['reaction_flags']
        self.tournament_collection = self.db['tournaments']
        
    async def add_reaction_flag(self, message_id, flag_type, emojis, user_filter=False, require_all_to_react=False):
        if user_filter:
            if not isinstance(user_filter, list):
                user_filter = [user_filter]
            filtered_user_ids = [user.id for user in user_filter]
        else:
            filtered_user_ids = False
            
        if not isinstance(emojis, list):
            emojis = [emojis]
            
        query = {
            'message_id': message_id,
            'type': flag_type
        }
        flag_exists = await self.reaction_collection.find_one(query)
        
        if flag_exists:
            update = {
                "$addToSet": {
                    'emojis': {
                        "$each": emojis
                        }
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
                'emojis': emojis
            }
            await self.reaction_collection.insert_one(reaction_flag)
    
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