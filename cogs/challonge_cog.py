import discord
from discord.ext import commands
from handlers.challonge_handler import ChallongeHandler

class ChallongeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.challonge = ChallongeHandler()

async def setup(bot):
    await bot.add_cog(ChallongeCog(bot))