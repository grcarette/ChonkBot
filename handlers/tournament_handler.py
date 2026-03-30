import discord
from discord.ext import commands

from utils.emojis import NUMBER_EMOJIS, INDICATOR_EMOJIS
from utils.errors import PlayerNotFoundError
from utils.channel_utils import DEFAULT_STAGE_NUMBER, CHANNEL_PERMISSIONS, NONDEFAULT_CHANNELS, create_channel
from utils.embed_utils import create_stage_embed

from ui.bot_control import BotControlView
from ui.register_control import RegisterControlView
from ui.tournament_checkin import TournamentCheckinView
from ui.confirmation import ConfirmationView
from ui.checkin import CheckinView
from ui.stage_bans import BanStagesButton
from ui.match_report import MatchReportButton

from formats import make_format

from tournaments.match_lobby import MatchLobby
from tournaments.tournament_manager import TournamentManager
from tournaments.event_manager import EventManager

from tournaments.challonge_handler import ChallongeHandler

RESULTS_CHANNEL_ID = 1346422769721544754

class TournamentHandler():
    def __init__(self, bot):
        self.bot = bot
        self.ch = ChallongeHandler()
        self.tournaments = {}
        self.events: dict = {}   # ObjectId → EventManager

    async def initialize_active_events(self):
        from data.migration_swiss_filter_schema import migrate_swiss_filter_schema
        from data.migration_challonge_to_phase import migrate_challonge_to_phase
        await migrate_swiss_filter_schema(self.bot.dh.tournament_collection)
        await migrate_challonge_to_phase(self.bot.dh.tournament_collection)

        active_events = await self.bot.dh.get_active_events()
        for event in active_events:
            em = EventManager(self.bot, event)
            await em.initialize()
            self.events[event['_id']] = em

            # Backward compat: register the active phase's TM so existing
            # code that uses bot.th.tournaments[tid] still works.
            # If the active phase is already finished (e.g. swiss phase done,
            # waiting for TO to start brackets), fall through to the event-level TM.
            if em.active_tm:
                phases = event.get('phases', [])
                active_phase_state = phases[em.active_phase_index].get('state') if phases else None
                if active_phase_state != 'finished':
                    self.tournaments[event['_id']] = em.active_tm
                    continue

            # Fallback for events with no active phase TM (setup state)
            if not event.get('category_id'):
                tm = TournamentManager(self.bot, event)
                tm.format = make_format(tm)
                tm.tc = None
                self.tournaments[event['_id']] = tm
                continue
            await self.initialize_event(event)
            
    async def initialize_event(self, event):
        tournament_manager = TournamentManager(self.bot, event)
        self.tournaments[event['_id']] = tournament_manager
        if not event.get('category_id'):
            tournament_manager.format = make_format(tournament_manager)
            tournament_manager.tc = None
            return tournament_manager
        await tournament_manager.initialize_event()
        return tournament_manager

    async def create_tournament_record(self, tournament):
        tournament = await self.bot.dh.create_tournament(tournament)
        if not tournament:
            return False
        await self.add_stages_tournament(tournament)

        em = EventManager(self.bot, tournament)
        await em.initialize()
        self.events[tournament['_id']] = em

        if em.active_tm:
            self.tournaments[tournament['_id']] = em.active_tm
        else:
            tm = TournamentManager(self.bot, tournament)
            tm.format = make_format(tm)
            await tm.format.on_initialize()
            tm.tc = None
            self.tournaments[tournament['_id']] = tm

        return tournament
        
    async def get_tournament_channel(self, tournament_manager, name):
        tournament_category = tournament_manager.get_tournament_category()
        channel = discord.utils.get(tournament_category.channels, name=name)
        return channel
        
    async def get_lobby_string(self, lobby):
        players = []
        for user_id in lobby['players']:
            user = await self.bot.dh.get_user(user_id=user_id)
            players.append(user['name'])
        player_string = ' vs '.join(players)
        timestamp = await self.get_short_timestamp(lobby['state_timestamp'])
        lobby_string = f'{player_string} - {timestamp}\n'
        return lobby_string
        
    async def confirm_reset_lobby(self, user_id, channel_id):
        guild = self.bot.guilds[0]
        channel = discord.utils.get(guild.channels, id=channel_id)
        lobby = await self.bot.dh.get_lobby_by_channel(channel_id)
        tm = self.tournaments[lobby['tournament']]
        embed = discord.Embed(
            title=f"**CAUTION:**\nAre you absolutely sure you want to reset this lobby?",
            description="This will return the lobby to the **reporting phase**. Both players will need to re-submit the match result.",
        )
        
        view = ConfirmationView(tm.reset_report, user_id, lobby=lobby)
        await channel.send(embed=embed, view=view)
 
    async def add_stages_tournament(self, tournament):       
        if tournament['config']['randomized_stagelist'] == True:
            stages = await self.bot.dh.get_random_stages(DEFAULT_STAGE_NUMBER)
            stage_codes = [stage['code'] for stage in stages]
            await self.bot.dh.add_stages_to_tournament(tournament['_id'], stage_codes)

    async def remove_tournament(self, kwargs):
        category_id = kwargs.get('category_id')
        guild = self.bot.guilds
        tournament = await self.bot.dh.get_tournament(category_id=category_id)
        await self.tournaments[tournament['_id']].delete_tournament()

    async def register_role(self, category_id):
        guild = self.bot.guild
        tournament = await self.bot.dh.get_tournament(category_id=category_id)
        tournament_id = tournament['_id']

        tournament_role = discord.utils.get(guild.roles, name=f"{tournament['name']}")
        if tournament_role is None:
            return

        for member in guild.members:
            if tournament_role in member.roles and not member.bot:
                player_registered = await self.bot.dh.get_registration_status(tournament_id, member.id)
                if not player_registered:
                    await self.tournaments[tournament_id].register_player(member.id)
            elif str(member.id) in tournament['entrants']:
                await self.tournaments[tournament_id].unregister_player(member.id)

    def get_tournament_category(self, category_id):
        guild = self.bot.guilds[0]
        category = discord.utils.get(guild.categories, id=category_id)
        return category