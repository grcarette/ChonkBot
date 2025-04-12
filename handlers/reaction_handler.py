import discord
from discord.ext import commands
from utils.emojis import NUMBER_EMOJIS, INDICATOR_EMOJIS
from utils.reaction_flags import *

class ReactionHandler:
    def __init__(self, bot):
        self.bot = bot
        
    async def process_reaction(self, payload, reaction_added):
        reaction_flag = await self.bot.dh.get_reaction_flag(payload=payload)
        
        if reaction_flag:
            if reaction_flag['users'] == False or payload.user_id in reaction_flag['users']:
                await self.process_reaction_flag(payload, reaction_flag, reaction_added)
                
    async def process_reaction_flag(self, payload, reaction_flag, reaction_added):
        channel = self.bot.get_channel(payload.channel_id)
        if channel is None:
            return

        message = await channel.fetch_message(payload.message_id)
        emoji = payload.emoji.name
        user_id = payload.user_id
        message_id = payload.message_id
        
        reaction_flag = await self.bot.dh.update_reaction_to_flag(message_id, emoji, user_id, reaction_added)
        
        if reaction_flag['require_all_to_react'] == True:
            if not set(reaction_flag['users']) == set(reaction_flag['emojis'][emoji]):
                return
            
        elif reaction_flag['type'] == 'link_confirmation':
            if reaction_added:
                message = await channel.fetch_message(reaction_flag['message_id'])
                user = message.author
                player = reaction_flag['value']
                try:
                    await self.bot.dh.link_user_to_player(user, player)
                
                    message_content = (
                        f'User: *{user.name}* linked to player: *{player}* successfully'
                    )
                    await channel.send(message_content)
                except:
                    await channel.send("Unknown Error")
                await self.bot.dh.remove_reaction_flag(reaction_flag['message_id'])
                
    def is_same_emoji(self, emoji1, emoji2):
        return str(emoji1) == str(emoji2)