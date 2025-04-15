import challonge
import os
from dotenv import load_dotenv
import asyncio
import datetime

load_dotenv()

class ChallongeHandler:
    def __init__(self, tournament_url=None):
        api_key = os.getenv('CHALLONGE_KEY')
        username = os.getenv('CHALLONGE_USERNAME')
        challonge.set_credentials(username, api_key)
        self.tournament_url = tournament_url
    
    async def register_player(self, tournament_url, player_name):
        player = challonge.participants.create(tournament_url, name=player_name)
        return player['id']
    
    async def unregister_player(self, tournament_id, player_id):
        challonge.participants.destroy(tournament_id, player_id)
    
    async def start_tournament(self, tournament_id):
        tournament = challonge.tournaments.show(tournament_id)
        
        if tournament['state'] != 'pending':
            return

        challonge.tournaments.start(tournament_id)
        
    async def get_tournament_from_url(self, tournament_url):
        tournament = challonge.tournaments.show(tournament_url)
        return tournament
        
    async def get_pending_matches(self, tournament_url):
        matches = challonge.matches.index(tournament_url)
        pending_matches = [match for match in matches if match["state"] == "open"]
        return pending_matches
            
    async def report_match(self, tournament_url, match_id, winner_id, is_dq=False):
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
            tournament_url,
            match_id,
            winner_id=winner_id,
            scores_csv=scores
        )
    
    async def reset_match(self, tournament_id, match_id):
        match = challonge.matches.show(tournament_id, match_id)
        
        if match['state'] == 'complete':
            challonge.matches.reopen(tournament_id, int(match_id))
        return True
        
    async def create_tournament(self, name, tournament_type, url=None, start_time=None):
        if isinstance(start_time, datetime.datetime):
            start_time = start_time
        else:
            start_time = datetime.datetime.now()
            
        tournament = challonge.tournaments.create(
            name=name,
            tournament_type=tournament_type,
            start_time=start_time,
            url=url,
            open_signup=False,
            ranked=False
        )
        self.tournament_url = tournament['url']
        return tournament
    
async def main():
    ch = ChallongeHandler()
    matches = await ch.get_pending_matches('p7nxt030')
    for match in matches:
        print(match['prerequisite_match_ids_csv'])
    
        
if __name__ == "__main__":
    asyncio.run(main())