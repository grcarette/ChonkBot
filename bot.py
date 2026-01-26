import discord
from discord.ext import commands, tasks
import os
from dotenv import load_dotenv

from data import DataHandler
from handlers.tournament_handler import TournamentHandler
from handlers.reaction_handler import ReactionHandler

from ui.register_control import RegisterControlView
from ui.bot_control import BotControlView

BOT_ID = 943999083792711741

class ChonkBot(commands.Bot):
    def __init__(self, command_prefix, intents):
        super().__init__(command_prefix, intents=intents)
        
        self.dh = DataHandler(self)
        self.th = TournamentHandler(self)
        self.rh = ReactionHandler(self)
        
        self.debug = True
        self.guild = None
        self.id = BOT_ID
        self.admin_id = int(os.getenv('ADMIN_ID'))
           
    async def setup_hook(self):
        await self.load_cogs()
        for command in self.commands:
            print(f"Command loaded: {command.name}")
            
    async def on_ready(self):
        self.guild = self.guilds[0]
        await self.th.initialize_active_events()
        print("Bot initialized")

    async def load_cogs(self):
        for filename in os.listdir("./cogs"):
            if filename.endswith(".py"):
                try:
                    await self.load_extension(f"cogs.{filename[:-3]}")
                    print(f"Loaded {filename}")
                except Exception as e:
                    print(f"Failed to load cog {filename}: {e}")
                    
if __name__=="__main__":
    load_dotenv()
    intents = discord.Intents.default()
    
    intents.members = True
    intents.messages = True
    intents.message_content = True
    intents.guilds = True
    bot = ChonkBot(command_prefix="/", intents=intents)
    bot.run(os.getenv("DISCORD_TOKEN"))