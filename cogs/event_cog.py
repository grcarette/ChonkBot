import discord
from discord.ext import commands

from utils.errors import *
from utils.messages import get_tournament_creation_message
from utils.reaction_utils import create_tournament_configuration

class EventCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.has_role('Event Organizer')
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
    
    @commands.has_role('Event Organizer')
    @commands.command(name="reveal_tournament")
    async def reveal_tournament(self, ctx):
        category_id = ctx.channel.category_id
        try:
            tournament = await self.bot.dh.get_tournament(category_id=category_id)
        except TournamentNotFoundError:
            return
        category_id = tournament['category_id']
        await self.bot.th.reveal_channels(category_id)
        
    @commands.has_role('Event Organizer')
    @commands.command(name="create_lobby")
    async def create_lobby(self, ctx):
        await self.bot.lh.create_lobby()
        
    @commands.has_role('Event Organizer')
    @commands.command(name="reset_lobby")
    async def reset_lobby(self, ctx):
        lobby = await self.bot.dh.reset_lobby(ctx.channel.id)
        await self.bot.lh.advance_lobby(lobby)
        
    @commands.has_role('Event Organizer')
    @commands.command(name="start_tournament")
    async def reset_lobby(self, ctx):
        lobby = await self.bot.dh.reset_lobby(ctx.channel.id)
        await self.bot.lh.advance_lobby(lobby)

        
            
async def setup(bot):
    await bot.add_cog(EventCog(bot))