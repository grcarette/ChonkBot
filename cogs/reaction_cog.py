import discord
from discord.ext import commands
from handlers.reaction_handler import ReactionHandler

class ReactionCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.reaction_handler = ReactionHandler()
        
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.user_id == self.bot.user.id:
            return
        await self.reaction_handler.process_reaction(payload)
        
         
async def setup(bot):
    await bot.add_cog(ReactionCog(bot))