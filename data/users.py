from utils.errors import *

class UserMethodsMixin:
    pass

    async def register_user(self, user, debug=False):
        if debug:
            user_exists = await self.user_collection.find_one({'user_id': user})
            if user_exists:
                return user_exists
            user_data = {
                'user_id':    user,
                'username':   f"debug_user_{user}",
                'name':       f"Debug User {user}",
                'mention':    f"<@{user}>",
                'avatar_url': None,
            }
            await self.user_collection.insert_one(user_data)
            return await self.user_collection.find_one({'user_id': user})

        await self.user_collection.update_one(
            {'user_id': user.id},
            {'$set': {
                'user_id':    user.id,
                'username':   user.name,
                'name':       user.display_name,
                'mention':    user.mention,
                'avatar_url': str(user.display_avatar.url) if user.display_avatar else None,
            }},
            upsert=True
        )
        return await self.user_collection.find_one({'user_id': user.id})
            
    async def get_user(self, **kwargs):
        user = await self.user_collection.find_one(kwargs)
        if user:
            return user
        return None
        
    async def get_user_by_challonge(self, tournament_id, challonge_id):
        tournament = await self.get_tournament_by_id(tournament_id)
        for discord_id, player_id in tournament['entrants'].items():
            if player_id == challonge_id:
                return discord_id
        return None

    async def get_users_bulk(self, user_ids: list[str | int]) -> dict[str, dict]:
        """Fetch multiple users in a single query. Returns {str(user_id): user_doc}."""
        if not user_ids:
            return {}
        int_ids = [int(uid) for uid in user_ids]
        users = await self.user_collection.find(
            {'user_id': {'$in': int_ids}}
        ).to_list(None)
        return {str(u['user_id']): u for u in users}

    async def refresh_all_avatars(self, guild):
        """Update avatar_url for all users in the database using current Discord member data."""
        users = await self.user_collection.find({}).to_list(None)
        updated = 0
        skipped = 0
        for user in users:
            member = guild.get_member(user['user_id'])
            if not member:
                skipped += 1
                continue
            await self.user_collection.update_one(
                {'user_id': user['user_id']},
                {'$set': {'avatar_url': str(member.display_avatar.url)}}
            )
            updated += 1
        return updated, skipped

    async def delete_debug_users(self):
        """Delete all user documents whose name starts with 'Debug User'."""
        result = await self.user_collection.delete_many(
            {'name': {'$regex': '^Debug User'}}
        )
        return result.deleted_count
            
    # async def link_user_to_player(self, user, player_name): 
    #     player = await self.lookup_player(player_name)
    #     if player:
    #         query = {
    #             'user_id': user.id
    #         }
    #         user_exists = await self.user_collection.find_one(query)
    #         if not user_exists:
    #             await self.register_user(user)
    #         update = {
    #             '$set':{
    #                 'player_id': player['_id']
    #             }
    #         }
    #         result = await self.user_collection.update_one(query, update)
    #         return result
    #     else:
    #         raise PlayerNotFoundError(player_name, 'link_user_to_player')
        
    # async def change_name(self, user_id, name):
    #     name_exists = await self.check_unique_name(name)
    #     if name_exists:
    #         raise NameNotUniqueError(name, 'change_name')
    #     user = await self.get_user(user_id=user_id)
    #     if 'player_id' in user:
    #         query = {
    #             '_id': user['player_id']
    #         }
    #         player = await self.player_collection.find_one(query)
    #         update = {
    #             '$set': {
    #                 'name': name
    #             },
    #             '$addToSet': {
    #                 'aliases': player['name']
    #             }
    #         }
    #         result = await self.player_collection.update_one(query, update)
    #         return result

    #     else:
    #         raise PlayerNotRegisteredError
        
