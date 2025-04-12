from utils.errors import *

class UserMethodsMixin:
    pass

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
        
