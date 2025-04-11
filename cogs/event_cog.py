import discord
from discord.ext import commands

from utils.errors import *
from utils.messages import get_tournament_creation_message
from utils.reaction_utils import create_tournament_configuration

from ui.create_tournament import TournamentSettingsView
from ui.confirmation import ConfirmationView

class EventCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.has_role('Event Organizer')
    @commands.command(name="create_tournament")
    async def create_tournament(self, ctx):
        embed = discord.Embed(
            title="Setup Tournament",
            description="Click the buttons below to configure your tournament.",
            color=discord.Color.green()
        )
        user = ctx.author
        await ctx.send(embed=embed, view=TournamentSettingsView(user, self.bot))
        
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
        user_id = ctx.message.author.id
        lobby = await self.bot.dh.get_lobby(channel_id=ctx.channel.id)
        await self.bot.th.confirm_reset_lobby(user_id, lobby, 'stage_bans')
        
    @commands.has_role('Event Organizer')
    @commands.command(name="reset_report")
    async def reset_report(self, ctx):
        user_id = ctx.message.author.id
        lobby = await self.bot.dh.get_lobby(channel_id=ctx.channel.id)
        await self.bot.th.confirm_reset_lobby(user_id, lobby, 'report')

        
    @commands.has_role("Moderator")
    @commands.command(name="delete_tournament", aliases=['r'])
    async def delete_tournament(self, ctx):
        user_id = ctx.message.author.id
        channel = ctx.channel
        category_id = ctx.channel.category.id
        embed = discord.Embed(
            title="Are you sure you want to delete this tournament?",
            color=discord.Color.red()
        )
        view = ConfirmationView(self.bot.th.remove_tournament, user_id, category_id=category_id)
        await channel.send(embed=embed, view=view)
        
    @commands.has_role("Moderator")
    @commands.command(name='reset_call')
    async def reset_call(self, ctx):
        category_id = ctx.channel.category.id
        kwargs={'category_id': category_id}
        await self.bot.th.start_tournament(kwargs)
         
async def setup(bot):
    await bot.add_cog(EventCog(bot))