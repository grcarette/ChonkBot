from utils.emojis import NUMBER_EMOJIS, INDICATOR_EMOJIS
from handlers.data_handler import DataHandler
from utils.reaction_flags import *

class MessageHandler:
    def __init__(self, bot):
        self.bot = bot
        