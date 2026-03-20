from .challonge_handler import ChallongeHandler
from .match_service import MatchService
from formats import make_format
from datetime import datetime

from utils.channel_utils import CHANNEL_PERMISSIONS, create_channel
from utils.emojis import RESULT_EMOJIS, INDICATOR_EMOJIS
from utils.discord_preset_colors import get_random_color
from utils.get_bracket_link import get_bracket_link
from utils.validate_stagecode import validate_stagecode

from ui.match_call import MatchCallView
from ui.checkin import CheckinView
from ui.stage_bans import BanStagesButton
from ui.match_report import MatchReportButton
from ui.register_control import RegisterControlView
from ui.bot_control import BotControlView
from ui.tournament_checkin import TournamentCheckinView
from ui.end_tournament import EndTournamentView
from ui.link_view import LinkView
from ui.registration_approval import RegistrationApprovalView
from ui.swiss_register import SwissActiveRegisterView

from .match_lobby import MatchLobby
from .tournament_control import TournamentControl
from .tournament_info_display import TournamentInfoDisplay

import discord
import random
import os

RESULTS_CHANNEL_ID = 1346422769721544754
DEFAULT_CHANNEL_POSITION = 2


class TournamentManager:
    def __init__(self, bot, tournament):
        self.bot = bot
        self.tournament = tournament
        self.ch = ChallongeHandler()
        self.guild = self.bot.guild
        self.lobbies = {}
        self.match_calls = {}
        self.bot_control = None
        self.tournament_reset = False
        self.autocall_matches = False
        self.debug = self.tournament.get('debug', False)
        self.organizer_role = None
        self.format = None

    # ─── Ranked API helper ────────────────────────────────────────────────────

    async def get_ranked_player(self, user_id: int) -> dict | None:
        """
        Wrapper around the UCH Ranked API that returns fake data in debug mode.
        Use this instead of calling self.bot.uchranked_api.get_player directly.
        """
        if self.debug:
            fake_elos = {
                0: 2100,  # tier 1 → 2 bonus points
                1: 2200,  # tier 1 → 2 bonus points
                2: 1600,  # tier 2 → 1 bonus point
                3: 1500,  # tier 2 → 1 bonus point
                4: 1100,  # tier 3 → 0 bonus points
                5: 1000,  # tier 3 → 0 bonus points
                6: 900,   # tier 3 → 0 bonus points
                7: 800,   # tier 3 → 0 bonus points
            }
            elo = fake_elos.get(user_id % 8, 1000)
            return {
                'found': True,
                'username': f'debug_user_{user_id}',
                'elo': elo,
                'rank': 'Debug',
                'division': 0,
            }
        return await self.bot.uchranked_api.get_player(user_id)

    # ─── Initialization ───────────────────────────────────────────────────────

    async def initialize_event(self):
        tournament = await self.get_tournament()

        self.format = make_format(self)
        await self.format.on_initialize()

        self.tc = TournamentControl(self)
        await self.tc.initialize_controls()

        active_lobbies = await self.bot.dh.get_active_lobbies(self.tournament['_id'])
        for lobby in active_lobbies:
            match_lobby = await MatchLobby.create(
                tournament_id=tournament['_id'],
                match_id=lobby['match_id'],
                lobby_name=lobby['lobby_name'],
                prereq_matches=lobby['prereq_matches'],
                players=lobby['players'],
                stages=lobby['stages'],
                num_winners=lobby['num_winners'],
                tournament_manager=self,
                datahandler=self.bot.dh,
                guild=self.bot.guild,
                bracket=lobby.get('bracket'),
                match_service=None,  # rehydrated lobbies fall back to report_match
            )
            self.lobbies[lobby['match_id']] = match_lobby
            if lobby['state'] == 'initialized':
                pass
            elif lobby['state'] == 'checkin':
                self.bot.add_view(CheckinView(match_lobby))
            elif lobby['state'] == 'stage_bans':
                self.bot.add_view(BanStagesButton(match_lobby))
            elif lobby['state'] == 'reporting':
                self.bot.add_view(MatchReportButton(match_lobby))

        if tournament['state'] == 'initialize':
            await self.progress_tournament()
        if tournament['state'] == 'setup':
            pass
        elif tournament['state'] == 'registration':
            self.bot.add_view(RegisterControlView(self))
        elif tournament['state'] == 'checkin':
            await self.send_checkin_message()
        elif tournament['state'] == 'active':
            if self.format and not self.format.needs_match_call_refresh:
                self.bot.add_view(SwissActiveRegisterView(self))
            await self.start_tournament_loop()
        elif tournament['state'] == 'finished':
            self.bot.add_view(EndTournamentView(self))

        tournament = await self.get_tournament()
        self.organizer_role = discord.utils.get(self.guild.roles, name=f"{tournament['name']} TO")

    # ─── Tournament state progression ────────────────────────────────────────

    async def progress_tournament(self, kwargs=None):
        tournament = await self.get_tournament()
        state = tournament['state']
        next_state = None
        pre_transition_tasks = []

        if state == 'initialize':
            next_state = 'setup'
        elif state == 'setup':
            next_state = 'registration'
            pre_transition_tasks = [
                self.publish_tournament(),
                self.open_registration()
            ]
        elif state == 'registration':
            next_state = 'checkin'
            pre_transition_tasks = [self.start_checkin()]
        elif state == 'checkin':
            next_state = 'active'
            pre_transition_tasks = [self.start_tournament()]
        elif state == 'active':
            next_state = 'finished'
            pre_transition_tasks = [self.end_tournament()]
        elif state == 'finished':
            next_state = 'finalized'
            pre_transition_tasks = [self.finalize_tournament()]

        if next_state:
            for task in pre_transition_tasks:
                await task
            await self.tc.update_tournament_state(next_state)
            await self.bot.dh.update_tournament_state(self.tournament['_id'], next_state)

    # ─── Stages ───────────────────────────────────────────────────────────────

    async def add_stages(self, stages):
        valid_stages = []
        stages = stages.split(',')
        for stage_code in stages:
            valid_code = validate_stagecode(stage_code)
            if not valid_code:
                return stage_code
            valid_stages.append(valid_code)
        await self.bot.dh.add_stages_to_tournament(self.tournament['_id'], valid_stages)
        return True

    # ─── Publishing ───────────────────────────────────────────────────────────

    async def publish_tournament(self):
        if self.debug:
            return
        guild = self.bot.guilds[0]
        category = self.get_tournament_category()
        for channel in category.channels:
            if channel.name in CHANNEL_PERMISSIONS:
                permissions = CHANNEL_PERMISSIONS[channel.name]
                if permissions != 'private':
                    overwrite = channel.overwrites_for(guild.default_role)
                    overwrite.view_channel = not overwrite.view_channel
                    await channel.set_permissions(guild.default_role, overwrite=overwrite)

    # ─── Registration ─────────────────────────────────────────────────────────

    async def open_registration(self):
        tournament = await self.get_tournament()

        if self.debug:
            default_debug_players = 8
            for i in range(default_debug_players):
                try:
                    await self.register_player(i)
                except Exception as e:
                    print(f"[open_registration] Failed to register debug player {i}: {e}")

        if tournament['state'] == 'registration':
            guild = self.bot.guild
            tournament_category = self.get_tournament_category()
            register_channel = await self.get_channel('register')
            hide_channel = True if self.debug else False

            if not register_channel:
                register_channel = await create_channel(
                    guild=guild,
                    tournament_category=tournament_category,
                    hide_channel=hide_channel,
                    channel_name='register',
                    channel_overwrites=CHANNEL_PERMISSIONS['register'],
                    organizer_role=self.organizer_role
                )
                await register_channel.edit(position=DEFAULT_CHANNEL_POSITION)
                view = RegisterControlView(self)
                embed = discord.Embed(
                    title=f"Register for {self.tournament['name']}",
                    color=discord.Color.green()
                )
                await register_channel.send(embed=embed, view=view)
            else:
                await self.toggle_registration_visibility()
        elif tournament['state'] == 'checkin':
            self.checkin_view.register_button.disabled = False
            await self.checkin_message.edit(view=self.checkin_view)

        await self.bot.dh.open_registration(tournament['_id'])

    async def close_registration(self):
        tournament = await self.get_tournament()
        if tournament['state'] == 'registration':
            await self.toggle_registration_visibility()
        elif tournament['state'] == 'checkin':
            self.checkin_view.register_button.disabled = True
            await self.checkin_message.edit(view=self.checkin_view)
        await self.bot.dh.close_registration(tournament['_id'])

    async def toggle_registration_visibility(self):
        if self.debug:
            return
        channel = await self.get_channel('register')
        overwrite = channel.overwrites_for(self.guild.default_role)
        overwrite.view_channel = not overwrite.view_channel
        await channel.set_permissions(self.guild.default_role, overwrite=overwrite)

    async def create_registration_approval(self, user_id, interaction):
        # Run the format's registration gate (e.g. UCH Ranked check for Swiss)
        allowed = await self.format.on_registration_gate(user_id, interaction)
        if not allowed:
            return

        already_registered = await self.bot.dh.get_registration_status(
            self.tournament['_id'], user_id
        )
        if already_registered:
            await interaction.response.send_message(
                "You are already registered for this event.",
                ephemeral=True
            )
            return

        if self.tournament['config']['approved_registration']:
            user = discord.utils.get(self.bot.guild.members, id=user_id)
            approval_channel = await self.get_channel('registration-approval')
            embed = discord.Embed(title=user.name, color=get_random_color())
            view = RegistrationApprovalView(self, user_id)
            await approval_channel.send(embed=embed, view=view)
            message_content = (
                f"Your registration for {self.tournament['name']} is awaiting TO approval"
            )
        else:
            await self.register_player(user_id)
            message_content = f"You are now registered for {self.tournament['name']}"

        await interaction.response.send_message(message_content, ephemeral=True)

    async def register_player(self, user_id):
        already_registered = await self.bot.dh.get_registration_status(
            self.tournament['_id'], user_id
        )
        if already_registered:
            return False

        guild = self.guild
        discord_user = discord.utils.get(guild.members, id=user_id)
        tournament_role = discord.utils.get(guild.roles, name=self.tournament['name'])

        if not self.debug:
            await discord_user.add_roles(tournament_role)
            await self.bot.dh.register_user(discord_user)
        else:
            await self.bot.dh.register_user(user_id, debug=True)

        user = await self.bot.dh.get_user(user_id=user_id)

        # Delegate format-specific registration (Challonge participant / Swiss event entry)
        await self.format.on_player_register(user_id, user)

        return True

    async def unregister_player(self, user_id):
        tournament = await self.get_tournament()
        if f'{user_id}' not in tournament.get('entrants', {}):
            return

        guild = self.guild
        discord_user = discord.utils.get(guild.members, id=user_id)
        tournament_role = discord.utils.get(guild.roles, name=self.tournament['name'])
        if discord_user and tournament_role:
            await discord_user.remove_roles(tournament_role)
        await self.bot.dh.unregister_player(tournament['_id'], user_id)

        # Delegate format-specific unregistration (Challonge destroy / Swiss drop)
        await self.format.on_player_unregister(user_id)

    # ─── Check-in ─────────────────────────────────────────────────────────────

    async def start_checkin(self):
        guild = self.bot.guild
        tournament = await self.get_tournament()
        tournament_category = self.get_tournament_category()
        checkin_channel = await self.get_channel('check-in')

        hide_channel = True if self.debug else False

        if not checkin_channel:
            checkin_channel = await create_channel(
                guild=guild,
                tournament_category=tournament_category,
                hide_channel=hide_channel,
                channel_name='check-in',
                channel_overwrites=CHANNEL_PERMISSIONS['check-in'],
                organizer_role=self.organizer_role
            )
            await checkin_channel.edit(position=DEFAULT_CHANNEL_POSITION)
        else:
            await checkin_channel.purge(limit=None)

        await self.send_checkin_message()

    async def send_checkin_message(self):
        tournament = await self.get_tournament()
        self.checkin_view = TournamentCheckinView(self, tournament)
        tournament_role = discord.utils.get(self.bot.guild.roles, name=tournament['name'])
        checkin_channel = await self.get_channel('check-in')
        await checkin_channel.purge(limit=None)
        embed = await self.checkin_view.generate_embed()
        message_content = f'{tournament_role.mention}'
        self.checkin_message = await checkin_channel.send(
            content=message_content, embed=embed, view=self.checkin_view
        )

    async def ping_checkin(self):
        MAXIMUM_PING_CHECKINS = 10
        tournament = await self.get_tournament()
        category = self.get_tournament_category()
        checkin_channel = discord.utils.get(category.text_channels, name='check-in')

        if not checkin_channel:
            return False

        checked_in_list = [str(player) for player in tournament.get('checked_in', [])]
        entrant_ids = list(tournament['entrants'].keys())
        missing_count = len(entrant_ids) - len(checked_in_list)

        if missing_count > MAXIMUM_PING_CHECKINS:
            return False

        for player in entrant_ids:
            if player not in checked_in_list:
                user = discord.utils.get(self.guild.members, id=int(player))
                if user:
                    await user.send(
                        f"**Reminder: Please check in for `{tournament['name']}`**!\n"
                        f"Go to {checkin_channel.mention} to check in."
                    )
        return True

    # ─── Tournament start ─────────────────────────────────────────────────────

    async def start_tournament(self):
        self.banner_filepath = await self.tc.generate_banner()
        tournament = await self.get_tournament()

        if self.debug:
            removed_players = []
        else:
            removed_players = [
                player for player in tournament['entrants'].keys()
                if int(player) not in tournament['checked_in']
            ]
        for player_id in removed_players:
            await self.unregister_player(int(player_id))

        checkin_channel = await self.get_channel('check-in')
        if checkin_channel:
            await checkin_channel.delete()

        register_channel = await self.get_channel('register')

        if self.format.needs_match_call_refresh:
            # DE/SE: delete the register channel, bracket drives match calling
            if register_channel:
                await register_channel.delete()
        else:
            # Swiss: keep register channel open with active join/leave view
            if register_channel:
                await register_channel.purge(limit=None)
                view = SwissActiveRegisterView(self)
                self.bot.add_view(view)
                embed = discord.Embed(
                    title=f"{self.tournament['name']} — Open Registration",
                    description=(
                        "The tournament has started, but you can still join or leave at any time.\n\n"
                        "**Join** to enter the next round.\n"
                        "**Leave** to drop out. If you are currently in a match, "
                        "your opponent wins by default."
                    ),
                    color=discord.Color.green()
                )
                await register_channel.send(embed=embed, view=view)
                if not self.debug:
                    overwrite = register_channel.overwrites_for(self.guild.default_role)
                    overwrite.view_channel = True
                    await register_channel.set_permissions(
                        self.guild.default_role, overwrite=overwrite
                    )

        tournament_category = self.get_tournament_category()
        matchcall_channel = discord.utils.get(tournament_category.channels, name='match-calling')
        if not matchcall_channel:
            await create_channel(
                guild=self.bot.guild,
                tournament_category=self.get_tournament_category(),
                hide_channel=True,
                channel_name='match-calling',
                channel_overwrites=CHANNEL_PERMISSIONS['match-calling'],
                organizer_role=self.organizer_role
            )

        await self.bot.dh.update_tournament_state(self.tournament['_id'], 'active')
        await self.send_instruction_message()
        await self.start_tournament_loop()

    async def send_instruction_message(self):
        event_updates_channel = await self.get_channel('event-updates')
        tournament_role = discord.utils.get(self.guild.roles, name=self.tournament['name'])
        message_content = f'{tournament_role.mention}'
        embed = discord.Embed(
            title=f"{self.tournament['name']} has started!",
            description=(
                "Look at the bracket in #event-info to see when you will be playing.\n"
                "When your match is called, a private channel will be made for you and your opponent at the top of this server.\n"
            ),
            color=discord.Color.green()
        )
        await event_updates_channel.send(content=message_content, embed=embed)

    async def start_tournament_loop(self):
        await self.format.on_match_calling_loop()
        if self.format.needs_match_call_refresh:
            await self.refresh_match_calls()

    # ─── Match calling ────────────────────────────────────────────────────────

    async def refresh_match_calls(self):
        await self.purge_match_calls()
        await self.call_matches()

    async def call_matches(self):
        tournament = await self.get_tournament()
        pending_matches = await self.ch.get_pending_matches(tournament['challonge_data']['url'])
        for match in pending_matches:
            if self.tournament_reset:
                await self.purge_match_calls()
                return
            try:
                match_data = await self.parse_match_data(match)
            except Exception as e:
                print(f"[call_matches] Error parsing match {match.get('id')}: {e}")
                continue
            if match_data is None:
                continue
            match_exists = await self.bot.dh.find_match(match_data['match_id'])
            if not match_exists and match_data['match_id'] not in self.match_calls:
                if self.autocall_matches:
                    await self.call_match(match_data)
                else:
                    await self.add_match_call(match_data)
            else:
                if match_exists and match_data['match_id'] not in self.match_calls:
                    if match_exists['state'] == 'held':
                        await self.add_match_call(match_data, match_held=True)

    async def add_match_call(self, match_data, match_held=False):
        category = self.get_tournament_category()
        channel = discord.utils.get(category.channels, name='match-calling')
        tournament = await self.get_tournament()
        player_1, player_2 = await self.get_players_from_match(match_data)

        waiting_since = await self.bot.dh.get_lobby_time(match_data['prereq_matches'])
        waiting_since = self.get_short_timestamp(waiting_since)

        bracket = match_data['bracket']
        if bracket == 'Winners':
            color = discord.Color.green()
            title = f"Winners Round {match_data['round']} - {player_1['name']} vs {player_2['name']}"
        elif bracket == 'Losers':
            color = discord.Color.red()
            title = f"Losers Round {abs(match_data['round'])} - {player_1['name']} vs {player_2['name']}"
        else:
            color = discord.Color.blue()
            title = f"Round {match_data['round']} - {player_1['name']} vs {player_2['name']}"

        embed = discord.Embed(
            title=title,
            description=f"{waiting_since}",
            color=color
        )
        match_call_view = MatchCallView(self, match_data, match_held)
        match_call_message = await channel.send(embed=embed, view=match_call_view)
        await match_call_view.add_message(match_call_message)
        self.match_calls[match_data['match_id']] = match_call_message

    async def get_lobby_name(self, match_data):
        player_1, player_2 = await self.get_players_from_match(match_data)
        round = match_data['round']
        bracket = match_data['bracket']
        if bracket == 'Winners':
            bracket_tag = 'w'
        elif bracket == 'Losers':
            bracket_tag = 'l'
        else:
            bracket_tag = 's'
        lobby_name = f"{bracket_tag}r{round}-{player_1['name']} vs {player_2['name']}"
        return lobby_name

    async def call_match(self, match_data, hold_match=False):
        guild = self.guild
        tournament = await self.get_tournament()
        player_1, player_2 = await self.get_players_from_match(match_data)
        players = [player_1['user_id'], player_2['user_id']]
        lobby_name = await self.get_lobby_name(match_data)

        async def on_complete(result):
            await self.report_match_from_result(result)

        service = MatchService(
            match_id=match_data['match_id'],
            players=players,
            stages=tournament['stagelist'],
            dh=self.bot.dh,
            on_complete=on_complete,
        )

        match_lobby = await MatchLobby.create(
            tournament_id=tournament['_id'],
            match_id=match_data['match_id'],
            lobby_name=lobby_name,
            prereq_matches=match_data['prereq_matches'],
            players=players,
            stages=tournament['stagelist'],
            num_winners=1,
            tournament_manager=self,
            datahandler=self.bot.dh,
            guild=guild,
            bracket=match_data['bracket'],
            match_service=service,
        )
        self.lobbies[match_data['match_id']] = match_lobby
        if match_data['match_id'] in self.match_calls and not hold_match:
            await self.match_calls[match_data['match_id']].delete()
        if player_1['user_id'] in tournament['dqs']:
            await match_lobby.end_reporting(winner_id=player_2['user_id'], is_dq=True)
        elif player_2['user_id'] in tournament['dqs']:
            await match_lobby.end_reporting(winner_id=player_1['user_id'], is_dq=True)
        else:
            await match_lobby.initialize_match(hold_match)

    async def start_held_match(self, match_data):
        await self.lobbies[match_data['match_id']].start_match()
        if match_data['match_id'] in self.match_calls:
            await self.match_calls[match_data['match_id']].delete()

    async def purge_match_calls(self):
        tournament_category = self.get_tournament_category()
        channel = discord.utils.get(tournament_category.channels, name='match-calling')
        if channel:
            await channel.purge(limit=None)
        self.match_calls.clear()

    # ─── Result reporting ─────────────────────────────────────────────────────

    async def report_match(self, lobby, is_dq=False):
        """
        Fallback for rehydrated lobbies that don't have a MatchService
        (i.e. the bot restarted mid-match). Builds the result dict and
        delegates to the format directly.
        """
        lobby_data = await lobby.get_lobby()
        winner_user_id = str(lobby_data['results'][0])
        loser_user_id = str(lobby_data['results'][1]) if len(lobby_data['results']) > 1 else None

        result = {
            'match_id': lobby_data['match_id'],
            'winner_id': int(winner_user_id),
            'loser_id': int(loser_user_id) if loser_user_id else None,
            'is_dq': is_dq,
        }
        await self.format.on_result(result, lobby)

    async def report_match_from_result(self, result):
        """
        Called by MatchService.on_complete. Looks up the lobby and delegates
        to the format. This is the primary result path for all new matches.
        """
        lobby = self.lobbies.get(result['match_id'])
        if lobby:
            await self.format.on_result(result, lobby)

    async def close_prereqs(self, lobby):
        lobby = await lobby.get_lobby()
        for match_id in lobby['prereq_matches']:
            lobby = await self.bot.dh.get_lobby(match_id)
            if not lobby['state'] == 'closed':
                await self.lobbies[match_id].close_lobby()

    # ─── Reset ───────────────────────────────────────────────────────────────

    async def reset_match(self, lobby):
        tournament = await self.get_tournament()
        match_reset = await self.ch.reset_match(tournament['challonge_data']['id'], lobby['match_id'])
        dependent_matches = await self.bot.dh.get_dependent_matches(lobby['match_id'])
        for lobby in dependent_matches:
            await self.bot.lh.delete_lobby(lobby)
        return match_reset

    async def reset_report(self, kwargs):
        lobby = kwargs.get('lobby')
        await self.lobbies[lobby['match_id']].reset_report()
        await self.format.on_reset_report(lobby)

    async def reset_tournament(self, kwargs):
        self.tournament_reset = True
        tournament = await self.get_tournament()
        for lobby in self.lobbies:
            await self.lobbies[lobby].delete_lobby()
        await self.format.on_reset()
        await self.bot.dh.update_tournament_state(self.tournament['_id'], 'registration')
        await self.bot.dh.clear_lobbies(self.tournament['_id'])
        await self.purge_match_calls()
        await self.progress_tournament()
        self.tournament_reset = False

    # ─── End tournament ───────────────────────────────────────────────────────

    async def end_tournament(self):
        for lobby in self.lobbies:
            await self.lobbies[lobby].close_lobby()
        await self.format.on_tournament_end()

    async def finalize_tournament(self):
        await self.remove_tournament_from_discord()
        if self.debug:
            await self.delete_tournament()

    async def prompt_end_tournament(self):
        embed = discord.Embed(
            title="End Tournament",
            description="All matches have concluded. Would you like to end the tournament?",
            color=discord.Color.yellow()
        )
        view = EndTournamentView(self)
        tournament_category = self.get_tournament_category()
        channel = discord.utils.get(tournament_category.channels, name='bot-control')
        await channel.send(embed=embed, view=view)

    async def post_final_results(self):
        channel = discord.utils.get(self.bot.guild.channels, id=RESULTS_CHANNEL_ID)

        swiss_event = await self.bot.dh.get_swiss_event_by_tournament(self.tournament['_id'])
        if swiss_event:
            standings = await self.bot.dh.swiss_get_standings(swiss_event['_id'])
            overall_winner = ''
            results = ''
            for i, player in enumerate(standings):
                rank = i + 1
                mention = f"<@{player['discord_id']}>"
                if rank == 1:
                    emoji = RESULT_EMOJIS['1st']
                    overall_winner = f"**{RESULT_EMOJIS['trophy']} Overall Winner: {player['username']}**\n\n"
                elif rank == 2:
                    emoji = RESULT_EMOJIS['2nd']
                elif rank == 3:
                    emoji = RESULT_EMOJIS['3rd']
                elif rank <= 8:
                    emoji = RESULT_EMOJIS['medal']
                else:
                    emoji = ''
                results += f"{rank}: {mention} ({player['points']}pts, {player['wins']}W-{player['losses']}L) {emoji}\n"
            message_content = overall_winner + results
        else:
            challonge_id = self.tournament['challonge_data']['id']
            final_results = await self.ch.get_final_results(challonge_id)
            overall_winner = ''
            results = ''
            for player in final_results:
                discord_id = await self.bot.dh.get_user_by_challonge(self.tournament['_id'], player['id'])
                mention = f"<@{discord_id}>" if discord_id else player['name']
                rank = player['final_rank']
                if rank == 1:
                    emoji = RESULT_EMOJIS['1st']
                    overall_winner = f"**{RESULT_EMOJIS['trophy']} Overall Winner: {player['name']}**\n\n"
                elif rank == 2:
                    emoji = RESULT_EMOJIS['2nd']
                elif rank == 3:
                    emoji = RESULT_EMOJIS['3rd']
                elif 3 < rank <= 8:
                    emoji = RESULT_EMOJIS['medal']
                else:
                    emoji = ''
                results += f"{rank}: {mention} {emoji}\n"
            message_content = overall_winner + results

        tournament = await self.get_tournament()
        if 'color' in tournament.get('config', {}):
            color = discord.Color.from_str(tournament['config']['color'])
        else:
            color = get_random_color()

        embed = discord.Embed(
            title=f"{self.tournament['name']}",
            description=message_content,
            color=color
        )

        if self.format.shows_bracket_link:
            label = f"{INDICATOR_EMOJIS['link']} Bracket"
            bracket_link = await get_bracket_link(self.tournament['challonge_data']['url'])
            view = LinkView(label, bracket_link)
            await channel.send(embed=embed, view=view)
        else:
            await channel.send(embed=embed)

    # ─── Delete tournament ────────────────────────────────────────────────────

    async def delete_tournament(self, kwargs=None):
        tournament = await self.get_tournament()
        await self.remove_tournament_from_discord()
        if tournament['state'] == 'finished':
            return False
        for lobby in self.lobbies:
            await self.lobbies[lobby].delete_lobby()
        await self.format.on_tournament_delete()
        await self.bot.dh.delete_tournament(tournament['_id'])
        self.bot.th.tournaments.pop(tournament['_id'], None)

    async def remove_tournament_from_discord(self):
        tournament = await self.get_tournament()
        guild = self.bot.guild
        tournament_category = self.get_tournament_category()
        for channel in tournament_category.channels:
            await channel.delete()
        tournament_role = discord.utils.get(guild.roles, name=f"{tournament['name']}")
        tournament_to_role = discord.utils.get(guild.roles, name=f"{tournament['name']} TO")
        if tournament_role:
            await tournament_role.delete()
        if tournament_to_role:
            await tournament_to_role.delete()
        if tournament_category:
            await tournament_category.delete()

    # ─── Player management ────────────────────────────────────────────────────

    async def get_players_from_match(self, match_data):
        player_1_id = match_data['player_1']
        player_2_id = match_data['player_2']
        player_1 = await self.bot.dh.get_user(user_id=player_1_id)
        player_2 = await self.bot.dh.get_user(user_id=player_2_id)
        if player_1 is None or player_2 is None:
            raise ValueError(
                f"[get_players_from_match] Could not find users: "
                f"p1={player_1_id} → {player_1}, p2={player_2_id} → {player_2}"
            )
        return player_1, player_2

    async def disqualify_player(self, user_id):
        player_registered = await self.bot.dh.get_registration_status(self.tournament['_id'], user_id)
        if not player_registered:
            return False
        lobby_data = await self.bot.dh.find_player_match(self.tournament['_id'], user_id)
        if lobby_data:
            lobby = self.lobbies[lobby_data['match_id']]
            winner_id = (set(lobby_data['players']) - {user_id}).pop()
            await lobby.end_reporting(winner_id, is_dq=True)
        return await self.bot.dh.disqualify_player(self.tournament['_id'], user_id)

    async def undisqualify_player(self, user_id):
        return await self.bot.dh.undisqualify_player(self.tournament['_id'], user_id)

    # ─── Match data parsing ───────────────────────────────────────────────────

    async def parse_match_data(self, match):
        tournament = await self.get_tournament()
        format = tournament['format']
        player_1_id = await self.bot.dh.get_user_by_challonge(tournament['_id'], match['player1_id'])
        player_2_id = await self.bot.dh.get_user_by_challonge(tournament['_id'], match['player2_id'])

        if player_1_id is None or player_2_id is None:
            print(f"[parse_match_data] Could not resolve players for match {match['id']}: "
                f"p1={match['player1_id']} → {player_1_id}, p2={match['player2_id']} → {player_2_id}")
            return None

        round_number = match['round']
        if format == 'single elimination':
            bracket = ''
        elif format == 'double elimination':
            bracket = 'Winners' if round_number > 0 else 'Losers'
        else:
            bracket = ''

        pre_reqs = match['prerequisite_match_ids_csv']
        if pre_reqs == '':
            prereq_matches = []
        elif isinstance(pre_reqs, float):
            prereq_matches = [int(pre_reqs)]
        elif isinstance(pre_reqs, str):
            prereq_matches = [int(p) for p in pre_reqs.split(',')]

        match_data = {
            'player_1': int(player_1_id),
            'player_2': int(player_2_id),
            'match_id': match['id'],
            'round': round_number,
            'bracket': bracket,
            'tournament': tournament['name'],
            'prereq_matches': prereq_matches
        }
        return match_data

    # ─── Seeding ─────────────────────────────────────────────────────────────

    async def generate_seeding_link(self) -> str:
        from web.seeding_server import generate_token
        tournament = await self.get_tournament()
        challonge_url = tournament['challonge_data']['url']
        token = generate_token(str(tournament['_id']), challonge_url)
        base_url = os.getenv('WEB_BASE_URL', 'http://localhost:8080').strip()
        return f"{base_url}/seeding?token={token}"

    # ─── Autocall ────────────────────────────────────────────────────────────

    async def toggle_autocall(self, state):
        self.autocall_matches = state

    # ─── Utilities ───────────────────────────────────────────────────────────

    async def get_tournament(self):
        tournament = await self.bot.dh.get_tournament_by_id(self.tournament['_id'])
        self.tournament = tournament
        return tournament

    def get_tournament_category(self):
        return discord.utils.get(self.guild.categories, id=self.tournament['category_id'])

    def get_short_timestamp(self, timestamp):
        return timestamp.strftime("%I:%M%p").lstrip("0")

    async def get_channel(self, name):
        tournament_category = self.get_tournament_category()
        return discord.utils.get(tournament_category.channels, name=name)

    async def get_state(self):
        tournament = await self.get_tournament()
        return tournament['state']

    async def add_view(self, view):
        self.bot.add_view(view)

    async def edit_tournament_config(self, **kwargs):
        for key, value in kwargs.items():
            if key in ('name', 'date', 'stagelist'):
                pass
        await self.bot.dh.edit_tournament_config(self.tournament['_id'], **kwargs)