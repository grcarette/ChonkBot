from utils.emojis import NUMBER_EMOJIS, INDICATOR_EMOJIS

from handlers.data_handler import DataHandler

class ReactionHandler:
    def __init__(self):
        self.dh = DataHandler()
        
    async def process_reaction(self, payload):
        reaction_flag = await self.dh.get_reaction_flag(payload=payload)
        
        if reaction_flag:
            if reaction_flag['has_confirmation'] == False:
                await self.process_reaction_flag(payload, reaction_flag)
            else:
                if self.is_same_emoji(payload.emoji, INDICATOR_EMOJIS['green_check']):
                    await self.process_reaction_flag(payload, reaction_flag)

    async def process_reaction_flag(self, payload, reaction_flag):
        pass
        
        
    def is_same_emoji(self, emoji1, emoji2):
        return str(emoji1) == str(emoji2)