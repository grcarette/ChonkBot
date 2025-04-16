import discord
from discord.ext import commands

from utils.emojis import NUMBER_EMOJIS, INDICATOR_EMOJIS
from utils.errors import PlayerNotFoundError
from utils.channel_permissions import DEFAULT_STAGE_NUMBER, CHANNEL_PERMISSIONS, NONDEFAULT_CHANNELS

from ui.bot_control import BotControlView
from ui.register_control import RegisterControlView
from ui.tournament_checkin import TournamentCheckinView
from ui.match_call import MatchCallView
from ui.confirmation import ConfirmationView
from ui.checkin import CheckinView
from ui.stage_bans import BanStagesButton
from ui.match_report import MatchReportButton

from tournaments.match_lobby import MatchLobby
from tournaments.tournament_manager import TournamentManager

from .bracket_handler import BracketHandler
from tournaments.challonge_handler import ChallongeHandler



class TournamentHandler():
    def __init__(self, bot):
        self.bot = bot
        self.ch = ChallongeHandler()
        self.tournaments = {}
        
    async def initialize_active_events(self):
        active_events = await self.bot.dh.get_active_events()
        for event in active_events:
            await self.initialize_event(event)
            
    async def initialize_event(self, event):
        tournament_manager = TournamentManager(self.bot, event) 
        self.tournaments[event['_id']] = tournament_manager
        await tournament_manager.initialize_event()
        return tournament_manager
        

    async def set_up_tournament(self, tournament):
        guild = self.bot.guilds[0]
        tournament = await self.bot.dh.create_tournament(tournament)
        await self.add_stages_tournament(tournament)
        
        organizer_role = await guild.create_role(name=f"{tournament['name']} TO")
        tournament_role = await guild.create_role(name=f"{tournament['name']}")
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False)
        }
        
        tournament_category = await guild.create_category(
            f"{tournament['name']}", 
            overwrites=overwrites
        )
        await self.bot.dh.add_category_to_tournament(tournament['name'], tournament_category.id)
        
        channel_dict = {}
        
        for channel in CHANNEL_PERMISSIONS:
            if channel not in NONDEFAULT_CHANNELS:
                channel_dict[f'{channel}'] = await self.create_channel(
                    guild=guild, 
                    tournament_category=tournament_category, 
                    hide_channel=True, 
                    channel_name=f'{channel}', 
                    channel_overwrites=CHANNEL_PERMISSIONS[f'{channel}']
                )
        
        await self.post_stages(tournament['name'], channel_dict['stagelist'])
        tournament = await self.bot.dh.get_tournament(name=tournament['name'])

        tournament_manager = await self.initialize_event(tournament)
        await self.add_register_control(tournament_manager)
        await self.add_bot_control(tournament_manager)
                
    async def add_register_control(self, tournament_manager):
        tournament = tournament_manager.tournament
        channel = await self.get_tournament_channel(tournament_manager, 'register')
        view = RegisterControlView(tournament_manager)
        embed = discord.Embed(
            title=f"Register for {tournament['name']}",
            color=discord.Color.green()
        )
        await channel.send(embed=embed, view=view)
        
    async def add_bot_control(self, tournament_manager):
        channel = await self.get_tournament_channel(tournament_manager, 'bot-control')
        view= BotControlView(tournament_manager)
        embed = discord.Embed(
            title="Tournament Controls",
            color=discord.Color.green()
        )
        await channel.send(embed=embed, view=view)
        
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
            color=discord.Color.red()
        )
        
        view = ConfirmationView(tm.reset_report, user_id, lobby=lobby)
        await channel.send(embed=embed, view=view)
 
    async def post_stages(self, tournament_name, channel):
        tournament = await self.bot.dh.get_tournament(name=tournament_name)
        for stage_code in tournament['stagelist']:
            stage = await self.bot.dh.get_stage(code=stage_code)
            message = (
                f"# {stage['name']}\n"
                f"Creator: {stage['creator']}\n"
                f"Code: {stage['code']}\n"
                f"{stage['imgur']}"
            )
            await channel.send(message)
        
    async def add_stages_tournament(self, tournament):       
        if tournament['config']['randomized_stagelist'] == True:
            stages = await self.bot.dh.get_random_stages(DEFAULT_STAGE_NUMBER)
            await self.bot.dh.add_stages_to_tournament(tournament['name'], stages)

    async def remove_tournament(self, kwargs):
        category_id = kwargs.get('category_id')
        guild = self.bot.guilds
        tournament = await self.bot.dh.get_tournament(category_id=category_id)
        await self.tournaments[tournament['_id']].delete_tournament()
            
    async def create_channel(self, guild, tournament_category, hide_channel, channel_name, channel_overwrites):
        overwrites = {}
        view_channel = False
        if channel_overwrites == 'read_only':
            if not hide_channel:
                view_channel = True
            overwrites[guild.default_role] = discord.PermissionOverwrite(
                view_channel=view_channel,
                send_messages=False,
                manage_messages=False,
                embed_links=False,
                attach_files=False,
                read_message_history=True,
                add_reactions=True,
                use_external_emojis=True
            )
        elif channel_overwrites == "open":
            if not hide_channel:
                view_channel = True
            overwrites[guild.default_role] = discord.PermissionOverwrite(
                view_channel=view_channel,
                send_messages=True,
                manage_messages=False,
                embed_links=True,
                attach_files=True,
                read_message_history=True,
                add_reactions=True,
                use_external_emojis=True
            )
        elif channel_overwrites == 'private':
            overwrites[guild.default_role] = discord.PermissionOverwrite(
                view_channel=view_channel,
                send_messages=False,
                manage_messages=False,
                embed_links=False,
                attach_files=False,
                read_message_history=False,
                add_reactions=False,
                use_external_emojis=False
            )
        
        new_channel = await guild.create_text_channel(
            f'{channel_name}',
            category=tournament_category,
            overwrites=overwrites
        )
        return new_channel
 
    def get_tournament_category(self, category_id):
        guild = self.bot.guilds[0]
        category = discord.utils.get(guild.categories, id=category_id)
        return category
            
        

        
        
        
       
        
        