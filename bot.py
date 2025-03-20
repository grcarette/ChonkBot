import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

class ChonkBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix="!", intents=intents)
        
        self.load_cogs()
        
    def load_cogs(self):
        cogs = ["cogs.challonge_cog", "cogs.data_cog"]
        for cog in cogs:
            try:
                self.load_extension(cog)
                print(f"Loaded {cog}")
            except Exception as e:
                print(f"Failed to load {cog}: {e}")

    async def on_ready(self):
        print(f"Logged in as {self.user}")

if __name__=="__main__":
    load_dotenv()
    bot = ChonkBot()
    bot.run(os.getenv("DISCORD_TOKEN"))