import discord
from discord.ext import commands

from utils.errors import *
from utils.messages import get_tournament_creation_message
from utils.reaction_utils import create_tournament_configuration

class EventCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @commands.command(name="create_tournament")
    async def create_tournament(self, ctx, *, event_data: str):
        user = ctx.author
        num_list = [1,2,3,4]
        
        event_data = event_data.split('-')
        event_name = event_data[0]
        event_time = event_data[1]
        
        message_content = get_tournament_creation_message(event_name, event_time)
        message = await ctx.send(message_content)

        try:
            await self.bot.dh.create_tournament(event_name, event_time, user.id, message_id=message.id)
            await create_tournament_configuration(self.bot, message, num_list, user_filter=user.id)
        except TournamentExistsError as e:
            await message.delete()
            await ctx.send(str(e))

        
            
        
         
async def setup(bot):
    await bot.add_cog(EventCog(bot))