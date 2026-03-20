import discord
import re
import typing

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
from ui.force_advance import ForceAdvanceView

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

    @app_commands.command(name="reset_lobby", description="Reset a match lobby to the reporting phase")
    @app_commands.checks.has_role("Event Organizer")
    async def reset_lobby(self, interaction: discord.Interaction):
        await self.bot.th.confirm_reset_lobby(interaction.user.id, interaction.channel.id)
        await interaction.response.send_message("Reset confirmation sent.", ephemeral=True)

    @app_commands.command(name="delete_tournament", description="Delete current tournament")
    @app_commands.checks.has_role("Event Organizer")
    async def delete_tournament(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        category = interaction.channel.category
        if not category:
            return await interaction.followup.send("This channel is not in a category.", ephemeral=True)

        tournament = await self.bot.dh.get_tournament_by_channel(interaction.channel)
        if not tournament:
            return await interaction.followup.send("No tournament found for this category.", ephemeral=True)
        if interaction.user.id not in tournament['organizers']:
            return await interaction.followup.send("You are not an organizer of this tournament.", ephemeral=True)

        tm = self.bot.th.tournaments.get(tournament['_id'])
        if not tm:
            return await interaction.followup.send("Tournament manager not found. The tournament may have already been deleted.", ephemeral=True)

        embed = discord.Embed(
            title="Are you sure you want to delete this tournament?",
            description="This will delete all channels and roles associated.",
            color=discord.Color.red()
        )
        view = ConfirmationView(tm.delete_tournament, interaction.user.id, category_id=category.id)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

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
    async def test_tournament(
        self,
        interaction: discord.Interaction,
        format: typing.Literal['swiss', 'de'] = 'swiss',
    ):
        await interaction.response.defer(ephemeral=True)

        if format == 'de':
            tournament_format = 'double elimination'
            name = 'test tournament de'
        else:
            tournament_format = 'swiss'
            name = 'test tournament'

        tournament_data = {
            'name': name,
            'date': discord.utils.utcnow(),
            'organizer': interaction.user.id,
            'format': tournament_format,
            'approved_registration': False,
            'randomized_stagelist': True,
            'display_entrants': True,
            'round_limit': 2,  # only used for swiss
            'debug': True,
        }

        existing = await self.bot.dh.get_tournament(name=name)
        if existing:
            await self.bot.dh.delete_tournament(existing['_id'])

        await self.bot.th.set_up_tournament(tournament_data)
        await interaction.followup.send(
            f"Test **{tournament_format}** tournament created.", ephemeral=True
        )

    @app_commands.command(name="register_role", description="Register all players with the tournament role")
    @app_commands.checks.has_role("Event Organizer")
    async def register_role(self, interaction: discord.Interaction):
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

        await self.bot.th.register_role(category.id)
        await interaction.response.send_message("All players registered with the tournament role.")

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

# ── cogs/event_cog.py ────────────────────────────────────────────────────────
# Add to imports at the top alongside other ui imports:
#
#   from ui.force_advance import ForceAdvanceView


    @app_commands.command(name="force_advance_lobby", description="Force a stuck lobby to a specific state")
    @app_commands.checks.has_role("Event Organizer")
    async def force_advance_lobby(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        lobby_data = await self.bot.dh.get_lobby_by_channel(interaction.channel.id)
        if not lobby_data:
            return await interaction.followup.send(
                "This channel is not a lobby channel. Run this command from inside a match lobby.",
                ephemeral=True
            )

        tournament = await self.bot.dh.get_tournament_by_channel(interaction.channel)
        if not tournament:
            return await interaction.followup.send("No tournament found for this channel.", ephemeral=True)

        tm = self.bot.th.tournaments.get(tournament['_id'])
        if not tm:
            return await interaction.followup.send("Tournament manager not found.", ephemeral=True)

        match_lobby = tm.lobbies.get(lobby_data['match_id'])
        if not match_lobby:
            return await interaction.followup.send(
                "Lobby is not active in memory. The bot may have restarted — try `/reset_lobby` instead.",
                ephemeral=True
            )

        view = ForceAdvanceView(match_lobby, lobby_data)
        embed = discord.Embed(
            title="⚠️ Force Advance Lobby",
            description=(
                f"**Current state:** `{lobby_data['state']}`\n\n"
                "Select where to advance this lobby. "
                "**Declare Winner** will fully report the match to Challonge and progress the bracket normally.\n\n"
                "Use this only if the lobby is genuinely stuck and cannot self-recover."
            ),
            color=discord.Color.orange()
        )
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        async def force_advance(self, target_state: str, winner_id: int = None):
            """
            Forcibly advance a stuck lobby to the given state.
            Called by the /force_advance_lobby slash command.

            target_state options:
            'stage_bans' — reset and re-run stage banning
            'reporting'  — skip/reset to reporting, picking a stage if needed
            'winner'     — declare a winner and run the full end_reporting chain

            For 'reporting' and 'stage_bans', the existing reset_lobby DB helpers
            are used so player state is restored correctly.
            For 'winner', end_reporting is called directly so Challonge, player
            instructions, and match calling all fire as normal.
            """
            await self.purge_bot_messages()

            if target_state == 'stage_bans':
                await self.dh.reset_lobby(self.match_id, 'stage_bans')
                lobby = await self.get_lobby()
                self.remaining_players = set(lobby['players'])
                await self.start_stage_bans()

            elif target_state == 'reporting':
                await self.dh.reset_lobby(self.match_id, 'report')
                lobby = await self.get_lobby()
                self.remaining_players = set(lobby['players'])
                if not lobby.get('picked_stage'):
                    picked_stage = random.choice(self.stages)
                    await self.dh.pick_lobby_stage(self.match_id, picked_stage)
                await self.start_reporting()

            elif target_state == 'winner':
                if winner_id is None:
                    raise ValueError("winner_id is required when forcing to 'winner' state")
                await self.end_reporting(winner_id=winner_id)

def extract_challonge_id(url: str) -> str:
    """Extracts the tournament slug/ID from a standard Challonge URL."""
    match = re.search(r"challonge\.com\/(?:[^\/]+\/)?([^\/\?]+)", url)
    return match.group(1) if match else None

async def setup(bot):
    await bot.add_cog(EventCog(bot))