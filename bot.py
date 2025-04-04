import discord
from discord.ext import commands, tasks
import os
from dotenv import load_dotenv

from data.data_handler import DataHandler
from handlers.tournament_handler import TournamentHandler
from handlers.message_handler import MessageHandler
from handlers.challonge_handler import ChallongeHandler
from handlers.lobby_handler import LobbyHandler
from handlers.reaction_handler import ReactionHandler

from ui.register_control import RegisterControlView
from ui.bot_control import BotControlView

class ChonkBot(commands.Bot):
    def __init__(self, command_prefix, intents):
        super().__init__(command_prefix, intents=intents)
        
        self.dh = DataHandler()
        self.th = TournamentHandler(self)
        self.mh = MessageHandler(self)
        self.ch = ChallongeHandler()
        self.lh = LobbyHandler(self)
        self.rh = ReactionHandler(self)
        
        self.guild = None
        self.admin_id = int(os.getenv('ADMIN_ID'))
           
    async def setup_hook(self):
        await self.load_cogs()
        for command in self.commands:
            print(f"Command loaded: {command.name}")
            
        self.add_view(RegisterControlView(self))
        self.add_view(BotControlView(self))
        
        self.clean_reaction_flags.start()
         
    async def load_cogs(self):
        for filename in os.listdir("./cogs"):
            if filename.endswith(".py"):
                try:
                    await self.load_extension(f"cogs.{filename[:-3]}")
                    print(f"Loaded {filename}")
                except Exception as e:
                    print(f"Failed to load cog {filename}: {e}")
                    
    @tasks.loop(minutes=2)
    async def clean_reaction_flags(self):
        await self.dh.clean_reaction_flags()
        
    @clean_reaction_flags.before_loop
    async def before_clean_reaction_flags(self):
        await self.wait_until_ready()

if __name__=="__main__":
    load_dotenv()
    intents = discord.Intents.default()
    
    intents.members = True
    intents.messages = True
    intents.message_content = True
    intents.guilds = True
    bot = ChonkBot(command_prefix="!", intents=intents)
    bot.run(os.getenv("DISCORD_TOKEN"))