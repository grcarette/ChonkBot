import discord
from discord.ext import commands

class DebugCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @commands.command(name='add_bc')
    async def add_bc(self, ctx):
        channel = ctx.channel
        await self.bot.th.add_bot_control(channel)
        
async def setup(bot):
    await bot.add_cog(DebugCog(bot))