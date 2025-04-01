from utils.emojis import NUMBER_EMOJIS, INDICATOR_EMOJIS
from handlers.data_handler import DataHandler
from utils.reaction_flags import *

class MessageHandler:
    def __init__(self, bot):
        self.bot = bot
        
    async def send_level_message(self, level_data, channel):
        message_content = (
            f"# {level_data['name']}\n"
            f"Creator: {level_data['creator']}\n"
            f"Code: {level_data['code']}\n"
            f"{level_data['imgur']}"
            )
        message = await channel.send(message_content)
        return message