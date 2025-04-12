import discord
from discord.ext import commands

class MessageDeleteCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload):
        message_id = payload.message_id
        
async def setup(bot):
    await bot.add_cog(MessageDeleteCog(bot))