from .challonge_handler import ChallongeHandler
from datetime import datetime

class BracketHandler():
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
        #go through checked in players in tournament
        tournament = await self.get_tournament()
        removed_players = [player for player in tournament['entrants'].keys() if int(player) not in tournament['checked_in']]
        for player_id in removed_players:
            await self.bot.th.unregister_player(tournament['name'], int(player_id))
            
        await self.ch.start_tournament(tournament['challonge_data']['id'])
        await self.call_matches()
    
    async def call_matches(self):
        tournament = await self.get_tournament()
        pending_matches = await self.ch.get_pending_matches(tournament['challonge_data']['url'])
        for match in pending_matches:
            match_data = await self.parse_match_data(match)
            await self.bot.th.add_match_call(match_data, tournament['category_id'])
            
    async def parse_match_data(self, match):
        tournament = await self.get_tournament()
        format = tournament['format']
        waiting_since = datetime.now().strftime("%I:%M%p").lstrip("0")
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
        match_data = {
            'player_1': int(player_1_id),
            'player_2': int(player_2_id),
            'waiting_since': waiting_since,
            'round': round_number,
            'bracket': bracket, 
            'tournament': tournament['name']
        }
        return match_data

    async def get_tournament(self):
        tournament = await self.bot.dh.get_tournament(name=self.tournament_name)
        return tournament
        
            

        
        
    