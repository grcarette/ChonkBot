import challonge
import os
from dotenv import load_dotenv

load_dotenv()

class ChallongeHandler:
    def __init__(self):
        api_key = os.getenv('CHALLONGE_KEY')
        username = os.getenv('CHALLONGE_USERNAME')
        challonge.set_credentials(username, api_key)
        self.tournament_url = 'g78avo67'
    
    async def register_player(self, name):
        player = challonge.participants.create(self.tournament_url, name=name)
        return player['id']
        
    async def get_pending_matches(self):
        matches = challonge.matches.index(self.tournament_url)
        pending_matches = [match for match in matches if match["state"] == "open"]
        return pending_matches
            
    async def report_match(self, match_id, winner_id, is_dq=False):
        match = challonge.matches.show(self.tournament_url, match_id)
        
        player1_id = match['player1_id']
        
        if winner_id == player1_id:
            if is_dq:
                scores = "0--1"
            else:
                scores = "1-0"
        else:
            if is_dq:
                scores = "-1-0"
            else:
                scores = "0-1"
        
        challonge.matches.update(
            self.tournament_url,
            match_id,
            winner_id=winner_id,
            scores_csv=scores
        )
        
    async def disqualify_player(self, player_id):
        challonge.participants.update(self.tournament_url, player_id, disqualified=True)
        
    async def create_tournament(self, name, tournament_type, url=None):
        tournament = challonge.tournaments.create(
            name=name,
            tournament_type=tournament_type,
            url=url,
            open_signup=False,
            ranked=False
        )
        return tournament['url']
