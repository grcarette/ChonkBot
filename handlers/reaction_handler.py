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
        
        if reaction_flag['type'] == 'create_tournament':
            if self.is_same_emoji(INDICATOR_EMOJIS['green_check'], payload.emoji.name):
                if reaction_added:
                    await self.bot.th.set_up_tournament(payload.message_id)
                else:
                    tournament = await self.bot.dh.get_tournament(message_id=payload.message_id)
                    await self.bot.th.remove_tournament(tournament['name'])
            else:
                await self.configure_tournament(payload, reaction_added)
            
        elif reaction_flag['type'] == 'report_match':
            pass
            
        elif reaction_flag['type'] == 'confirm_registration':
            if reaction_added:
                await self.bot.th.process_registration(message, True, is_confirmation=True)
            
                        
    async def configure_tournament(self, payload, reaction_added):
        message_id = payload.message_id
        emoji = payload.emoji.name
        if not reaction_added and TOURNAMENT_CONFIGURATION[emoji][1] == True:
            update_content = False
        else:
            update_content = TOURNAMENT_CONFIGURATION[emoji][1]

        update = {
            "$set": {f'{TOURNAMENT_CONFIGURATION[emoji][0]}': update_content}
        }
        await self.bot.dh.update_tournament(message_id, update)
        
    def is_same_emoji(self, emoji1, emoji2):
        return str(emoji1) == str(emoji2)