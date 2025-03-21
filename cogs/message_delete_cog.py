import discord
from discord.ext import commands

class MessageDeleteCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload):
        message_id = payload.message_id
        reaction_flags = await self.bot.dh.get_reaction_flag(message_id=message_id)
        if reaction_flags:
            await self.bot.dh.remove_reaction_flag(message_id)
        

async def setup(bot):
    await bot.add_cog(MessageDeleteCog(bot))