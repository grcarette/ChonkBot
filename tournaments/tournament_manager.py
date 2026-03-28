from .challonge_handler import ChallongeHandler
from .match_service import MatchService
from formats import make_format
from datetime import datetime

from utils.channel_utils import CHANNEL_PERMISSIONS, NONDEFAULT_CHANNELS, STAFF_PERMISSIONS, CHANNEL_ORDER, create_channel
from utils.emojis import RESULT_EMOJIS, INDICATOR_EMOJIS
from utils.discord_preset_colors import get_random_color
from utils.get_bracket_link import get_bracket_link
from utils.validate_stagecode import validate_stagecode
from utils.event_logger import EventLogger

from ui.checkin import CheckinView
from ui.stage_bans import BanStagesButton
from ui.match_report import MatchReportButton
from ui.register_control import RegisterControlView
from ui.tournament_checkin import TournamentCheckinView
from ui.link_view import LinkView
from ui.registration_approval import RegistrationApprovalView
from ui.swiss_register import SwissActiveRegisterView

from .match_lobby import MatchLobby

import discord
import random
import os
import asyncio

RESULTS_CHANNEL_ID = 1346422769721544754
DEFAULT_CHANNEL_POSITION = 2

CHECKIN_REMINDER_SECONDS = 300
CHECKIN_POLL_INTERVAL    = 60
CHECKIN_AUTODQ_SECONDS   = 6000


