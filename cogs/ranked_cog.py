import discord
from discord.ext import commands

class RankedCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @commands.command(name='create_ranked_lobby')
    async def create_ranked_lobby(self, ctx, player1: str, player2: str):
        pass
        
async def setup(bot):
    await bot.add_cog(RankedCog(bot))