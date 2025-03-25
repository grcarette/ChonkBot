from utils.emojis import NUMBER_EMOJIS, INDICATOR_EMOJIS
from handlers.data_handler import DataHandler
from utils.reaction_flags import *

class ReactionHandler:
    def __init__(self, bot):
        self.dh = DataHandler()
        self.bot = bot
        
    async def process_reaction(self, payload, reaction_added):
        reaction_flag = await self.dh.get_reaction_flag(payload=payload)
        
        if reaction_flag:
            if reaction_flag['users'] == False or payload.user_id in reaction_flag['users']:
                await self.process_reaction_flag(payload, reaction_flag, reaction_added)
                
    async def process_reaction_flag(self, payload, reaction_flag, reaction_added):
        print('processing reaction flag')
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
            
        if reaction_flag['type'] == 'create_tournament':
            if self.is_same_emoji(INDICATOR_EMOJIS['green_check'], emoji):
                if reaction_added:
                    await self.bot.th.set_up_tournament(message_id)
                else:
                    tournament = await self.bot.dh.get_tournament(message_id=message_id)
                    await self.bot.th.remove_tournament(tournament['name'])
            
        elif reaction_flag['type'] == 'confirm_registration':
            if reaction_added:
                await self.bot.th.process_registration(message, True, is_confirmation=True)
                
        elif reaction_flag['type'] == 'match_checkin':
            lobby = await self.bot.dh.get_lobby(channel_id=channel.id)
            await self.bot.dh.remove_reaction_flag(message_id)
            await self.bot.lh.advance_lobby(lobby)
            
        elif reaction_flag['type'] == 'stage_ban':
            channel_id = payload.channel_id
            await message.delete()
            await self.bot.lh.ban_stages(channel_id, payload)

        elif reaction_flag['type'] == 'match_report':
            channel_id = payload.channel_id
            lobby = await self.bot.dh.get_lobby(channel_id=channel.id)
            await self.bot.dh.remove_reaction_flag(message_id)
            await self.bot.dh.report_match(channel_id, payload)
            await self.bot.lh.advance_lobby(lobby)
            
        elif reaction_flag['type'] == 'match_confirmation':
            channel_id = payload.channel_id
            lobby = await self.bot.dh.get_lobby(channel_id=channel.id)
            await self.bot.dh.remove_reaction_flag(message_id)
            if self.is_same_emoji(emoji, INDICATOR_EMOJIS['green_check']):
                await self.bot.lh.advance_lobby(lobby, confirmation=True)
            elif self.is_same_emoji(emoji, INDICATOR_EMOJIS['red_x']):
                await self.bot.lh.advance_lobby(lobby, confirmation=False)
            

    def is_same_emoji(self, emoji1, emoji2):
        return str(emoji1) == str(emoji2)