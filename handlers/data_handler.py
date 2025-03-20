import motor.motor_asyncio
import asyncio

class DataHandler:
    def __init__(self):
        client = motor.motor_asyncio.AsyncIOMotorClient("mongodb://localhost:27017")
        self.db = client['ChonkBot']
        self.reaction_collection = self.db['reaction_flags']
        
    async def add_reaction_flag(self, message_id, flag_type, emojis, user_filter):
        filtered_user_ids = [user.id for user in user_filter]
        
        query = {
            'message_id': message_id
        }
        reaction_flag = {
            'type': flag_type,
            'emojis': emojis
        }
        
        message_has_flag = await self.reaction_collection.find_one(query)
        if message_has_flag:
            update = {
                '$push': {'flags': reaction_flag}
            }
            result = await self.reaction_collection.update_one(query, update)
        else:
            reaction_flag_message = {
                'message_id': message_id,
                'users': filtered_user_ids,
                'has_confirmation': False,
                'flags': [reaction_flag]
            }
            result = await self.reaction_collection.insert_one(reaction_flag_message)
        return result
    
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