import discord
from discord.ext import commands

from utils.emojis import NUMBER_EMOJIS, INDICATOR_EMOJIS
from utils.errors import PlayerNotFoundError

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

DEFAULT_STAGE_NUMBER = 5
CHANNEL_PERMISSIONS = {
    'event-info': 'read_only',
    'event-updates': 'read_only',
    'stagelist': 'read_only',
    'event-chat': 'open',
    'questions': 'open',
    'register': 'read_only',
    'organizer-chat': 'private',
    'bot-control': 'private',
    'check-in': 'read_only',
    'match-calling': 'private',
    'active-matches': 'private'
}

NONDEFAULT_CHANNELS = [
    'check-in',
    'match-calling',
    'active-matches',
]

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
        await tournament_manager.initialize_event()
        self.tournaments[event['_id']] = tournament_manager

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
        await self.add_register_control(tournament, channel_dict['register'])
        await self.add_bot_control(channel_dict['bot-control'])
        await self.initialize_event(tournament)
        
    async def register_player(self, tournament_name, user_id):
        guild = self.bot.guilds[0]
        discord_user = discord.utils.get(guild.members, id=user_id)
        await self.bot.dh.register_user(discord_user)
        tournament_role = discord.utils.get(guild.roles, name=tournament_name)
        await discord_user.add_roles(tournament_role)
        
        user = await self.bot.dh.get_user(user_id=user_id)
        tournament = await self.bot.dh.get_tournament(name=tournament_name)
        player_id = await self.ch.register_player(tournament['challonge_data']['url'], user['name'])
        
        await self.bot.dh.register_player(tournament_name, user_id, player_id)

    async def unregister_player(self, tournament_name, user_id):
        guild = self.bot.guilds[0]
        discord_user = discord.utils.get(guild.members, id=user_id)
        tournament_role = discord.utils.get(guild.roles, name=tournament_name)
        await discord_user.remove_roles(tournament_role)
        
        tournament = await self.bot.dh.get_tournament(name=tournament_name)
        challonge_id = tournament['challonge_data']['id']
        player_id = tournament['entrants'][f'{user_id}']

        await self.bot.dh.unregister_player(tournament_name, user_id)
        await self.ch.unregister_player(challonge_id, player_id)
        
    async def disqualify_player(self, channel, user):
        user_id = user.id
        tournament = await self.bot.dh.get_tournament_by_channel(channel)
        if not tournament:
            raise PlayerNotFoundError
        dq_successful = await self.bot.dh.disqualify_player(tournament, user_id)
        if dq_successful == False:
            await self.unregister_player(tournament['name'], user_id)
        
    async def add_register_control(self, tournament, channel):
        view = RegisterControlView(self.bot)
        embed = discord.Embed(
            title=f"Register for {tournament['name']}",
            color=discord.Color.green()
        )
        await channel.send(embed=embed, view=view)
        
    async def add_bot_control(self, channel):
        view= BotControlView(self.bot)
        embed = discord.Embed(
            title="Tournament Controls",
            color=discord.Color.green()
        )
        await channel.send(embed=embed, view=view)
        
    async def start_checkin(self, category_id):
        guild = self.bot.guilds[0]
        tournament = await self.bot.dh.get_tournament(category_id=category_id)
        checkin_channel = await self.create_channel(
            guild=guild,
            tournament_category=discord.utils.get(guild.categories, id=category_id),
            hide_channel=True,
            channel_name='check-in',
            channel_overwrites=CHANNEL_PERMISSIONS['check-in'] 
        )
        await checkin_channel.edit(position=1)

        tournament_role = discord.utils.get(guild.roles, name=tournament['name'])
        
        message_content = (
            f'{tournament_role.mention}'
        )
        view = TournamentCheckinView(self.bot, tournament)
        embed = await view.generate_embed()

        await checkin_channel.send(content=message_content, embed=embed, view=view)
        
    async def start_tournament(self, kwargs):
        category_id = kwargs.get('category_id')
        guild = self.bot.guild

        tournament_category = self.get_tournament_category(category_id)
        
        match_call_channel = discord.utils.get(tournament_category.channels, name='match-calling')
        active_match_channel = discord.utils.get(tournament_category.channels, name='active-matches')
        
        if not match_call_channel:
            match_call_channel = await self.create_channel(
                guild=guild,
                tournament_category=tournament_category,
                hide_channel=True,
                channel_name='match-calling',
                channel_overwrites=CHANNEL_PERMISSIONS['match-calling'] 
            )
        if not active_match_channel:
            active_match_channel = await self.create_channel(
                guild=guild,
                tournament_category=tournament_category,
                hide_channel=True,
                channel_name='active-matches',
                channel_overwrites=CHANNEL_PERMISSIONS['active-matches'] 
            ) 
        
        checkin_channel = discord.utils.get(tournament_category.channels, name='check-in')
        if checkin_channel:
            await checkin_channel.delete()
            
        tournament_handler = self.tournaments[category_id]
        await self.bot.dh.start_tournament(category_id)
        await tournament_handler.start_tournament()
        await self.refresh_match_calls(category_id)
        
    async def get_players_from_match(self, match_data):
        player_1_id = match_data['player_1']
        player_2_id = match_data['player_2']
        
        player_1 = await self.bot.dh.get_user(user_id=player_1_id)
        player_2 = await self.bot.dh.get_user(user_id=player_2_id)       
        
        return player_1, player_2
    
    async def get_short_timestamp(self, timestamp):
        return timestamp.strftime("%I:%M%p").lstrip("0")
        
    async def add_match_call(self, match_data, category_id):
        guild = self.bot.guilds[0]
        category = self.get_tournament_category(category_id)
        channel = discord.utils.get(category.channels, name='match-calling')
        
        tournament = await self.bot.dh.get_tournament(category_id=category_id)
        
        player_1, player_2 = await self.get_players_from_match(match_data)
        players = [player_1, player_2]
        
        waiting_since = await self.bot.dh.get_lobby_time(match_data['prerequisite_matches'])
        waiting_since = await self.get_short_timestamp(waiting_since)

        if match_data['bracket'] == 'Winners':
            color = discord.Color.green()
        else:
            color = discord.Color.red()
        
        embed = discord.Embed(
            title = f"{match_data['bracket']} round {match_data['round']} - {player_1['name']} vs {player_2['name']}",
            description = f"{waiting_since}",
            color  = color
        )
        view = MatchCallView(self.bot, match_data)
        await channel.send(embed=embed, view=view)
    
    async def call_match(self, match_data):
        guild = self.bot.guilds[0]
        player_1, player_2 = await self.get_players_from_match(match_data)
        
        players = [
            discord.utils.get(guild.members, id=player_1['user_id']),
            discord.utils.get(guild.members, id=player_2['user_id'])
        ]
        
        await self.bot.lh.create_lobby(
            tournament_name = match_data['tournament'],
            match_id = match_data['match_id'],
            prerequisite_matches = match_data['prerequisite_matches'],
            players = players,
            stage=None,
            num_winners=1,
            pool=None
        )
        
    async def get_lobby_string(self, lobby):
        players = []
        for user_id in lobby['players']:
            user = await self.bot.dh.get_user(user_id=user_id)
            players.append(user['name'])
        player_string = ' vs '.join(players)
        timestamp = await self.get_short_timestamp(lobby['state_timestamp'])
        lobby_string = f'{player_string} - {timestamp}\n'
        return lobby_string
        
    async def create_match_calls(self, category_id):
        tournament_handler = self.tournaments[category_id]
        await tournament_handler.call_matches()
        
    async def refresh_match_calls(self, category_id):
        tournament_category = self.get_tournament_category(category_id)
        channel = discord.utils.get(tournament_category.channels, name='match-calling')
        await channel.purge(limit=None)
        await self.create_match_calls(category_id)
        
    async def report_match(self, lobby):
        await self.bot.dh.end_match(lobby['channel_id'])
        tournament = await self.bot.dh.get_tournament(name=lobby['tournament'])
        category_id = tournament['category_id']
        await self.tournaments[category_id].report_match(lobby)
        await self.refresh_match_calls(tournament['category_id'])
        
    async def update_matches(self, tournament):
        await self.refresh_match_calls(tournament['category_id'])
        
    async def confirm_reset_lobby(self, user_id, channel_id, state):
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
        
    async def reset_lobby(self, kwargs):
        lobby = kwargs.get('lobby')
        state = kwargs.get('state')
        
        tournament = await self.bot.dh.get_tournament(name=lobby['tournament'])
        match_reset = await self.tournaments[tournament['category_id']].reset_match(lobby)

        lobby = await self.bot.dh.reset_lobby(lobby['channel_id'], state=state)
        if state == 'stage_bans':
            await self.bot.lh.start_stage_bans(lobby)
        elif state == 'report':
            await self.bot.lh.start_reporting(lobby)
        await self.update_matches(tournament)
        
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
        guild = self.bot.guilds[0]
        tournament = await self.bot.dh.get_tournament(category_id=category_id)
        category_id = tournament['category_id']
        category = self.get_tournament_category(category_id)
        role = discord.utils.get(guild.roles, name=tournament['name'])
        
        if role:
            await role.delete()
        try:
            await category.delete()
        except discord.DiscordException as e:
            print(f"Error deleting category {category.name}: {e}")
            
        await self.bot.dh.delete_tournament(int(category_id))
            
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
    
    async def toggle_reveal_channels(self, category_id):
        guild = self.bot.guilds[0]
        category = self.get_tournament_category(category_id)
        for channel in category.channels:
            permissions = CHANNEL_PERMISSIONS[channel.name]
            if permissions != 'private':
                overwrite = channel.overwrites_for(guild.default_role)
                overwrite.view_channel = not overwrite.view_channel
                await channel.set_permissions(guild.default_role, overwrite=overwrite)
                
    def get_tournament_category(self, category_id):
        guild = self.bot.guilds[0]
        category = discord.utils.get(guild.categories, id=category_id)
        return category
            
        

        
        
        
       
        
        