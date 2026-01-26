import discord
from discord.ext import commands
from discord import app_commands

from utils.errors import *
from tournaments.match_lobby import MatchLobby
from tournaments.results_poster import post_results
from ui.create_tournament import TournamentSettingsView
from ui.confirmation import ConfirmationView

class EventCog(commands.Cog, name="event"):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="create_tournament", description="Create a new tournament")
    @app_commands.checks.has_role("Event Organizer")
    async def create_tournament(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Setup Tournament",
            description="Click the buttons below to configure your tournament.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(
            embed=embed, 
            view=TournamentSettingsView(interaction.user, self.bot),
            ephemeral=True
        )

    @app_commands.command(name="reset_lobby", description="Reset a match lobby")
    @app_commands.checks.has_role("Event Organizer")
    async def reset_lobby(self, interaction: discord.Interaction):
        await self.bot.th.confirm_reset_lobby(interaction.user.id, interaction.channel.id)
        await interaction.response.send_message("Reset confirmation sent.", ephemeral=True)

    @app_commands.command(name="delete_tournament", description="Delete current tournament")
    @app_commands.checks.has_role("Event Organizer")
    async def delete_tournament(self, interaction: discord.Interaction):
        category = interaction.channel.category
        if not category:
            return await interaction.response.send_message("This channel is not in a category.", ephemeral=True)

        tournament = await self.bot.dh.get_tournament_by_channel(interaction.channel)
        if not interaction.user.id in tournament['organizers']:
            await interaction.response.send_message("You are not an organizer of this tournament.", ephemeral=True)
            return
        tm = self.bot.th.tournaments[tournament['_id']]
        
        embed = discord.Embed(
            title="Are you sure you want to delete this tournament?",
            description="This will delete all channels and roles associated.",
            color=discord.Color.red()
        )
        view = ConfirmationView(tm.delete_tournament, interaction.user.id, category_id=category.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="reset_call", description="Reset tournament calls")
    @app_commands.checks.has_role("Moderator")
    async def reset_call(self, interaction: discord.Interaction):
        category_id = interaction.channel.category.id
        kwargs = {'category_id': category_id}
        await self.bot.th.start_tournament(kwargs)
        await interaction.response.send_message("Calls reset.", ephemeral=True)

    @app_commands.command(name="test_lobby", description="Create a test match lobby")
    @app_commands.checks.has_role("Moderator")
    async def test_lobby(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        guild = interaction.guild
        p1_id, p2_id = 1017833723506475069, 142798704703700992
        players = [p1_id, p2_id]
        
        tournament = await self.bot.dh.get_tournament(name='test')
        
        match_lobby = await MatchLobby.create(
            tournament_id='67fac457a8ae7cd75e075ab2',
            match_id=1,
            lobby_name='|WR1| Bojack vs Bojack',
            prereq_matches=[],
            players=players,
            stages=tournament['stagelist'],
            num_winners=1,
            tournament_manager=self.bot.th.tournaments['67fac457a8ae7cd75e075ab2'], # Adjusted manager reference
            datahandler=self.bot.dh,
            guild=guild,
        )
        await match_lobby.initialize_match()
        await interaction.followup.send("Test lobby created.")

    @app_commands.command(name="test_tournament", description="Create a test tournament (invisible to users)")
    @app_commands.checks.has_role("Event Organizer")
    async def test_tournament(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        tournament_data = {
            'name': "test tournament",
            'date': discord.utils.utcnow(),
            'organizer': interaction.user.id,
            'format': 'single elimination',
            'approved_registration': False,
            'randomized_stagelist': True,
            'display_entrants': True,
        }
        await self.bot.th.set_up_tournament(tournament_data)
        await interaction.followup.send("Test tournament created.")

async def setup(bot):
    await bot.add_cog(EventCog(bot))