from utils.errors import *

import random

class StageMethodsMixin:
    pass

    async def get_stage(self, **kwargs):
        stage = await self.party_map_collection.find_one(kwargs)
        return stage

    
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
        
    async def add_message_to_level(self, code, message_id): #stage
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