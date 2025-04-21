from .challonge_handler import ChallongeHandler
from datetime import datetime

from utils.channel_utils import CHANNEL_PERMISSIONS, create_channel
from utils.emojis import RESULT_EMOJIS, INDICATOR_EMOJIS
from utils.discord_preset_colors import PRESET_COLORS
from utils.get_bracket_link import get_bracket_link

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

from .match_lobby import MatchLobby

import discord
import random

RESULTS_CHANNEL_ID = 1346422769721544754

class TournamentManager:
    def __init__(self, bot, tournament):
        self.bot = bot
        self.tournament = tournament
        self.ch = ChallongeHandler()
        self.guild = self.bot.guild
        self.lobbies = {}
        
    async def initialize_event(self):
        tournament = await self.get_tournament()
        if 'challonge_data' in tournament:
            self.ch = ChallongeHandler(tournament['challonge_data']['url'])
        else:
            self.ch = ChallongeHandler()
            challonge_tournament = await self.ch.create_tournament(
                name=tournament['name'],
                tournament_type=tournament['format'],
                start_time=tournament['date']
            )
            name = tournament['name']
            url = challonge_tournament['url']
            tournament_id = challonge_tournament['id']
            await self.bot.dh.add_challonge_to_tournament(name, url, tournament_id)
            
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
            )
            self.lobbies[lobby['match_id']] = match_lobby
            if lobby['state'] == 'initialize':
                pass
            elif lobby['state'] == 'checkin':
                self.bot.add_view(CheckinView(match_lobby))
            elif lobby['state'] == 'stage_bans':
                self.bot.add_view(BanStagesButton(match_lobby))
            elif lobby['state'] == 'reporting':
                self.bot.add_view(MatchReportButton(match_lobby))
                
        self.bot.add_view(RegisterControlView(self))
        self.bot.add_view(BotControlView(self))
        
        if self.tournament['state'] == 'checkin':
            self.bot.add_view(TournamentCheckinView(self))
                
        elif tournament['state'] == 'active':
            await self.start_tournament_loop()
            
    async def register_player(self, user_id):
        guild = self.guild
        discord_user = discord.utils.get(guild.members, id=user_id)
        tournament_role = discord.utils.get(guild.roles, name=self.tournament['name'])
        
        await self.bot.dh.register_user(discord_user)
        await discord_user.add_roles(tournament_role)
        
        user = await self.bot.dh.get_user(user_id=user_id)
        tournament = await self.get_tournament()
        player_id = await self.ch.register_player(tournament['challonge_data']['url'], user['name'])
        
        await self.bot.dh.register_player(tournament['_id'], user_id, player_id)
        
    async def unregister_player(self, user_id):
        guild = self.guild
        discord_user = discord.utils.get(guild.members, id=user_id)
        tournament_role = discord.utils.get(guild.roles, name=self.tournament['name'])
        
        await discord_user.remove_roles(tournament_role)
        
        tournament = await self.get_tournament()
        challonge_id = tournament['challonge_data']['id']
        player_id = tournament['entrants'][f'{user_id}']
        
        await self.bot.dh.unregister_player(tournament['_id'], user_id)
        await self.ch.unregister_player(challonge_id, player_id)
        
    async def create_registration_approval(self, user_id):
        if self.tournament['config']['approved_registration'] == True:
            user = discord.utils.get(self.bot.guild.members, id=user_id)
            approval_channel = await self.get_channel('registration-approval')
            embed = discord.Embed(
                title=user.name,
                color=random.choice(PRESET_COLORS)
            )
            view = RegistrationApprovalView(self, user_id)
            await approval_channel.send(embed=embed, view=view)
        else:
            await self.register_player(user_id)
            
    async def start_tournament(self, kwargs):
        tournament = await self.get_tournament()
        removed_players = [player for player in tournament['entrants'].keys() if int(player) not in tournament['checked_in']]
        for player_id in removed_players:
            await self.unregister_player(tournament['_id'], int(player_id))
        checkin_channel = await self.get_channel('check-in')
        register_channel = await self.get_channel('register')
        await checkin_channel.delete()
        await register_channel.delete()
            
        await self.ch.start_tournament(tournament['challonge_data']['id'])
        
        tournament_category = self.get_tournament_category()
        matchcall_channel = discord.utils.get(tournament_category.channels, name='match-calling')
        if not matchcall_channel:
            await create_channel(
                guild=self.bot.guild,
                tournament_category=self.get_tournament_category(),
                hide_channel=True,
                channel_name='match-calling',
                channel_overwrites=CHANNEL_PERMISSIONS[F'match-calling']
            )
        await self.start_tournament_loop()
        
    async def start_tournament_loop(self):
        await self.refresh_match_calls()
        
    async def refresh_match_calls(self):
        tournament_category = self.get_tournament_category()
        channel = discord.utils.get(tournament_category.channels, name='match-calling')
        await channel.purge(limit=None)
        await self.call_matches()
    
    async def call_matches(self):
        tournament = await self.get_tournament()
        pending_matches = await self.ch.get_pending_matches(tournament['challonge_data']['url'])
        for match in pending_matches:
            match_data = await self.parse_match_data(match)
            match_exists = await self.bot.dh.find_match(match_data['match_id'])
            if not match_exists:
                await self.add_match_call(match_data)
                
    async def add_match_call(self, match_data):
        category = self.get_tournament_category()
        channel = discord.utils.get(category.channels, name='match-calling')
        tournament = await self.get_tournament()
        
        player_1, player_2 = await self.get_players_from_match(match_data)
        players = [player_1, player_2]
        
        waiting_since = await self.bot.dh.get_lobby_time(match_data['prereq_matches'])
        waiting_since = self.get_short_timestamp(waiting_since)
        
        if match_data['bracket'] == 'Winners':
            color = discord.Color.green()
        else:
            color = discord.Color.red()
            
        embed = discord.Embed(
            title = f"{match_data['bracket']} round {match_data['round']} - {player_1['name']} vs {player_2['name']}",
            description = f"{waiting_since}",
            color  = color
        )
        view = MatchCallView(self, match_data)
        await channel.send(embed=embed, view=view)
        
    async def get_lobby_name(self, match_data):
        player_1, player_2 = await self.get_players_from_match(match_data)
        round = match_data['round']
        if match_data['bracket'] == 'Winners':
            bracket_tag = 'w'
        else:
            bracket_tag = 'l'
        lobby_name = f"{bracket_tag}r{round}-{player_1['name']} vs {player_2['name']}"
        return lobby_name
        
    async def call_match(self, match_data):
        guild = self.guild
        tournament = await self.get_tournament()
        
        player_1, player_2 = await self.get_players_from_match(match_data)
        players = [player_1['user_id'], player_2['user_id']]
        
        lobby_name = await self.get_lobby_name(match_data)
        
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
        )
        self.lobbies[match_data['match_id']] = match_lobby
        await match_lobby.initialize_match()
        await self.refresh_match_calls()
        
    async def get_players_from_match(self, match_data):
        player_1_id = match_data['player_1']
        player_2_id = match_data['player_2']
        
        player_1 = await self.bot.dh.get_user(user_id=player_1_id)
        player_2 = await self.bot.dh.get_user(user_id=player_2_id)       
        
        return player_1, player_2
        
    async def parse_match_data(self, match):
        tournament = await self.get_tournament()
        format = tournament['format']
        player_1_id = await self.bot.dh.get_user_by_challonge(tournament['_id'], match['player1_id'])
        player_2_id = await self.bot.dh.get_user_by_challonge(tournament['_id'], match['player2_id'])
        
        round_number = match['round']
        if format == 'single elimination':
            pass
        elif format == 'double elimination':
            if round_number > 0:
                bracket = "Winners"
            else:
                bracket = "Losers"
                
        pre_reqs = match['prerequisite_match_ids_csv']
        if pre_reqs == '':
            prereq_matches = []
        elif isinstance(pre_reqs, float):
            prereq_matches = [int(pre_reqs)]
        elif isinstance(pre_reqs, str):
            pre_req_ids = pre_reqs.split(',')
            prereq_matches = [int(pre_req) for pre_req in pre_req_ids]
               
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
    
    async def prompt_end_tournament(self):
        embed = discord.Embed(
            title="End Tournament",
            description="All matches have concluded. Would you like to end the tourament?",
            color=discord.Color.yellow()
        )
        view = EndTournamentView(self)
        tournament_category = self.get_tournament_category()
        channel = discord.utils.get(tournament_category.channels, name='bot-control')
        await channel.send(embed=embed, view=view)
    
    async def report_match(self, lobby):
        lobby_data = await lobby.get_lobby()
        tournament = await self.get_tournament()
        winner_user_id = str(lobby_data['results'][0])
        winner_id = tournament['entrants'][winner_user_id]
        await self.ch.report_match(tournament['challonge_data']['url'], lobby_data['match_id'], winner_id)
        status = await self.ch.check_tournament_status(tournament['challonge_data']['id'])
        await self.close_prereqs(lobby)
        if status == 'awaiting_review':
            await self.prompt_end_tournament()
        else:
            await self.refresh_match_calls()
        
    async def close_prereqs(self, lobby):
        lobby = await lobby.get_lobby()
        for match_id in lobby['prereq_matches']:
            lobby = await self.bot.dh.get_lobby(match_id)
            if not lobby['state'] == 'closed':
                await self.lobbies[match_id].close_lobby()
    
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
        await self.ch.reset_match(self.tournament['challonge_data']['id'], lobby['match_id'])
          
    async def reset_tournament(self, kwargs):
        tournament = await self.get_tournament()
        for lobby in self.lobbies:
            await self.lobbies[lobby].delete_lobby()
        await self.ch.reset_tournament(tournament['challonge_data']['id'])
        
    async def get_tournament(self):
        tournament = await self.bot.dh.get_tournament_by_id(self.tournament['_id'])
        self.tournament = tournament
        return tournament

    def get_tournament_category(self):
        category = discord.utils.get(self.guild.categories, id=self.tournament['category_id'])
        return category

    def get_short_timestamp(self, timestamp):
        return timestamp.strftime("%I:%M%p").lstrip("0")
    
    async def toggle_reveal_channels(self):
        guild = self.bot.guilds[0]
        category = self.get_tournament_category()
        for channel in category.channels:
            permissions = CHANNEL_PERMISSIONS[channel.name]
            if permissions != 'private':
                overwrite = channel.overwrites_for(guild.default_role)
                overwrite.view_channel = not overwrite.view_channel
                await channel.set_permissions(guild.default_role, overwrite=overwrite)
                
    async def get_channel(self, name):
        tournament_category = self.get_tournament_category()
        checkin_channel = discord.utils.get(tournament_category.channels, name=name)
        return checkin_channel
    
    async def start_checkin(self):
        await self.bot.dh.update_tournament_state(self.tournament['_id'], 'checkin')
        tournament = await self.get_tournament()
        guild = self.bot.guild
        tournament_category = self.get_tournament_category()
        checkin_channel = await self.get_channel('checkin')
        if not checkin_channel:
            checkin_channel = await create_channel(
                guild=guild,
                tournament_category=tournament_category,
                hide_channel=True,
                channel_name='check-in',
                channel_overwrites=CHANNEL_PERMISSIONS['check-in'] 
            )
            await checkin_channel.edit(position=1)
        else:
            await checkin_channel.purge(limit=None)

        tournament_role = discord.utils.get(guild.roles, name=tournament['name'])
        
        message_content = (
            f'{tournament_role.mention}'
        )
        view = TournamentCheckinView(self)
        embed = await view.generate_embed()

        await checkin_channel.send(content=message_content, embed=embed, view=view)
        
    async def end_tournament(self, kwargs):
        await self.bot.dh.end_tournament(self.tournament['_id'])
        await self.ch.finalize_tournament(self.tournament['challonge_data']['id'])
        for lobby in self.lobbies:
            await self.lobbies[lobby].close_lobby()
            
        await self.post_final_results()
            
    async def post_final_results(self):
        channel = discord.utils.get(self.bot.guild.channels, id=RESULTS_CHANNEL_ID)
        challonge_id = self.tournament['challonge_data']['id']
        final_results = await self.ch.get_final_results(challonge_id)
        
        overall_winner = ''
        results = ''
        
        for player in final_results:
            discord_id = await self.bot.dh.get_user_by_challonge(self.tournament['_id'], player['id'])
            if discord_id:
                mention = f"<@{discord_id}>"
            else:
                mention = player['name']
                
            rank = player['final_rank']
                
            if rank == 1:
                emoji = RESULT_EMOJIS['1st']
                overall_winner = f"**{RESULT_EMOJIS['trophy']} Overall Winner: {mention}**\n\n"
            elif rank == 2:
                emoji = RESULT_EMOJIS['2nd']
            elif rank == 3:
                emoji = RESULT_EMOJIS['3rd']            
            elif rank > 3 and rank <= 8:
                emoji = RESULT_EMOJIS['medal']
            else:
                emoji = ''        
                
            results += f"{rank}: {player['name']} {emoji}\n"
            
        message_content = overall_winner + results

        embed = discord.Embed(
            title=f"{self.tournament['name']}",
            description=message_content,
            color=random.choice(PRESET_COLORS)
        )
        label = f"{INDICATOR_EMOJIS['link']} Bracket"
        bracket_link = await get_bracket_link(self.tournament['challonge_data']['url'])
        
        view = LinkView(label, bracket_link)

        await channel.send(embed=embed, view=view)
            
    async def delete_tournament(self):
        tournament = await self.get_tournament()
        if tournament['state'] == 'finished':
            return False
        guild = self.bot.guild
        
        await self.ch.delete_tournament(tournament['challonge_data']['id'])
        tournament_category = self.get_tournament_category()
        for channel in tournament_category.channels:
            await channel.delete()
        for lobby in self.lobbies:
            await self.lobbies[lobby].delete_lobby()
        await self.bot.dh.delete_tournament(tournament['_id'])
        
        tournament_role = discord.utils.get(guild.roles, name=f"{tournament['name']}")
        tournament_to_role = discord.utils.get(guild.roles, name=f"{tournament['name']} TO")
        
        await tournament_role.delete()
        await tournament_to_role.delete()
        await tournament_category.delete()
        

        
        
        