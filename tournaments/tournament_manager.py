from .challonge_handler import ChallongeHandler
from datetime import datetime

from ui.match_call import MatchCallView
from ui.checkin import CheckinView
from ui.stage_bans import BanStagesButton
from ui.match_report import MatchReportButton

from .match_lobby import MatchLobby

import discord

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
                
            #add register button
            #add bot control view
                
        if tournament['state'] == 'active':
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
        
        await self.bot.dh.register_player(tournament['name'], user_id, player_id)
        
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
            
    async def start_tournament(self):
        tournament = await self.get_tournament()
        removed_players = [player for player in tournament['entrants'].keys() if int(player) not in tournament['checked_in']]
        for player_id in removed_players:
            await self.unregister_player(tournament['_id'], int(player_id))
            
        await self.ch.start_tournament(tournament['challonge_data']['id'])
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
        
    async def call_match(self, match_data):
        guild = self.guild
        tournament = await self.get_tournament()
        
        player_1, player_2 = await self.get_players_from_match(match_data)
        players = [player_1['user_id'], player_2['user_id']]
        
        match_lobby = await MatchLobby.create(
            tournament_id=tournament['_id'],
            match_id=match_data['match_id'],
            lobby_name='|WR1| Bojack vs Bojack',
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
        
    async def get_players_from_match(self, match_data):
        player_1_id = match_data['player_1']
        player_2_id = match_data['player_2']
        
        player_1 = await self.bot.dh.get_user(user_id=player_1_id)
        player_2 = await self.bot.dh.get_user(user_id=player_2_id)       
        
        return player_1, player_2
        
    async def parse_match_data(self, match):
        tournament = await self.get_tournament()
        format = tournament['format']
        player_1_id = await self.bot.dh.get_user_by_challonge(tournament['name'], match['player1_id'])
        player_2_id = await self.bot.dh.get_user_by_challonge(tournament['name'], match['player2_id'])
        
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
    
    async def report_match(self, lobby):
        lobby_data = await lobby.get_lobby()
        tournament = await self.get_tournament()
        winner_user_id = str(lobby_data['results'][0])
        winner_id = tournament['entrants'][winner_user_id]
        await self.ch.report_match(tournament['challonge_data']['url'], lobby_data['match_id'], winner_id)
        await self.refresh_match_calls()
        await self.close_prereqs(lobby)
        
    async def close_prereqs(self, lobby):
        lobby = await lobby.get_lobby()
        for prereq in lobby['prereq_matches']:
            await self.lobbies[prereq].close_lobby()
    
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
        
    async def get_tournament(self):
        tournament = await self.bot.dh.get_tournament_by_id(self.tournament['_id'])
        self.tournament = tournament
        return tournament

    def get_tournament_category(self):
        category = discord.utils.get(self.guild.categories, id=self.tournament['category_id'])
        return category

    def get_short_timestamp(self, timestamp):
        return timestamp.strftime("%I:%M%p").lstrip("0")