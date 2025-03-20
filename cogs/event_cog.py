import discord
from discord.ext import commands

from utils.messages import get_tournament_creation_message
from utils.reaction_utils import create_numerical_reaction, create_confirmation_reaction

class EventCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @commands.command(name="create_tournament")
    async def create_tournament(self, ctx, *, event_data: str):
        user = ctx.author
        flag_type = 'create_tournament'
        
        event_data = event_data.split('-')
        event_name = event_data[0]
        event_time = event_data[1]

        message_content = get_tournament_creation_message(event_name, event_time)
        emoji_list = [1,2,3,4]
        message = await ctx.send(message_content)
        await create_numerical_reaction(self.bot, message, emoji_list, flag_type, user_filter=[user])
        await create_confirmation_reaction(self.bot, message, user_filter=[user])
        
         
async def setup(bot):
    await bot.add_cog(EventCog(bot))