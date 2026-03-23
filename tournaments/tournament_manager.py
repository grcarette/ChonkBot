from .challonge_handler import ChallongeHandler
from .match_service import MatchService
from formats import make_format
from datetime import datetime

from utils.channel_utils import CHANNEL_PERMISSIONS, NONDEFAULT_CHANNELS, STAFF_PERMISSIONS, CHANNEL_ORDER, create_channel
from utils.emojis import RESULT_EMOJIS, INDICATOR_EMOJIS
from utils.discord_preset_colors import get_random_color
from utils.get_bracket_link import get_bracket_link
from utils.validate_stagecode import validate_stagecode

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
import asyncio

RESULTS_CHANNEL_ID = 1346422769721544754
DEFAULT_CHANNEL_POSITION = 2

CHECKIN_REMINDER_SECONDS = 300
CHECKIN_POLL_INTERVAL   = 60
CHECKIN_AUTODQ_SECONDS = 6000

class TournamentManager:
    def __init__(self, bot, tournament):
        self.bot = bot
        self.tournament = tournament
        self.ch = ChallongeHandler()
        self.guild = self.bot.guild
        self.lobbies = {}
        self.bot_control = None
        self.tournament_reset = False
        self.called_match_ids = set()
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

        self.tc = None  # TournamentControl removed — web dashboard handles all controls

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
                match_service=None,
            )
            self.lobbies[lobby['match_id']] = match_lobby
            # Track already-called matches so call_matches() won't re-call them
            self.called_match_ids.add(lobby['match_id'])
            if lobby['state'] == 'initialized':
                pass
            elif lobby['state'] == 'checkin':
                self.bot.add_view(CheckinView(match_lobby))
            elif lobby['state'] == 'stage_bans':
                self.bot.add_view(BanStagesButton(match_lobby))
            elif lobby['state'] == 'reporting':
                self.bot.add_view(MatchReportButton(match_lobby))

        tournament = await self.get_tournament()

        if tournament['state'] == 'initialize':
            await self.progress_tournament()
        if tournament['state'] == 'setup':
            pass
        elif tournament['state'] == 'registration':
            self.bot.add_view(RegisterControlView(self))
        elif tournament['state'] == 'checkin':
            await self.send_checkin_message()
        elif tournament['state'] == 'active':
            if self.format:
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
        tournament = await self.get_tournament()
        guild      = self.bot.guilds[0]
        hide       = self.debug  # debug tournaments stay hidden

        organizer_role  = await guild.create_role(name=f"{tournament['name']} TO")
        tournament_role = await guild.create_role(name=f"{tournament['name']}")
        self.organizer_role = organizer_role

        for user_id in tournament['organizers']:
            member = discord.utils.get(guild.members, id=user_id)
            if member:
                await member.add_roles(organizer_role)

        category_overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            organizer_role:     discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_messages=True,
                embed_links=True,
                attach_files=True,
                read_message_history=True,
                add_reactions=True,
                use_external_emojis=True,
            ),
        }
        tournament_category = await guild.create_category(
            tournament['name'], overwrites=category_overwrites
        )
        await self.bot.dh.add_category_to_tournament(tournament['name'], tournament_category.id)
        self.tournament['category_id'] = tournament_category.id

        PUBLISH_CHANNELS = [
            ('event-info',     'read_only', True),
            ('event-updates',  'read_only', True),
            ('register',       'read_only', False),  # always hidden until open_registration
            ('event-chat',     'open',      True),
            ('organizer-chat', 'private',   False),  # always private
        ]

        for channel_name, perm_type, public in PUBLISH_CHANNELS:
            # Debug tournaments keep everything hidden
            visible = public and not hide

            overwrites = {organizer_role: STAFF_PERMISSIONS}
            if perm_type == 'read_only':
                overwrites[guild.default_role] = discord.PermissionOverwrite(
                    view_channel=visible,
                    send_messages=False,
                    read_message_history=True,
                    add_reactions=True,
                    use_external_emojis=True,
                )
            elif perm_type == 'open':
                overwrites[guild.default_role] = discord.PermissionOverwrite(
                    view_channel=visible,
                    send_messages=True,
                    embed_links=True,
                    attach_files=True,
                    read_message_history=True,
                    add_reactions=True,
                    use_external_emojis=True,
                )
            elif perm_type == 'private':
                overwrites[guild.default_role] = discord.PermissionOverwrite(
                    view_channel=False,
                )
            await guild.create_text_channel(
                channel_name, category=tournament_category, overwrites=overwrites
            )
        await self.post_event_info()

        for i, name in enumerate(['event-info', 'event-updates', 'event-chat', 'organizer-chat']):
            ch = discord.utils.get(tournament_category.channels, name=name)
            if ch:
                await ch.edit(position=i)
        await self.sync_channel_order()

    # ─── Registration ─────────────────────────────────────────────────────────

    async def set_registration_visibility(self, visible: bool):
        if self.debug:
            return
        channel = await self.get_channel('register')
        if not channel:
            return
        await channel.set_permissions(
            self.guild.default_role,
            view_channel=visible,
            send_messages=False,
            read_message_history=True,
            add_reactions=True,
            use_external_emojis=True,
        )

    async def open_registration(self):
        tournament = await self.get_tournament()

        if self.debug:
            for i in range(8):
                try:
                    await self.register_player(i)
                except Exception as e:
                    print(f"[open_registration] Failed to register debug player {i}: {e}")

        if tournament['state'] == 'registration':
            register_channel = await self.get_channel('register')
            if register_channel:
                history = [msg async for msg in register_channel.history(limit=1)]
                if not history:
                    view  = RegisterControlView(self)
                    embed = discord.Embed(
                        title=f"Register for {self.tournament['name']}",
                        color=discord.Color.green()
                    )
                    await register_channel.send(embed=embed, view=view)
                await self.set_registration_visibility(True)
            else:
                guild               = self.bot.guild
                tournament_category = self.get_tournament_category()
                register_channel    = await create_channel(
                    guild=guild,
                    tournament_category=tournament_category,
                    hide_channel=False,
                    channel_name='register',
                    channel_overwrites=CHANNEL_PERMISSIONS['register'],
                    organizer_role=self.organizer_role
                )
                view  = RegisterControlView(self)
                embed = discord.Embed(
                    title=f"Register for {self.tournament['name']}",
                    color=discord.Color.green()
                )
                await register_channel.send(embed=embed, view=view)

        elif tournament['state'] == 'checkin':
            self.checkin_view.register_button.disabled = False
            await self.checkin_message.edit(view=self.checkin_view)

        await self.bot.dh.open_registration(tournament['_id'])
        await self.sync_channel_order()

    async def close_registration(self):
        tournament = await self.get_tournament()
        if tournament['state'] == 'registration':
            await self.set_registration_visibility(False)
        elif tournament['state'] == 'checkin':
            self.checkin_view.register_button.disabled = True
            await self.checkin_message.edit(view=self.checkin_view)
        await self.bot.dh.close_registration(tournament['_id'])

    async def create_registration_approval(self, user_id, interaction):
        allowed = await self.format.on_registration_gate(user_id, interaction)
        if not allowed:
            return

        already_registered = await self.bot.dh.get_registration_status(
            self.tournament['_id'], user_id
        )
        if already_registered:
            await interaction.followup.send(
                "You are already registered for this event.", ephemeral=True
            )
            return

        requests = await self.bot.dh.get_registration_requests(self.tournament['_id'])
        if user_id in requests:
            await interaction.followup.send(
                "Your registration is already awaiting approval.", ephemeral=True
            )
            return

        await self.bot.dh.add_registration_request(self.tournament['_id'], user_id)
        await interaction.followup.send(
            f"Your registration for {self.tournament['name']} is awaiting TO approval.",
            ephemeral=True
        )

    async def register_player(self, user_id):
        already_registered = await self.bot.dh.get_registration_status(
            self.tournament['_id'], user_id
        )
        if already_registered:
            return False

        tournament = await self.get_tournament()
        if tournament.get('config', {}).get('approved_registration'):
            await self.bot.dh.add_registration_request(tournament['_id'], user_id)
            return 'pending'

        guild = self.guild
        discord_user = discord.utils.get(guild.members, id=user_id)
        tournament_role = discord.utils.get(guild.roles, name=self.tournament['name'])

        if not self.debug:
            await discord_user.add_roles(tournament_role)
            await self.bot.dh.register_user(discord_user)
        else:
            await self.bot.dh.register_user(user_id, debug=True)

        user = await self.bot.dh.get_user(user_id=user_id)

        await self.format.on_player_register(user_id, user)
        return True

    async def unregister_player(self, user_id):
        tournament = await self.get_tournament()
        entrants = tournament.get('entrants', [])
        if isinstance(entrants, dict):
            entrant_ids = [int(k) for k in entrants.keys()]
        else:
            entrant_ids = [e['discord_id'] for e in entrants]

        if int(user_id) not in entrant_ids:
            return

        guild = self.guild
        discord_user = discord.utils.get(guild.members, id=user_id)
        tournament_role = discord.utils.get(guild.roles, name=self.tournament['name'])
        if discord_user and tournament_role:
            await discord_user.remove_roles(tournament_role)

        await self.format.on_player_unregister(user_id)
        await self.bot.dh.unregister_player(tournament['_id'], user_id)

    async def register_player_direct(self, user_id):
        """Register a player directly, bypassing the approval check. Used by web approval flow."""
        already_registered = await self.bot.dh.get_registration_status(
            self.tournament['_id'], user_id
        )
        if already_registered:
            return False

        discord_user   = discord.utils.get(self.guild.members, id=user_id)
        tournament_role = discord.utils.get(self.guild.roles, name=self.tournament['name'])

        if not self.debug:
            if discord_user and tournament_role:
                await discord_user.add_roles(tournament_role)
            await self.bot.dh.register_user(discord_user)
        else:
            await self.bot.dh.register_user(user_id, debug=True)

        user = await self.bot.dh.get_user(user_id=user_id)
        await self.format.on_player_register(user_id, user)
        return True

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

            failed_pings = []
            for player in entrant_ids:
                if player not in checked_in_list:
                    user = discord.utils.get(self.guild.members, id=int(player))
                    if user:
                        try:
                            await user.send(
                                f"**Reminder: Please check in for `{tournament['name']}`**!\n"
                                f"Go to {checkin_channel.mention} to check in."
                            )
                        except discord.Forbidden:
                            failed_pings.append(user.display_name)

            if failed_pings:
                try:
                    channel = await self.get_channel('bot-control')
                    if channel:
                        names = ', '.join(f'**{name}**' for name in failed_pings)
                        embed = discord.Embed(
                            title="⚠️ Check-in Ping Failed",
                            description=(
                                f"Could not DM the following players (DMs likely disabled):\n{names}\n\n"
                                f"You may want to ping them manually in {checkin_channel.mention}."
                            ),
                            color=discord.Color.orange()
                        )
                        await channel.send(embed=embed)
                except Exception as e:
                    print(f"[ping_checkin] Failed to post DM failure alert: {e}")

            return True

    # ─── Tournament start ─────────────────────────────────────────────────────

    async def start_tournament(self):
        self.banner_filepath = await self.generate_banner()
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

        await self.bot.dh.update_tournament_state(self.tournament['_id'], 'active')
        await self.send_instruction_message()
        await self.format.on_tournament_start()
        await self.start_tournament_loop()

    async def send_instruction_message(self):
        event_updates_channel = await self.get_channel('event-updates')
        tournament_role = discord.utils.get(self.guild.roles, name=self.tournament['name'])
        message_content = f'{tournament_role.mention}'

        if self.format and not self.format.needs_match_call_refresh:
            # Swiss
            description = (
                "Matches will be called in rounds. "
                "When your match is ready, a private channel will be made for you and your opponent at the top of this server.\n"
            )
        else:
            # DE / SE
            description = (
                "Look at the bracket in #event-info to see when you will be playing.\n"
                "When your match is called, a private channel will be made for you and your opponent at the top of this server.\n"
            )

        embed = discord.Embed(
            title=f"{self.tournament['name']} has started!",
            description=description,
            color=discord.Color.green()
        )
        await event_updates_channel.send(content=message_content, embed=embed)

    async def start_tournament_loop(self):
        await self.format.on_match_calling_loop()
        self.start_checkin_reminder_loop()

    # ─── Match calling ────────────────────────────────────────────────────────
    # Matches are called automatically on tournament start and after each result.
    # The web dashboard exposes pending matches and can trigger call_match /
    # hold_match via POST /api/tournament/{id}/action with action='call_match'
    # or 'hold_match', passing match_id in the request body.

    async def get_pending_matches(self) -> list[dict]:
        """
        Return all pending Challonge matches that have not yet been called.
        Used by the web API to display uncalled matches on the dashboard.
        """
        tournament = await self.get_tournament()

        raw_matches = await self.ch.get_pending_matches(tournament['challonge_data']['url'])
        result = []

        for match in raw_matches:
            try:
                match_data = await self.parse_match_data(match)
            except Exception as e:
                continue
            if match_data is None:
                continue
            match_exists = await self.bot.dh.find_match(match_data['match_id'])
            if not match_exists and match_data['match_id'] not in self.called_match_ids:
                result.append(match_data)

        return result

    async def call_matches(self):
        """
        Call all currently pending matches. Only triggered explicitly
        from the web dashboard (Call All button or Auto Call).
        """
        tournament = await self.get_tournament()
        pending_matches = await self.ch.get_pending_matches(tournament['challonge_data']['url'])
        for match in pending_matches:
            if self.tournament_reset:
                return
            try:
                match_data = await self.parse_match_data(match)
            except Exception as e:
                print(f"[call_matches] Error parsing match {match.get('id')}: {e}")
                await self._alert_unresolvable_match(match, str(e))
                continue
            if match_data is None:
                await self._alert_unresolvable_match(match)
                continue
            if match_data['match_id'] not in self.called_match_ids:
                try:
                    await self.call_match(match_data)
                except Exception as e:
                    print(f"[call_matches] Failed to call match {match_data['match_id']}: {e}")
                    await self._alert_unresolvable_match(match, str(e))

    async def _alert_unresolvable_match(self, match, error: str = None):
        """
        Posts a visible warning to bot-control when a Challonge match cannot
        be resolved to Discord users. Without this, the match is silently
        skipped and TOs have no way to know it was missed.
        """
        match_id = match.get('id', 'unknown')
        p1 = match.get('player1_id', '?')
        p2 = match.get('player2_id', '?')

        description = (
            f"Match **{match_id}** (Challonge players `{p1}` vs `{p2}`) "
            f"could not be resolved to Discord users and was skipped.\n\n"
            f"This usually means one or both players are not registered in the database. "
            f"Use `/call_match` to call this match manually once the issue is resolved."
        )
        if error:
            description += f"\n\n**Error:** `{error}`"

        embed = discord.Embed(
            title="⚠️ Unresolvable Match",
            description=description,
            color=discord.Color.orange()
        )

        try:
            channel = await self.get_channel('bot-control')
            if channel:
                await channel.send(embed=embed)
        except Exception as e:
            print(f"[_alert_unresolvable_match] Failed to post alert: {e}")

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
        """
        Create a lobby channel for a match and initialize it.
        Called automatically by call_matches(), or triggered from the web dashboard
        via POST /api/tournament/{id}/action with action='call_match'.
        """
        # Hard guard: never create a lobby if one already exists for this match
        if match_data['match_id'] in self.called_match_ids:
            print(f"[call_match] Match {match_data['match_id']} already called, skipping.")
            return
        if await self.bot.dh.find_match(match_data['match_id']):
            print(f"[call_match] Match {match_data['match_id']} already exists in DB, skipping.")
            self.called_match_ids.add(match_data['match_id'])
            return

        # Add to called set immediately before any async work so concurrent calls are blocked
        self.called_match_ids.add(match_data['match_id'])

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

        if player_1['user_id'] in tournament['dqs']:
            await match_lobby.end_reporting(winner_id=player_2['user_id'], is_dq=True)
        elif player_2['user_id'] in tournament['dqs']:
            await match_lobby.end_reporting(winner_id=player_1['user_id'], is_dq=True)
        else:
            await match_lobby.initialize_match(hold_match)

    async def start_held_match(self, match_data):
        """
        Start a previously held match. Can be triggered from the web dashboard
        via POST /api/tournament/{id}/action with action='start_held_match'.
        """
        await self.lobbies[match_data['match_id']].start_match()

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
        lobby = self.lobbies.get(result['match_id'])
        if lobby:
            await self.format.on_result(result, lobby)
            # If autocall is on, call any newly available matches
            if getattr(self, 'autocall_matches', False) and self.format.needs_match_call_refresh:
                await self.call_matches()

    async def close_prereqs(self, lobby):
        lobby_data = await lobby.get_lobby()
        for match_id in lobby_data['prereq_matches']:
            prereq_data = await self.bot.dh.get_lobby(match_id)
            if prereq_data['state'] != 'closed':
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
        if self.format and hasattr(self.format, 'on_reset'):
            await self.format.on_reset()
        self.called_match_ids.clear()
        await self.progress_tournament()
        self.tournament_reset = False

    # ─── End tournament ───────────────────────────────────────────────────────

    async def end_tournament(self):
        self.stop_checkin_reminder_loop()
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
        if tournament.get('category_id'):
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
        if not tournament.get('category_id'):
            return

        guild = self.bot.guild
        tournament_category = self.get_tournament_category()

        if tournament_category:
            for channel in list(tournament_category.channels):
                try:
                    await channel.delete()
                except discord.NotFound:
                    pass
            await tournament_category.delete()

        tournament_role = discord.utils.get(guild.roles, name=f"{tournament['name']}")
        tournament_to_role = discord.utils.get(guild.roles, name=f"{tournament['name']} TO")
        if tournament_role:
            await tournament_role.delete()
        if tournament_to_role:
            await tournament_to_role.delete()

    # ─── Player management ────────────────────────────────────────────────────

    async def get_players_from_match(self, match_data):
        player_1_id = match_data['player_1']
        player_2_id = match_data['player_2']
        player_1 = await self.bot.dh.get_user(user_id=player_1_id)
        player_2 = await self.bot.dh.get_user(user_id=player_2_id)

        # In debug mode, synthesize a fake user if the DB doc is missing.
        # This handles stale tournaments where debug users were never persisted.
        if self.debug:
            if player_1 is None:
                player_1 = {'user_id': player_1_id, 'name': f'Debug User {player_1_id}'}
            if player_2 is None:
                player_2 = {'user_id': player_2_id, 'name': f'Debug User {player_2_id}'}

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

    def start_checkin_reminder_loop(self):
        self._checkin_reminded = set()
        self._checkin_autodqd = set()
        self._checkin_reminder_task = asyncio.create_task(
            self._checkin_reminder_loop()
        )

    async def _checkin_reminder_loop(self):
        """
        Every CHECKIN_POLL_INTERVAL seconds, query the DB for lobbies in 'checkin'
        state that have been waiting longer than CHECKIN_REMINDER_SECONDS, then DM
        any players who haven't checked in yet and haven't already been reminded.
        """
        while True:
            await asyncio.sleep(CHECKIN_POLL_INTERVAL)
            try:
                await self._send_checkin_reminders()
            except Exception as e:
                print(f"[checkin_reminder_loop] Unexpected error: {e}")

    async def _send_checkin_reminders(self):
        if self.debug:
            return
        stale_lobbies = await self.bot.dh.get_stale_checkin_lobbies(
            self.tournament['_id'], CHECKIN_REMINDER_SECONDS
        )

        for lobby in stale_lobbies:
            match_id = lobby['match_id']
            checked_in = set(lobby.get('checked_in', []))
            missing = [p for p in lobby['players'] if p not in checked_in]

            if not missing:
                continue

            # ── Auto-DQ check (10 minutes) ────────────────────────────────────
            elapsed = (datetime.now() - lobby['state_timestamp']).total_seconds()
            if elapsed >= CHECKIN_AUTODQ_SECONDS:
                if match_id not in self._checkin_autodqd:
                    self._checkin_autodqd.add(match_id)
                    await self._auto_dq_lobby(lobby, missing)
                continue  # don't send a reminder after DQ'ing

            # ── Reminder DM (5 minutes) ───────────────────────────────────────
            for player_id in missing:
                key = (match_id, player_id)
                if key in self._checkin_reminded:
                    continue

                user = discord.utils.get(self.guild.members, id=player_id)
                if not user:
                    continue

                lobby_channel = discord.utils.get(
                    self.guild.channels, id=lobby.get('channel_id')
                )
                channel_mention = lobby_channel.mention if lobby_channel else 'your match channel'

                try:
                    await user.send(
                        f"**Reminder:** You haven't checked in for your match in "
                        f"**{self.tournament['name']}**!\n"
                        f"Go to {channel_mention} and click **Check in** or you may be disqualified."
                    )
                    self._checkin_reminded.add(key)
                except discord.Forbidden:
                    self._checkin_reminded.add(key)

    def stop_checkin_reminder_loop(self):
        task = getattr(self, '_checkin_reminder_task', None)
        if task and not task.done():
            task.cancel()
        self._checkin_reminded = set()
        self._checkin_autodqd = set()

    async def _auto_dq_lobby(self, lobby, missing_players):
        """
        Resolve a lobby where one or both players failed to check in.
        The higher-seeded player (lower seed number) wins.
        If seeds can't be determined, DQ the first missing player and log a warning.
        Posts a notification to the lobby channel.
        """
        match_id = lobby['match_id']
        all_players = lobby['players']

        try:
            winner_id = await self._get_higher_seed(all_players)
        except Exception as e:
            print(f"[auto_dq] Could not determine seeds for match {match_id}: {e}. "
                  f"Defaulting to first player in list.")
            winner_id = all_players[0]

        loser_id = next(p for p in all_players if p != winner_id)

        match_lobby = self.lobbies.get(match_id)
        if match_lobby and match_lobby.channel:
            missing_mentions = ' '.join(f'<@{p}>' for p in missing_players)
            try:
                await match_lobby.channel.send(
                    f"⏰ **Check-in time expired.**\n"
                    f"{missing_mentions} did not check in within the time limit.\n"
                    f"<@{winner_id}> advances by seed. <@{loser_id}> has been disqualified."
                )
            except Exception:
                pass

        await self.disqualify_player(loser_id)

    async def _get_higher_seed(self, player_ids):
        """
        Return the player_id with the lower seed number (higher seeding).
        Fetches participant data from Challonge.
        """
        tournament = await self.get_tournament()
        entrants = tournament['entrants']

        challonge_to_discord = {
            int(challonge_id): int(discord_id)
            for discord_id, challonge_id in entrants.items()
            if challonge_id is not None
        }

        participants = await self.ch.get_participants(tournament['challonge_data']['url'])

        seed_map = {}
        for p in participants:
            discord_id = challonge_to_discord.get(p['id'])
            if discord_id in player_ids:
                seed_map[discord_id] = p.get('seed') or 9999

        if not seed_map:
            raise ValueError("No seed data found for lobby players")

        return min(seed_map, key=lambda pid: seed_map[pid])

    async def end_swiss_tournament_flow(self, kwargs=None):
        """
        Force-end a Swiss tournament: close lobbies, post results, finalize.
        Called by /end_swiss_tournament via ConfirmationView.
        """
        swiss_event = await self.bot.dh.get_swiss_event_by_tournament(self.tournament['_id'])
        if swiss_event:
            await self.bot.dh.update_swiss_state(swiss_event['_id'], 'finished')

        if hasattr(self.format, 'manager'):
            self.format.manager.running = False

        await self.end_tournament()
        await self.post_final_results()
        await self.bot.dh.update_tournament_state(self.tournament['_id'], 'finished')
        await self.finalize_tournament()

    async def post_event_info(self):
        """Post or update the event-info embed."""
        tournament = await self.get_tournament()
        channel    = await self.get_channel('event-info')
        if not channel:
            return

        if 'color' in tournament.get('config', {}):
            from utils.color_utils import discord_color_from_hex
            color = discord_color_from_hex(tournament['config']['color'])
        else:
            color = discord.Color.blue()

        organizer_list = []
        for user_id in tournament['organizers']:
            member = discord.utils.get(self.guild.members, id=user_id)
            if member:
                organizer_list.append(member.mention)
        organizer_str = '\n-'.join(organizer_list) if organizer_list else 'N/A'

        description = (
            f"**Date:** {tournament.get('date', 'TBA')}\n"
            f"**Format:** {tournament.get('format', '')}\n"
            f"**TO's:**\n-{organizer_str}\n"
        )

        if tournament.get('config', {}).get('display_entrants'):
            entrants = tournament.get('entrants', {})
            if entrants:
                names = []
                for i, discord_id_str in enumerate(entrants.keys(), start=1):
                    user = await self.bot.dh.get_user(user_id=int(discord_id_str))
                    name = user['name'] if user else f'Unknown ({discord_id_str})'
                    names.append(f"{i}. {name}")
                description += f"\n**Entrants ({len(entrants)}):**\n" + '\n'.join(names)

        embed = discord.Embed(title=tournament['name'], description=description, color=color)

        bot_id = self.bot.id
        existing = None
        async for msg in channel.history(limit=20, oldest_first=True):
            if msg.author.id == bot_id and msg.embeds:
                existing = msg
                break

        if existing:
            await existing.edit(embed=embed)
        else:
            await channel.send(embed=embed)

    async def publish_stagelist(self):
        from utils.embed_utils import create_stage_embed
        tournament = await self.get_tournament()
        if not tournament.get('stagelist'):
            return

        stagelist_channel = await self.get_channel('stagelist')
        if not stagelist_channel:
            guild               = self.bot.guilds[0]
            tournament_category = self.get_tournament_category()
            stagelist_channel   = await guild.create_text_channel(
                'stagelist',
                category=tournament_category,
                overwrites={
                    guild.default_role: discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=False,
                        read_message_history=True,
                    ),
                    self.organizer_role: STAFF_PERMISSIONS,
                }
            )
        await stagelist_channel.purge(limit=None)

        for stage_code in tournament['stagelist']:
            stage = await self.bot.dh.get_stage(code=stage_code)
            if stage:
                embed = await create_stage_embed(stage)
                await stagelist_channel.send(embed=embed)

        await self.bot.dh.edit_tournament_config(
            self.tournament['_id'], stagelist_published=True
        )
        await self.sync_channel_order()

    async def generate_banner(self):
        """Generate the stage banner image for use at tournament start."""
        from handlers.ban_graphic_generator import StageBannerGenerator
        tournament      = await self.get_tournament()
        sbg             = StageBannerGenerator()
        stage_list_data = []

        for map_code in tournament['stagelist']:
            stage = await self.bot.dh.get_stage(code=map_code)
            if stage:
                stage_list_data.append(stage)

        while len(stage_list_data) < 5:
            random_stages = await self.bot.dh.get_random_stages(1)
            if random_stages:
                stage_list_data.append(random_stages[0])

        filepath = await sbg.generate_banner(stage_list_data, tournament)
        return filepath

    async def sync_channel_order(self):
        """Reorder channels in the tournament category to match CHANNEL_ORDER, only moving what's necessary."""
        tournament_category = self.get_tournament_category()
        if not tournament_category:
            return

        channels = {ch.name: ch for ch in tournament_category.channels}

        desired = [channels[name] for name in CHANNEL_ORDER if name in channels]

        base_position = min(ch.position for ch in desired) if desired else 0

        for i, ch in enumerate(desired):
            expected = base_position + i
            if ch.position != expected:
                await ch.edit(position=expected)

    async def revert_tournament(self):
            """
            Revert the tournament one step back.
            checkin → registration: delete check-in channel, clear checked_in, re-open registration.
            active  → checkin: only if no matches have been reported. Close lobby channels,
                            clear lobbies, restore check-in channel.
            """
            tournament = await self.get_tournament()
            state = tournament['state']

            if state == 'checkin':
                # Delete the check-in channel
                checkin_channel = await self.get_channel('check-in')
                if checkin_channel:
                    await checkin_channel.delete()

                # Clear all check-in data
                await self.bot.dh.clear_checkin(tournament['_id'])

                # Restore registration channel visibility and re-post the register view
                register_channel = await self.get_channel('register')
                if register_channel:
                    history = [msg async for msg in register_channel.history(limit=1)]
                    if not history:
                        view  = RegisterControlView(self)
                        embed = discord.Embed(
                            title=f"Register for {self.tournament['name']}",
                            color=discord.Color.green()
                        )
                        await register_channel.send(embed=embed, view=view)
                    await self.set_registration_visibility(True)

                await self.bot.dh.open_registration(tournament['_id'])
                await self.bot.dh.update_tournament_state(self.tournament['_id'], 'registration')

            elif state == 'active':
                self.stop_checkin_reminder_loop()

                for lobby in self.lobbies.values():
                    await lobby.delete_lobby()
                self.lobbies.clear()
                self.called_match_ids.clear()
                await self.bot.dh.clear_lobbies(self.tournament['_id'])

                if self.format and hasattr(self.format, 'on_reset'):
                    await self.format.on_reset()

                await self.start_checkin()
                await self.bot.dh.update_tournament_state(self.tournament['_id'], 'checkin')

            else:
                raise ValueError(f'Cannot revert from state: {state!r}')