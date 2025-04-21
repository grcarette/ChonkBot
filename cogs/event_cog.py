import discord
from discord.ext import commands

from utils.errors import *
from utils.messages import get_tournament_creation_message
from utils.reaction_utils import create_tournament_configuration

from ui.create_tournament import TournamentSettingsView
from ui.confirmation import ConfirmationView

from tournaments.match_lobby import MatchLobby
from tournaments.results_poster import post_results

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
    @commands.command(name="reset_report")
    async def reset_report(self, ctx):
        user_id = ctx.message.author.id
        channel_id = ctx.channel.id
        await self.bot.th.confirm_reset_lobby(user_id, channel_id)
 
    @commands.has_role("Moderator")
    @commands.command(name="delete_tournament", aliases=['r'])
    async def delete_tournament(self, ctx):
        user_id = ctx.message.author.id
        channel = ctx.channel
        category_id = ctx.channel.category.id
        
        tournament = await self.bot.dh.get_tournament_by_channel(channel)
        tm = self.bot.th.tournaments[tournament['_id']]
        embed = discord.Embed(
            title="Are you sure you want to delete this tournament?",
            color=discord.Color.red()
        )
        view = ConfirmationView(tm.delete_tournament, user_id, category_id=category_id)
        await channel.send(embed=embed, view=view)
        
    @commands.has_role("Moderator")
    @commands.command(name='reset_call')
    async def reset_call(self, ctx):
        category_id = ctx.channel.category.id
        kwargs={'category_id': category_id}
        await self.bot.th.start_tournament(kwargs)
        
    @commands.has_role("Moderator")
    @commands.command(name='test_lobby', aliases = ['tl'])
    async def test_lobby(self, ctx):
        guild = self.bot.guild
        
        player1 = discord.utils.get(guild.members, id=1017833723506475069).id
        player2 = discord.utils.get(guild.members, id=142798704703700992).id
        players = [player1, player2]
        
        tournament = await self.bot.dh.get_tournament(name='test')
        
        match_lobby = await MatchLobby.create(
            tournament_id='67fac457a8ae7cd75e075ab2',
            match_id=1,
            lobby_name='|WR1| Bojack vs Bojack',
            prereq_matches=[],
            players=players,
            stages=tournament['stagelist'],
            num_winners=1,
            tournament_manager=self,
            datahandler=self.bot.dh,
            guild=guild,
        )
        await match_lobby.initialize_match()
        
    @commands.has_role("Moderator")
    @commands.command(name='delete_lobbies', aliases = ['dl'])
    async def delete_lobbies(self, ctx):
        lobbies = await self.bot.dh.get_active_lobbies('67fac457a8ae7cd75e075ab2')
        print(lobbies)
        for lobby in lobbies:
            channel = discord.utils.get(self.bot.guild.channels, id=lobby['channel_id'])
            await channel.delete()
            await self.bot.dh.remove_lobby(lobby['match_id'])
            
    @commands.has_role("Moderator")
    @commands.command(name='post_challonge_results', aliases = ['pcr'])
    async def post_challonge_results(self, ctx, challonge_id, challonge_url, *, tournament_name):
        await post_results(self.bot, challonge_url, challonge_id, tournament_name)
        

        
            
            
        
         
async def setup(bot):
    await bot.add_cog(EventCog(bot))