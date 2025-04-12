from .challonge_handler import ChallongeHandler
from datetime import datetime

class BracketHandler:
    def __init__(self, bot, tournament):
        self.bot = bot
        self.tournament_name = tournament['name']
        self.ch = ChallongeHandler()
        
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
            
    async def start_tournament(self):
        tournament = await self.get_tournament()
        removed_players = [player for player in tournament['entrants'].keys() if int(player) not in tournament['checked_in']]
        for player_id in removed_players:
            await self.bot.th.unregister_player(tournament['name'], int(player_id))
            
        await self.ch.start_tournament(tournament['challonge_data']['id'])
    
    async def call_matches(self):
        tournament = await self.get_tournament()
        pending_matches = await self.ch.get_pending_matches(tournament['challonge_data']['url'])
        for match in pending_matches:
            match_data = await self.parse_match_data(match)
            match_exists = await self.bot.dh.find_match(match_data['match_id'])
            if not match_exists:
                await self.bot.th.add_match_call(match_data, tournament['category_id'])
            
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
            prerequisite_matches = []
        elif isinstance(pre_reqs, float):
            prerequisite_matches = [int(pre_reqs)]
        elif isinstance(pre_reqs, str):
            pre_req_ids = pre_reqs.split(',')
            prerequisite_matches = [int(pre_req) for pre_req in pre_req_ids]
               
        match_data = {
            'player_1': int(player_1_id),
            'player_2': int(player_2_id),
            'match_id': match['id'],
            'round': round_number,
            'bracket': bracket, 
            'tournament': tournament['name'],
            'prerequisite_matches': prerequisite_matches
        }
        return match_data
    
    async def report_match(self, lobby):
        tournament = await self.get_tournament()
        winner_user_id = str(lobby['results'][0])
        winner_id = tournament['entrants'][winner_user_id]
        await self.ch.report_match(tournament['challonge_data']['url'], lobby['match_id'], winner_id)
        
    async def reset_match(self, lobby):
        tournament = await self.get_tournament()
        match_reset = await self.ch.reset_match(tournament['challonge_data']['id'], lobby['match_id'])
        
        dependent_matches = await self.bot.dh.get_dependent_matches(lobby['match_id'])
        for lobby in dependent_matches:
            await self.bot.lh.delete_lobby(lobby)
        return match_reset
        
    async def get_tournament(self):
        tournament = await self.bot.dh.get_tournament(name=self.tournament_name)
        return tournament
        
            

        
        
    