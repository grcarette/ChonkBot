import discord
import re
from discord.ext import commands
from discord import app_commands

from utils.errors import *
from utils.emojis import RESULT_EMOJIS, INDICATOR_EMOJIS
from utils.discord_preset_colors import get_random_color
from tournaments.match_lobby import MatchLobby
from tournaments.results_poster import post_results
from ui.create_tournament import TournamentSettingsView
from ui.confirmation import ConfirmationView
from ui.link_view import LinkView
from tournaments.challonge_handler import ChallongeHandler


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
        if not tournament:
            await interaction.response.send_message("No tournament found for this category.", ephemeral=True)
            return
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
        await interaction.followup.send("Creating test tournament...", ephemeral=True)

        tournament_data = {
            'name': "test tournament",
            'date': discord.utils.utcnow(),
            'organizer': interaction.user.id,
            'format': 'single elimination',
            'approved_registration': False,
            'randomized_stagelist': True,
            'display_entrants': True,
        }
        tournament = await self.bot.dh.get_tournament(name="test tournament")
        if tournament:
            await self.bot.dh.delete_tournament(tournament['_id'])
        await self.bot.th.set_up_tournament(tournament_data)

    @app_commands.command(name="post_results", description="Post tournament results to the results channel")
    @app_commands.checks.has_role("Event Organizer")
    async def post_results(self, interaction: discord.Interaction, challonge_url: str):
        RESULTS_CHANNEL_ID = 1346422769721544754
        channel = discord.utils.get(self.bot.guild.channels, id=RESULTS_CHANNEL_ID)
        ch = ChallongeHandler()
        
        challonge_id = extract_challonge_id(challonge_url)
        if not challonge_id:
            return await interaction.response.send_message("Invalid Challonge URL format.", ephemeral=True)
        tournament_name = await ch.get_tournament_name(challonge_id)
        await interaction.response.defer(ephemeral=True)

        try:
            final_results = await ch.get_final_results(challonge_id)
            
            overall_winner = ''
            results_list = []

            for player in final_results:
                rank = player.get('final_rank')
                name = player.get('name')
                emoji = ''
                
                if rank == 1:
                    emoji = RESULT_EMOJIS['1st']
                    overall_winner = f"**{RESULT_EMOJIS['trophy']} Overall Winner: {name}**\n\n"
                elif rank == 2:
                    emoji = RESULT_EMOJIS['2nd']
                elif rank == 3:
                    emoji = RESULT_EMOJIS['3rd']            
                elif 3 < rank <= 8:
                    emoji = RESULT_EMOJIS['medal']
                    
                results_list.append(f"{rank}: {name} {emoji}")

            message_content = overall_winner + "\n".join(results_list)
            embed = discord.Embed(
                title=f"{tournament_name}",
                description=message_content,
                color=get_random_color()
            )
            view = LinkView(f"{INDICATOR_EMOJIS['link']} Bracket", challonge_url)
            await channel.send(embed=embed, view=view)
            
            await interaction.followup.send("Results posted successfully!")

        except Exception as e:
            await interaction.followup.send(f"Error fetching results: {str(e)}")

def extract_challonge_id(url: str) -> str:
    """Extracts the tournament slug/ID from a standard Challonge URL."""
    match = re.search(r"challonge\.com\/(?:[^\/]+\/)?([^\/\?]+)", url)
    return match.group(1) if match else None

async def setup(bot):
    await bot.add_cog(EventCog(bot))