from utils.errors import *

class UserMethodsMixin:
    pass

    async def register_user(self, user): 
        if self.bot.debug:
            user_data = {
                'user_id': user,
                'username': f"debug_user_{user}",
                'name': f"Debug User {user}",
                'mention': f"<@{user}>",
                'favorite_maps': [],
                'blocked_maps': []
            }
            result = await self.user_collection.insert_one(user_data)
            user = await self.user_collection.find_one({'user_id': user})   
            return user
        query = {
            'user_id': user.id
        }
        user_exists = await self.user_collection.find_one(query)
        if not user_exists:
            user_data = {
                'user_id': user.id,
                'username': user.name,
                'name': user.display_name,
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
        
    async def get_user_by_challonge(self, tournament_id, challonge_id):
        tournament = await self.get_tournament_by_id(tournament_id)
        for discord_id, player_id in tournament['entrants'].items():
            if player_id == challonge_id:
                return discord_id
        return None
    
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
        