class TournamentManager:
    def __init__(self, bot, tournament):
        self.bot = bot
        self.tournament = tournament
        self.guild = self.bot.guild
        self.lobbies = {}
        self.bot_control = None
        self.tournament_reset = False
        self.debug = self.tournament.get('debug', False)
        self.organizer_role = None
        self.format = None
        self.logger = EventLogger(tournament['name'])

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

    @property
    def is_ranked(self) -> bool:
        """True if this tournament should report results to UCH Ranked."""
        return bool(self.tournament.get('config', {}).get('ranked_reporting', False))

    @property
    def is_teams_mode(self) -> bool:
        """True if this tournament uses 2v2 teams."""
        return bool(self.tournament.get('config', {}).get('teams_mode', False))

    async def report_result_to_ranked_api(self, winner_id: int, loser_id: int) -> None:
        try:
            result = await self.bot.uchranked_api.report_match(
                player1_id=winner_id,
                player2_id=loser_id,
                score='1-0',
            )
            if not result.get('success'):
                self.logger.ranked_failed(winner_id, loser_id, result.get('error', 'unknown error'))
                await self._alert_ranked_api_failure(winner_id, loser_id, result.get('error'))
                return

            match_id = result.get('match_id')
            if not match_id:
                self.logger.ranked_failed(winner_id, loser_id, 'no match_id returned')
                await self._alert_ranked_api_failure(winner_id, loser_id, 'No match_id returned')
                return

            self.logger.ranked_reported(winner_id, loser_id, match_id)

            try:
                await self.bot.uchranked_api.accept_match(winner_id, match_id)
            except Exception as e:
                self.logger.warning('RANKED', f'Winner accept_match failed — {winner_id} — {e}')
            try:
                await self.bot.uchranked_api.accept_match(loser_id, match_id)
            except Exception:
                pass

        except Exception as e:
            self.logger.ranked_failed(winner_id, loser_id, str(e))
            await self._alert_ranked_api_failure(winner_id, loser_id, str(e))

    async def report_match(self, lobby, is_dq=False):
        lobby_data = await lobby.get_lobby()
        winner_user_id = str(lobby_data['results'][0])
        loser_user_id  = str(lobby_data['results'][1]) if len(lobby_data['results']) > 1 else None

        result = {
            'match_id':  lobby_data['match_id'],
            'winner_id': winner_user_id,
            'loser_id':  loser_user_id,
            'is_dq':     is_dq,
        }
        self.logger.match_result(result['match_id'], result['winner_id'], result['loser_id'], is_dq)
        await self.format.on_result(result, lobby)
        if hasattr(self.format, 'invalidate_pending_cache'):
            self.format.invalidate_pending_cache()

    async def _alert_ranked_api_failure(self, winner_id: int, loser_id: int, error: str = None) -> None:
        print(f"[Ranked] API failure: winner={winner_id} loser={loser_id} error={error}")
        try:
            channel = await self.get_channel('event-updates')
            if channel:
                embed = discord.Embed(
                    title="⚠️ UCH Ranked API Failure",
                    description=(
                        f"Match result for <@{winner_id}> over <@{loser_id}> "
                        f"**was not reported to UCH Ranked**.\n\n"
                        + (f"**Error:** `{error}`" if error else "")
                    ),
                    color=discord.Color.red(),
                )
                await channel.send(embed=embed)
        except Exception as e:
            print(f"[Ranked] Failed to send API failure alert: {e}")

    # ─── Initialization ───────────────────────────────────────────────────────

    async def initialize_event(self):
        tournament = await self.get_tournament()

        self.format = make_format(self)
        await self.format.on_initialize()

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
            if hasattr(self.format, 'called_match_ids'):
                self.format.called_match_ids.add(lobby['match_id'])
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
            self.logger.state_transition(state, next_state)

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
            is_swiss = self.tournament.get('format', '') in ('swiss', 'swiss filter')
            debug_player_count = 4 if is_swiss else 8
            if self.is_teams_mode:
                # Pair up debug players into teams
                for i in range(0, debug_player_count, 2):
                    try:
                        await self.register_player_team(i, i + 1)
                        await self.accept_team_invite(i + 1)
                    except Exception as e:
                        print(f"[open_registration] Failed to register debug team ({i}, {i+1}): {e}")
            else:
                for i in range(debug_player_count):
                    try:
                        await self.register_player(i)
                    except Exception as e:
                        print(f"[open_registration] Failed to register debug player {i}: {e}")
        state = tournament['state']

        if state in ('setup', 'registration'):
            register_channel = await self.get_channel('register')
            if register_channel:
                register_message = await self._get_register_message(register_channel)
                if register_message:
                    view = RegisterControlView(self)
                    view.register_button.disabled = False
                    await register_message.edit(view=view)
                else:
                    view  = RegisterControlView(self)
                    embed = discord.Embed(
                        title=f"Register for {self.tournament['name']}",
                        color=discord.Color.green()
                    )
                    await register_channel.send(embed=embed, view=view)
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

        elif state == 'checkin':
            self.checkin_view.register_button.disabled = False
            await self.checkin_message.edit(view=self.checkin_view)

        await self.bot.dh.open_registration(tournament['_id'])
        await self.sync_channel_order()

    async def close_registration(self):
        tournament = await self.get_tournament()
        state = tournament['state']

        if state in ('setup', 'registration'):
            register_channel = await self.get_channel('register')
            if register_channel:
                register_message = await self._get_register_message(register_channel)
                if register_message:
                    view = RegisterControlView(self)
                    view.register_button.disabled = True
                    await register_message.edit(view=view)
        elif state == 'checkin':
            self.checkin_view.register_button.disabled = True
            await self.checkin_message.edit(view=self.checkin_view)

        await self.bot.dh.close_registration(tournament['_id'])

    async def _get_register_message(self, register_channel):
        """Find the bot's register view message in the register channel."""
        bot_id = self.bot.user.id
        async for message in register_channel.history(limit=10):
            if message.author.id == bot_id and message.components:
                return message
        return None

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
            self.logger.debug('REGISTRATION', f'Player {user_id} tried to register but is already registered')
            return False

        tournament = await self.get_tournament()

        # Ranked gate — applies to any ranked_reporting tournament, debug always bypasses
        if self.is_ranked and not self.debug:
            ranked_player = await self.get_ranked_player(user_id)
            if not ranked_player:
                self.logger.warning('REGISTRATION', f'Player {user_id} blocked — no UCH Ranked account')
                return 'no_ranked_account'

        if tournament.get('config', {}).get('approved_registration'):
            await self.bot.dh.add_registration_request(tournament['_id'], user_id)
            self.logger.info('REGISTRATION', f'Player {user_id} registration pending TO approval')
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
        if tournament.get('config', {}).get('display_entrants'):
            await self.edit_event_info()

        self.logger.player_registered(user_id, user['name'] if user else str(user_id))
        return True

    async def unregister_player(self, user_id):
        tournament = await self.get_tournament()

        if self.is_teams_mode:
            team_id = self._find_team_id_for_player(tournament, user_id)
            if not team_id:
                return
            p1_id, p2_id = self._parse_team_id(team_id)
            guild = self.guild
            tournament_role = discord.utils.get(guild.roles, name=self.tournament['name'])
            for pid in (p1_id, p2_id):
                member = discord.utils.get(guild.members, id=pid)
                if member and tournament_role:
                    await member.remove_roles(tournament_role)
            await self.format.on_team_unregister(team_id)
            await self.bot.dh.unregister_team(tournament['_id'], team_id)
            if tournament.get('config', {}).get('display_entrants'):
                await self.edit_event_info()
            return

        # ── Solo path ────────────────────────────────────────────────────────────
        entrants = tournament.get('entrants', {})
        if isinstance(entrants, dict):
            if str(user_id) not in entrants:
                pass
        else:
            entrants = {str(e['discord_id']): None for e in entrants}

        if str(user_id) not in entrants:
            self.logger.warning('REGISTRATION', f'Unregister attempted for {user_id} but not in entrants')
            return

        guild = self.guild
        discord_user = discord.utils.get(guild.members, id=user_id)
        tournament_role = discord.utils.get(guild.roles, name=self.tournament['name'])
        if discord_user and tournament_role:
            await discord_user.remove_roles(tournament_role)

        await self.format.on_player_unregister(user_id)
        await self.bot.dh.unregister_player(tournament['_id'], user_id)
        self.logger.player_dropped(user_id, str(user_id))
        if tournament.get('config', {}).get('display_entrants'):
            await self.edit_event_info()

    async def register_player_direct(self, user_id):
        """Register a player directly, bypassing the approval check. Used by web approval flow."""
        already_registered = await self.bot.dh.get_registration_status(
            self.tournament['_id'], user_id
        )
        if already_registered:
            return False

        discord_user    = discord.utils.get(self.guild.members, id=user_id)
        tournament_role = discord.utils.get(self.guild.roles, name=self.tournament['name'])

        if not self.debug:
            if discord_user and tournament_role:
                await discord_user.add_roles(tournament_role)
            await self.bot.dh.register_user(discord_user)
        else:
            await self.bot.dh.register_user(user_id, debug=True)

        user = await self.bot.dh.get_user(user_id=user_id)
        await self.format.on_player_register(user_id, user)
        if (await self.get_tournament()).get('config', {}).get('display_entrants'):
            await self.edit_event_info()
        return True

    # ─── Teams registration ───────────────────────────────────────────────────

    @staticmethod
    def _make_team_id(player1_id: int, player2_id: int) -> str:
        """Deterministic team ID from two player IDs, always lower ID first."""
        a, b = sorted((player1_id, player2_id))
        return f"{a}_{b}"

    @staticmethod
    def _parse_team_id(team_id: str) -> tuple[int, int]:
        """Parse a team_id string back into (player1_id, player2_id)."""
        a, b = team_id.split('_')
        return int(a), int(b)

    def _find_team_id_for_player(self, tournament: dict, player_id: int) -> str | None:
        """
        Scan entrants to find the team_id that contains player_id.
        Returns the team_id string, or None if not found.
        """
        for key in tournament.get('entrants', {}):
            try:
                p1, p2 = self._parse_team_id(key)
                if player_id in (p1, p2):
                    return key
            except (ValueError, AttributeError):
                continue
        return None

    async def register_player_team(self, player1_id: int, player2_id: int):
        """
        Initiate a 2v2 team registration. Creates a pending invite from
        player1 to player2. Player2 must call accept_team_invite to complete.

        Returns one of:
          'self_invite'                — player1 == player2
          'already_registered'         — player1 is already on a confirmed team
          'partner_already_registered' — player2 is already on a confirmed team
          'already_pending'            — player1 already has an outstanding invite
          'pending'                    — invite created successfully
        """
        if player1_id == player2_id:
            return 'self_invite'

        tournament = await self.get_tournament()
        tid = tournament['_id']

        # Check confirmed registrations
        if self._find_team_id_for_player(tournament, player1_id):
            return 'already_registered'
        if self._find_team_id_for_player(tournament, player2_id):
            return 'partner_already_registered'

        # Check pending invites
        pending = await self.bot.dh.get_pending_teams(tid)
        for pt in pending:
            if pt['player1_id'] == player1_id or pt['player2_id'] == player1_id:
                return 'already_pending'

        await self.bot.dh.add_pending_team(tid, player1_id, player2_id)
        return 'pending'

    async def accept_team_invite(self, player2_id: int):
        """
        Accept a pending team invite addressed to player2_id.

        Returns one of:
          'no_invite'          — no pending invite found for this player
          'already_registered' — player2 is already on a confirmed team
          'registered'         — team confirmed and registered with the format
        """
        tournament = await self.get_tournament()
        tid = tournament['_id']

        # Guard: already on a team
        if self._find_team_id_for_player(tournament, player2_id):
            return 'already_registered'

        # Find the pending invite where this player is player2
        pending = await self.bot.dh.get_pending_teams(tid)
        invite = next((pt for pt in pending if pt['player2_id'] == player2_id), None)
        if not invite:
            return 'no_invite'

        player1_id = invite['player1_id']
        team_id = self._make_team_id(player1_id, player2_id)

        # Resolve display names for team name
        u1 = await self.bot.dh.get_user(user_id=player1_id)
        u2 = await self.bot.dh.get_user(user_id=player2_id)
        name1 = u1['name'] if u1 else str(player1_id)
        name2 = u2['name'] if u2 else str(player2_id)
        team_name = f"{name1} / {name2}"

        team_doc = {
            'team_id': team_id,
            'player1_id': player1_id,
            'player2_id': player2_id,
            'name': team_name,
        }

        # Remove the pending invite before registering
        await self.bot.dh.remove_pending_team(tid, player1_id, player2_id)

        # Grant Discord role to both members
        guild = self.guild
        tournament_role = discord.utils.get(guild.roles, name=self.tournament['name'])
        if not self.debug:
            for pid in (player1_id, player2_id):
                member = discord.utils.get(guild.members, id=pid)
                if member and tournament_role:
                    await member.add_roles(tournament_role)
                await self.bot.dh.register_user(member if member else pid)

        # Delegate bracket registration to the format
        await self.format.on_team_register(team_id, team_doc)

        if tournament.get('config', {}).get('display_entrants'):
            await self.edit_event_info()

        return 'registered'

    async def resolve_team_members(self, team_ids: list) -> list[int]:
        """
        Given a list of team_id strings, return all constituent discord user IDs.
        Used by the lobby builder for channel overwrites and @mentions.
        Raises ValueError if a team_id is malformed or not found in entrants.
        """
        members = []
        tournament = await self.get_tournament()
        entrants = tournament.get('entrants', {})
        for team_id in team_ids:
            if str(team_id) not in entrants:
                raise ValueError(f"Team ID '{team_id}' not found in tournament entrants")
            p1, p2 = self._parse_team_id(str(team_id))
            members.extend([p1, p2])
        return members

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
        # Resolve entrant keys to individual discord IDs for ping purposes
        individual_ids = []
        for key in tournament['entrants'].keys():
            key_str = str(key)
            if '_' in key_str:
                try:
                    p1, p2 = key_str.split('_')
                    individual_ids.extend([str(p1), str(p2)])
                except ValueError:
                    pass
            else:
                individual_ids.append(key_str)

        missing_count = len(individual_ids) - len(checked_in_list)

        if missing_count > MAXIMUM_PING_CHECKINS:
            return False

        failed_pings = []
        for player in individual_ids:
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

        if tournament.get('config', {}).get('approved_registration'):
            pending_ids = await self.bot.dh.get_registration_requests(tournament['_id'])
            for discord_id in pending_ids:
                member = self.guild.get_member(discord_id)
                if member:
                    try:
                        embed = discord.Embed(
                            title='Registration Closed',
                            description=f"Registration for **{tournament['name']}** has closed and your request was not approved in time.",
                            color=discord.Color.red()
                        )
                        await member.send(embed=embed)
                    except discord.Forbidden:
                        pass
            await self.bot.dh.clear_registration_requests(tournament['_id'])

        if self.debug:
            removed_players = []
        elif self.is_teams_mode:
            # Remove any team where at least one member didn't check in
            checked_in_set = set(str(x) for x in tournament['checked_in'])
            removed_players = []
            for team_id in tournament['entrants'].keys():
                team_id_str = str(team_id)
                if '_' in team_id_str:
                    try:
                        p1, p2 = team_id_str.split('_')
                        if p1 not in checked_in_set or p2 not in checked_in_set:
                            removed_players.append(team_id_str)
                    except ValueError:
                        pass
                else:
                    if team_id_str not in checked_in_set:
                        removed_players.append(team_id_str)
            for team_id in removed_players:
                await self.unregister_player(int(team_id.split('_')[0]))
        else:
            checked_in_set = set(str(x) for x in tournament['checked_in'])
            removed_players = [
                player for player in tournament['entrants'].keys()
                if str(player) not in checked_in_set
            ]
            for player_id in removed_players:
                self.logger.info('CHECKIN', f'Player {player_id} removed — did not check in')
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
        if hasattr(self.format, 'invalidate_pending_cache'):
            self.format.invalidate_pending_cache()
        await self.send_instruction_message()
        await self.format.on_tournament_start()
        self.logger.info('STATE', f'Tournament started — {len(tournament["entrants"])} players')
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
    # All match calling logic lives in formats/challonge.py (for DE/SE) or
    # tournaments/swiss_manager.py (for Swiss). TournamentManager only holds
    # the lobby dict and delegates everything else to self.format.

    async def start_held_match(self, match_data):
        await self.lobbies[match_data['match_id']].start_match()

    # ─── Result reporting ─────────────────────────────────────────────────────

    async def report_match(self, lobby, is_dq=False):
        lobby_data = await lobby.get_lobby()
        winner_user_id = str(lobby_data['results'][0])
        loser_user_id  = str(lobby_data['results'][1]) if len(lobby_data['results']) > 1 else None

        result = {
            'match_id':  lobby_data['match_id'],
            'winner_id': winner_user_id,
            'loser_id':  loser_user_id,
            'is_dq':     is_dq,
        }
        self.logger.match_result(result['match_id'], result['winner_id'], result['loser_id'], is_dq)
        await self.format.on_result(result, lobby)
        if hasattr(self.format, 'invalidate_pending_cache'):
            self.format.invalidate_pending_cache()

    async def report_match_from_result(self, result):
        lobby = self.lobbies.get(result['match_id'])
        if lobby:
            await self.format.on_result(result, lobby)

            if hasattr(self.format, 'hold_when_ready') and self.format.hold_when_ready:
                pending = await self.format.get_pending_matches()
                for match_data in pending:
                    if match_data['match_id'] in self.format.hold_when_ready:
                        await self.format.call_match(match_data, hold_match=True)

            if getattr(self.format, 'autocall_matches', False) and self.format.needs_match_call_refresh:
                await self.format.call_matches()

    async def close_prereqs(self, lobby):
        lobby_data = await lobby.get_lobby()
        for match_id in lobby_data['prereq_matches']:
            prereq_data = await self.bot.dh.get_lobby(match_id)
            if prereq_data['state'] != 'closed':
                await self.lobbies[match_id].close_lobby()

    # ─── Reset ───────────────────────────────────────────────────────────────

    async def reset_lobby_to_active(self, match_id: int):
        """
        Reset a complete match back to active so it can be replayed.
        - Resets the match on Challonge via the format
        - Deletes any dependent lobbies spawned from this match's result
        - Removes this match from the format's called_match_ids
        - Deletes the finished lobby from the DB
        Raises ValueError if any dependent match has a finished lobby.
        """
        dependent_lobbies = await self.bot.dh.get_dependent_matches(match_id)
        print(f"[reset_lobby] match_id={match_id}, dependents={[d['match_id'] for d in dependent_lobbies]}, states={[d['state'] for d in dependent_lobbies]}")
        for dep in dependent_lobbies:
            if dep.get('state') in ('finished', 'closed'):
                raise ValueError(
                    f"Cannot reset match {match_id} — a match that depends on its result has already finished."
                )

        # Delegate Challonge reset to the format
        await self.format.on_reset_report({'match_id': match_id})

        # Close and delete any dependent lobbies that are still active
        for dep in dependent_lobbies:
            dep_id = dep['match_id']
            if dep_id in self.lobbies:
                await self.lobbies[dep_id].delete_lobby()
                del self.lobbies[dep_id]
            else:
                await self.bot.dh.delete_lobby(dep_id)
            if hasattr(self.format, 'called_match_ids'):
                self.format.called_match_ids.discard(dep_id)

        # Delete the original lobby from DB and memory
        existing = self.lobbies.get(match_id)
        if existing:
            await existing.delete_lobby()
            del self.lobbies[match_id]
        else:
            await self.bot.dh.delete_lobby(match_id)

        if hasattr(self.format, 'called_match_ids'):
            self.format.called_match_ids.discard(match_id)
        if hasattr(self.format, 'invalidate_pending_cache'):
            self.format.invalidate_pending_cache()

    async def reset_report(self, kwargs):
        lobby = kwargs.get('lobby')
        await self.lobbies[lobby['match_id']].reset_report()
        await self.format.on_reset_report(lobby)

    async def reset_tournament(self, kwargs):
        self.logger.info('STATE', 'Tournament reset initiated')
        self.tournament_reset = True
        for lobby in self.lobbies:
            await self.lobbies[lobby].delete_lobby()
        await self.format.on_reset()
        await self.bot.dh.update_tournament_state(self.tournament['_id'], 'registration')
        await self.bot.dh.clear_lobbies(self.tournament['_id'])
        if hasattr(self.format, 'called_match_ids'):
            self.format.called_match_ids.clear()
        await self.progress_tournament()
        self.tournament_reset = False
        self.logger.info('STATE', 'Tournament reset complete — back to registration')
        if hasattr(self.format, 'invalidate_pending_cache'):
            self.format.invalidate_pending_cache()

    # ─── End tournament ───────────────────────────────────────────────────────

    async def end_tournament(self):
        self.stop_checkin_reminder_loop()
        for lobby in self.lobbies:
            await self.lobbies[lobby].close_lobby()
        await self.format.on_tournament_end()
        self.logger.info('STATE', 'Tournament ended — all lobbies closed')

    async def finalize_tournament(self):
        """Close all lobbies, post results if not already posted, remove Discord channels."""
        await self.end_tournament()
        tournament = await self.get_tournament()
        if not tournament.get('config', {}).get('results_posted'):
            await self.post_final_results()
        await self.remove_tournament_from_discord()
        if self.debug:
            await self._cleanup_lobbies()
            await self.format.on_tournament_delete()
            await self.bot.dh.delete_tournament(tournament['_id'])
            self.bot.th.tournaments.pop(tournament['_id'], None)

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
            # Challonge-backed result — delegate to format for the ch reference
            ch = self.format.ch if hasattr(self.format, 'ch') else None
            if not ch:
                print("[post_final_results] No Challonge handler available")
                return
            challonge_id = self.tournament['challonge_data']['id']
            final_results = await ch.get_final_results(challonge_id)
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

        await self.bot.dh.edit_tournament_config(
            self.tournament['_id'], results_posted=True
        )

    # ─── Delete tournament ────────────────────────────────────────────────────

    async def delete_tournament(self, kwargs=None):
        tournament = await self.get_tournament()
        if tournament.get('category_id'):
            await self.remove_tournament_from_discord()
        await self._cleanup_lobbies()
        await self.format.on_tournament_delete()
        await self.bot.dh.delete_tournament(tournament['_id'])
        self.bot.th.tournaments.pop(tournament['_id'], None)

    async def _cleanup_lobbies(self):
        """Delete all in-memory lobbies and clear all lobby DB records for this tournament."""
        for lobby in self.lobbies.values():
            await lobby.delete_lobby()
        self.lobbies.clear()
        await self.bot.dh.clear_lobbies(self.tournament['_id'])

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

        tournament_role    = discord.utils.get(guild.roles, name=f"{tournament['name']}")
        tournament_to_role = discord.utils.get(guild.roles, name=f"{tournament['name']} TO")
        if tournament_role:
            await tournament_role.delete()
        if tournament_to_role:
            await tournament_to_role.delete()

    async def disqualify_player(self, user_id):
        player_registered = await self.bot.dh.get_registration_status(self.tournament['_id'], user_id)
        if not player_registered:
            self.logger.warning('DQ', f'DQ attempted for {user_id} but player is not registered')
            return False

        lobby_data = await self.bot.dh.find_player_match(self.tournament['_id'], user_id)
        if lobby_data:
            lobby = self.lobbies[lobby_data['match_id']]
            winner_id = (set(lobby_data['players']) - {str(user_id)}).pop()

            if lobby.channel:
                await lobby.purge_bot_messages()
                dq_mention     = f"<@{user_id}>"
                winner_mention = f"<@{winner_id}>"
                embed = discord.Embed(
                    title="Player Disqualified",
                    description=(
                        f"{dq_mention} has been disqualified.\n"
                        f"{winner_mention} wins this match by default.\n\n"
                        f"This channel will close shortly."
                    ),
                    color=discord.Color.red()
                )
                await lobby.channel.send(embed=embed)

            await lobby.end_reporting(winner_id, is_dq=True)
            self.logger.player_dq(user_id, had_active_match=True, opponent_id=winner_id)
        else:
            self.logger.player_dq(user_id, had_active_match=False)

        return await self.bot.dh.disqualify_player(self.tournament['_id'], user_id)

    async def undisqualify_player(self, user_id):
        tournament = await self.get_tournament()

        if str(user_id) not in tournament.get('dqs', []):
            return False

        result = await self.bot.dh.undisqualify_player(self.tournament['_id'], user_id)

        # Mark as dropped in swiss so they must explicitly rejoin
        if tournament.get('format') == 'swiss' and self.format:
            swiss_event = await self.bot.dh.get_swiss_event_by_tournament(self.tournament['_id'])
            if swiss_event and str(user_id) in swiss_event.get('players', {}):
                await self.bot.dh.swiss_collection.update_one(
                    {'_id': swiss_event['_id']},
                    {'$set': {f'players.{user_id}.dropped': True}}
                )
                self.logger.info('DQ', f'Player {user_id} un-DQ\'d — must rejoin to play')

        return result

    async def reopen_lobby(self, match_id_str: str):
        match_lobby = next(
            (lobby for key, lobby in self.lobbies.items() if str(key) == match_id_str),
            None
        )
        if not match_lobby:
            raise ValueError('Lobby not found in memory — bot may have restarted')

        lobby_db = await match_lobby.get_lobby()
        tournament = await self.get_tournament()

        dq_players = [p for p in lobby_db.get('players', []) if str(p) in tournament.get('dqs', [])]
        # Un-DQ any DQ'd players in this lobby
        for player_id in lobby_db.get('players', []):
            if str(player_id) in tournament.get('dqs', []):
                await self.undisqualify_player(player_id)

        # Format-specific result unrecording
        await self.format.on_lobby_reopen(match_lobby, lobby_db)

        # Reset lobby DB state
        await self.bot.dh.lobby_collection.update_one(
            {'match_id': match_lobby.match_id},
            {'$set': {
                'state':        'checkin',
                'results':      [],
                'checked_in':   [],
                'picked_stage': None,
            }}
        )

        match_lobby.remaining_players = set(lobby_db.get('players', []))

        # Notify channel if present
        if match_lobby.channel:
            await match_lobby.purge_bot_messages()
            if dq_players:
                mentions = ' '.join(f"<@{p}>" for p in lobby_db.get('players', []))
                embed = discord.Embed(
                    title="Disqualification Reverted",
                    description=(
                        f"The disqualification has been reverted.\n"
                        f"please play out your match."
                    ),
                    color=discord.Color.green()
                )
                await match_lobby.channel.send(embed=embed)

        await match_lobby.start_checkin()

    # ─── Seeding ─────────────────────────────────────────────────────────────

    async def generate_seeding_link(self) -> str:
        from web.seeding_server import generate_token
        tournament = await self.get_tournament()
        challonge_url = tournament['challonge_data']['url']
        token = generate_token(str(tournament['_id']), challonge_url)
        base_url = os.getenv('WEB_BASE_URL', 'http://localhost:8080').strip()
        return f"{base_url}/seeding?token={token}"

    # ─── Auto-DQ (checkin reminder loop) ─────────────────────────────────────

    async def _get_higher_seed(self, player_ids):
        """
        Return the player_id with the lower seed number (higher seeding).
        Fetches participant data from Challonge via the format's ch handler.
        """
        tournament = await self.get_tournament()
        entrants = tournament['entrants']

        challonge_to_discord = {
            int(challonge_id): int(discord_id)
            for discord_id, challonge_id in entrants.items()
            if challonge_id is not None
        }

        ch = self.format.ch if hasattr(self.format, 'ch') else None
        if not ch:
            raise ValueError("No Challonge handler available for seed lookup")

        participants = await ch.get_participants(tournament['challonge_data']['url'])

        seed_map = {}
        for p in participants:
            discord_id = challonge_to_discord.get(p['id'])
            if discord_id in player_ids:
                seed_map[discord_id] = p.get('seed') or 9999

        if not seed_map:
            raise ValueError("No seed data found for lobby players")

        return min(seed_map, key=lambda pid: seed_map[pid])

    # ─── Swiss utilities ──────────────────────────────────────────────────────

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

    # ─── Event info embed ─────────────────────────────────────────────────────

    async def _build_event_info_embed(self):
        """Build and return (embed, view, banner_file) for the event-info message."""
        tournament = await self.get_tournament()

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

        # ── Entrants ──────────────────────────────────────────────────────────
        entrant_list = []
        if tournament.get('config', {}).get('display_entrants'):
            entrants = tournament.get('entrants', {})
            if entrants:
                # Resolve individual discord IDs — in teams mode keys are "p1_p2" strings
                individual_ids = []
                for key in entrants.keys():
                    key_str = str(key)
                    if '_' in key_str:
                        try:
                            p1, p2 = key_str.split('_')
                            individual_ids.extend([int(p1), int(p2)])
                        except ValueError:
                            pass
                    else:
                        try:
                            individual_ids.append(int(key_str))
                        except ValueError:
                            pass

                user_map = await self.bot.dh.get_users_bulk(individual_ids)

                for key_str in entrants.keys():
                    key_str = str(key_str)
                    if '_' in key_str:
                        try:
                            p1, p2 = key_str.split('_')
                            u1 = user_map.get(int(p1))
                            u2 = user_map.get(int(p2))
                            n1 = u1['name'] if u1 else str(p1)
                            n2 = u2['name'] if u2 else str(p2)
                            name = f"{n1} / {n2}"
                        except ValueError:
                            name = key_str
                        entrant_list.append({'discord_id': key_str, 'name': name, 'seed': None})
                    else:
                        try:
                            discord_id_int = int(key_str)
                        except ValueError:
                            continue
                        user = user_map.get(discord_id_int)
                        name = user['name'] if user else f'Unknown ({key_str})'
                        seed = None
                        if not (self.format and self.format.shows_bracket_link and 'challonge_data' in tournament):
                            seeds = tournament.get('seeds', {})
                            seed  = seeds.get(key_str) or seeds.get(discord_id_int)
                        entrant_list.append({'discord_id': key_str, 'name': name, 'seed': seed})

                if self.format and self.format.shows_bracket_link and 'challonge_data' in tournament:
                    ch = self.format.ch if hasattr(self.format, 'ch') else None
                    if ch:
                        try:
                            participants = await ch.get_participants(tournament['challonge_data']['url'])
                            challonge_to_discord = {
                                int(cid): str(did)
                                for did, cid in entrants.items()
                                if cid is not None
                            }
                            seed_map = {
                                challonge_to_discord[p['id']]: p.get('seed')
                                for p in participants
                                if p['id'] in challonge_to_discord
                            }
                            for e in entrant_list:
                                e['seed'] = seed_map.get(e['discord_id'])
                        except Exception as ex:
                            print(f"[post_event_info] Failed to fetch Challonge seeds: {ex}")

                entrant_list.sort(key=lambda e: e['seed'] if e['seed'] is not None else 9999)

        # ── Banner ────────────────────────────────────────────────────────────
        banner_file      = None
        banner_image_url = None
        banner_path      = tournament.get('banner_url')
        if banner_path:
            abs_path = os.path.normpath(
                os.path.join(os.path.dirname(__file__), '..', 'web', banner_path.lstrip('/'))
            )
            if os.path.exists(abs_path):
                banner_file      = discord.File(abs_path, filename='banner.jpg')
                banner_image_url = 'attachment://banner.jpg'
            else:
                print(f"[post_event_info] Banner file not found at {abs_path}")

        # ── Bracket link view ─────────────────────────────────────────────────
        UCH_RULESET_URL = 'https://docs.google.com/document/d/1Z9FcjZPDYJVVLo90GeTZSMHd4HNE8Ms8/edit?usp=sharing&ouid=116452753972353491775&rtpof=true&sd=true'

        if self.format and self.format.shows_bracket_link and 'challonge_data' in tournament:
            from utils.get_bracket_link import get_bracket_link
            from utils.emojis import INDICATOR_EMOJIS
            bracket_link = await get_bracket_link(tournament['challonge_data']['url'])
            view = discord.ui.View()
            view.add_item(discord.ui.Button(
                label=f"{INDICATOR_EMOJIS['link']} Bracket",
                url=bracket_link,
                style=discord.ButtonStyle.link
            ))
            view.add_item(discord.ui.Button(
                label=f"{INDICATOR_EMOJIS['link']} Ruleset",
                url=UCH_RULESET_URL,
                style=discord.ButtonStyle.link
            ))
        else:
            from utils.emojis import INDICATOR_EMOJIS
            view = discord.ui.View()
            view.add_item(discord.ui.Button(
                label=f"{INDICATOR_EMOJIS['link']} Ruleset",
                url=UCH_RULESET_URL,
                style=discord.ButtonStyle.link
            ))

        # ── Build embed ───────────────────────────────────────────────────────
        embed = discord.Embed(color=color)
        embed.title = tournament['name']
        if banner_image_url:
            embed.set_image(url=banner_image_url)

        embed.add_field(name='Date', value=tournament.get('date', 'TBA'), inline=True)
        fmt_display = tournament.get('format', '').replace('_', ' ').title()
        if tournament.get('format') == 'swiss':
            fmt_display += f" ({tournament.get('round_limit', 8)} rounds)"
        embed.add_field(name='Format', value=fmt_display, inline=True)
        embed.add_field(
            name="TO's",
            value='\n'.join(organizer_list) if organizer_list else 'N/A',
            inline=True
        )

        if entrant_list:
            names = '\n'.join(f"{i+1}. {e['name']}" for i, e in enumerate(entrant_list))
            embed.add_field(
                name=f"Entrants ({len(entrant_list)})",
                value=names,
                inline=False
            )

        return embed, view, banner_file

    async def post_event_info(self):
        """Send a fresh event-info message. Call on tournament creation or banner change."""
        channel = await self.get_channel('event-info')
        if not channel:
            return
        embed, view, banner_file = await self._build_event_info_embed()
        if banner_file:
            await channel.send(file=banner_file, embed=embed, view=view)
        else:
            await channel.send(embed=embed, view=view)

    async def edit_event_info(self):
        """Edit the existing event-info message in place. Call on registration/seed changes."""
        channel = await self.get_channel('event-info')
        if not channel:
            return
        embed, view, banner_file = await self._build_event_info_embed()

        bot_id = self.bot.user.id
        existing = None
        async for msg in channel.history(limit=20, oldest_first=True):
            if msg.author.id == bot_id and (msg.embeds or msg.attachments):
                existing = msg
                break

        if not existing:
            await self.post_event_info()
            return

        if banner_file:
            for att in existing.attachments:
                if att.filename == 'banner.jpg':
                    embed.set_image(url=att.url)
                    break

        await existing.edit(embed=embed, view=view)

    # ─── Stagelist ────────────────────────────────────────────────────────────

    async def publish_stagelist(self):
        from utils.embed_utils import create_stage_embed
        tournament = await self.get_tournament()
        if not tournament.get('stagelist'):
            return

        view_channel = True
        if self.debug:
            view_channel = False

        stagelist_channel = await self.get_channel('stagelist')
        if not stagelist_channel:
            guild               = self.bot.guilds[0]
            tournament_category = self.get_tournament_category()
            stagelist_channel   = await guild.create_text_channel(
                'stagelist',
                category=tournament_category,
                overwrites={
                    guild.default_role: discord.PermissionOverwrite(
                        view_channel=view_channel,
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

    # ─── Utilities ───────────────────────────────────────────────────────────

    async def sync_channel_order(self):
        """Reorder channels in the tournament category to match CHANNEL_ORDER.
        
        Only edits channels that are out of place, using the minimum number of
        edits. Channels already forming the longest correct subsequence are left
        untouched.
        """
        tournament_category = self.get_tournament_category()
        if not tournament_category:
            return

        channels = {ch.name: ch for ch in tournament_category.channels}
        desired = [channels[name] for name in CHANNEL_ORDER if name in channels]
        if not desired:
            return

        # Find which channels are already in the correct relative order (LIS).
        # Map each channel to its target index in desired.
        target_index = {ch: i for i, ch in enumerate(desired)}
        current = [ch for ch in tournament_category.channels if ch in target_index]

        # Extract the indices of current channels in desired order and find LIS.
        indices = [target_index[ch] for ch in current]

        def longest_increasing_subsequence(seq):
            """Returns the set of values in the LIS (not indices, values)."""
            if not seq:
                return set()
            tails = []
            for val in seq:
                lo, hi = 0, len(tails)
                while lo < hi:
                    mid = (lo + hi) // 2
                    if tails[mid] < val:
                        lo = mid + 1
                    else:
                        hi = mid
                if lo == len(tails):
                    tails.append(val)
                else:
                    tails[lo] = val
            return set(tails)

        lis_indices = longest_increasing_subsequence(indices)
        needs_edit = [ch for ch in desired if target_index[ch] not in lis_indices]

        for ch in needs_edit:
            await ch.edit(position=target_index[ch])

    async def revert_tournament(self):
        tournament = await self.get_tournament()
        state = tournament['state']

        if state == 'checkin':
            checkin_channel = await self.get_channel('check-in')
            if checkin_channel:
                await checkin_channel.delete()
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
            if hasattr(self.format, 'invalidate_pending_cache'):
                self.format.invalidate_pending_cache()
            await self.bot.dh.revert_tournament(self.tournament['_id'], 'registration')

        elif state == 'active':
            self.stop_checkin_reminder_loop()
            await self._cleanup_lobbies()
            self.lobbies.clear()
            if hasattr(self.format, 'called_match_ids'):
                self.format.called_match_ids.clear()
            if hasattr(self.format, 'invalidate_pending_cache'):
                self.format.invalidate_pending_cache()
            if self.format and hasattr(self.format, 'on_reset'):
                await self.format.on_reset()
            await self.bot.dh.revert_tournament(self.tournament['_id'], 'checkin')
            await self.start_checkin()

        else:
            raise ValueError(f'Cannot revert from state: {state!r}')

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
        await self.bot.dh.edit_tournament_config(self.tournament['_id'], **kwargs)

    def start_checkin_reminder_loop(self):
        self._checkin_reminded = set()
        self._checkin_autodqd  = set()
        self._checkin_reminder_task = asyncio.create_task(
            self._checkin_reminder_loop()
        )

    async def _checkin_reminder_loop(self):
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
            match_id    = lobby['match_id']
            checked_in  = set(lobby.get('checked_in', []))
            missing     = [p for p in lobby['players'] if p not in checked_in]

            if not missing:
                continue

            elapsed = (datetime.now() - lobby['state_timestamp']).total_seconds()
            if elapsed >= CHECKIN_AUTODQ_SECONDS:
                if match_id not in self._checkin_autodqd:
                    self._checkin_autodqd.add(match_id)
                    await self._auto_dq_lobby(lobby, missing)
                continue

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
        self._checkin_autodqd  = set()

    async def _auto_dq_lobby(self, lobby, missing_players):
        match_id    = lobby['match_id']
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