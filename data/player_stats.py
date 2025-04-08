import motor.motor_asyncio

from utils.errors import PlayerNotFoundError
from datetime import datetime, timezone, timedelta

class StatsHandler:
    def __init__(self):
        pass
    
    async def find_placement_data(self, player_id):
        query = {
            '_id': player_id
        }
        player = await self.player_collection.find_one(query)
        
        if not player or "tournaments" not in player:
            return []
        
        tournament_ids = player["tournaments"]

        pipeline = [
            {
                "$match": {
                    "id": {"$in": tournament_ids} 
                }
            },
            {
                "$project": {
                    "tournament_id": 1,
                    "name": 1,
                    "date": 1,
                    "total_entrants": {"$size": "$results"},
                    "player_result": {
                        "$arrayElemAt": [
                            {
                                "$filter": {
                                    "input": "$results",
                                    "as": "result",
                                    "cond": {"$eq": ["$$result.id", player_id]}
                                }
                            },
                            0
                        ]
                    }
                }
            },
            {
                "$match": {
                    "player_result": {"$ne": None}
                }
            },
            {
                "$addFields": {
                    "placement_ratio": {
                        "$divide": ["$player_result.placement", "$total_entrants"]
                    }
                }
            },
            {
                "$sort": {"placement_ratio": 1}
            },
            {
                "$limit": 4
            }
        ]
        
        result = await self.tournament_data_collection.aggregate(pipeline).to_list(None)
        return result
    
    async def get_head_to_head(self, player1_name, player2_name, set_limit='5'):
        await self.stats.get_head_to_head(self)
        if set_limit.lower() == "all":
            set_limit = 999
        else:
            try:
                set_limit = int(set_limit)
            except ValueError:
                raise ValueError
        try: 
            player1 = await self.lookup_player(player1_name)
            p1_id = player1['_id']
            
            player2 = await self.lookup_player(player2_name)
            p2_id = player2['_id']

            p1_query = {
                'winner_id': p1_id, 
                'loser_id': p2_id,
                'is_dq': False
            }
            p2_query = {
                'winner_id': p2_id,
                'loser_id': p1_id,
                'is_dq': False
            }
            player_1_wins = await self.match_collection.count_documents(p1_query)
            player_2_wins = await self.match_collection.count_documents(p2_query)
            
            query = {
                '$or': [
                    {'winner_id': p1_id, 'loser_id': p2_id},
                    {'winner_id': p2_id, 'loser_id': p1_id}
                ],
                'is_dq': False
            }
            
            recent_matches = await self.match_collection.find(query).sort('date', -1).limit(set_limit).to_list(None)
            recent_matches_text = ''
            
            max_tourney_name_length = 21
            player_indent_position = 25
            result_indent_position = max(len(player1_name), len(player2_name))
            
            for match in recent_matches:
                if match['winner_id'] == p1_id:
                    winner_name = player1_name
                    loser_name = player2_name
                else:
                    winner_name = player2_name
                    loser_name = player1_name
                query = {
                    'id': match['tournament_id']
                }
                tournament = await self.tournament_data_collection.find_one(query)
                tournament_name = tournament['name'][:max_tourney_name_length]
                if len(tournament['name']) > max_tourney_name_length:
                    tournament_name += '...'
                formatted_string = (
                    f"{tournament_name:<{player_indent_position}}"
                    f"{winner_name:<{result_indent_position}} W-L {loser_name}"
                )
                recent_matches_text += f"```{formatted_string}```"
            return player_1_wins, player_2_wins, recent_matches_text
        except PlayerNotFoundError as e:
            raise PlayerNotFoundError(e.player_name, 'get_head_to_head') from e
        
    async def get_leaderboard(self, timeframe, start_timestamp=None, end_timestamp=None):
        min_match_count = 16
        leaderboard_length = 10
        
        if timeframe.lower() == 'season':
            start_timestamp=datetime(2025,1,1)
            end_timestamp=datetime(2025,7,1)
        elif timeframe.lower() == 'year':
            start_timestamp=datetime.now(timezone.utc) - timedelta(days=365)
            end_timestamp=datetime.now(timezone.utc)
        elif timeframe.lower() == 'custom':
            start_timestamp=start_timestamp
            end_timestamp=end_timestamp
            min_match_count = 8
        else:
            start_timestamp=datetime(2000,1,1)
            end_timestamp=datetime(2030,1,1)
            
        valid_tournaments = await self.tournament_data_collection.find(
            {
                "amateur": False, 
                "date": {"$gte": start_timestamp, "$lte": end_timestamp} 
            },
            {"_id": 0, "id": 1}
        ).to_list(length=None)
        valid_tournament_ids = [tournament["id"] for tournament in valid_tournaments]

        pipeline = [
            {"$match": {
                "is_dq": {"$ne": True},
                "tournament_id": {"$in": valid_tournament_ids}
            }},
            {
                "$project": {
                    "players": [
                        {"player_id": "$winner_id", "win": 1},
                        {"player_id": "$loser_id", "win": 0}
                    ]
                }
            },
            {"$unwind": "$players"},

            {
                "$group": {
                    "_id": "$players.player_id",
                    "total_wins": {"$sum": "$players.win"},
                    "total_matches": {"$sum": 1}
                }
            },

            {
                "$project": {
                    "player_id": "$_id",
                    "_id": 0,
                    "total_wins": 1,
                    "total_matches": 1,
                    "win_rate": {
                        "$cond": {
                            "if": {"$gt": ["$total_matches", 0]},
                            "then": {"$divide": ["$total_wins", "$total_matches"]},
                            "else": 0
                        }
                    }
                }
            },

            {"$match": {"total_matches": {"$gte": min_match_count}}},
            {"$sort": {"win_rate": -1}},
            {"$limit": leaderboard_length}
        ]
        
        result = await self.match_collection.aggregate(pipeline).to_list(length=None)
        leaderboard = []
        for player in result:
            query = {
                '_id': player['player_id']
            }
            player_data = await self.player_collection.find_one(query)
            losses = player['total_matches'] - player['total_wins']
            leaderboard_data = {
                'name': player_data['name'],
                'wins': player['total_wins'],
                'losses': losses,
                'winrate': round(player['win_rate'], 2)
            }
            leaderboard.append(leaderboard_data)
        return leaderboard
    
    async def get_player_stats(self, player_name):
        player = await self.lookup_player(player_name, use_alias=True)
        if not player:
            return False
        
        start_date = datetime(2025, 1, 14)
        end_date = datetime(2025, 6, 14)
        
        winrate_data = await self.find_winrate_data(player['_id'], start_date, end_date)
        placement_data = await self.find_placement_data(player['_id'])
        bracket_demon, rival = await self.find_special_opponents(player['_id'])

        lifetime_wins = winrate_data['lifetime_wins']
        lifetime_losses = winrate_data['lifetime_losses']
        if lifetime_wins == 0 and lifetime_losses == 0:
            lifetime_winrate = 0
        else:
            lifetime_winrate = lifetime_wins / (lifetime_wins + lifetime_losses)
            
        season_wins = winrate_data['season_wins']
        season_losses = winrate_data['season_losses']      
        if season_wins == 0 and season_losses == 0:
            season_winrate = 0
        else:
            season_winrate = season_wins / (season_wins + season_losses)

        placements = [f"{placement['name']}: {placement['player_result']['placement']}/{placement['total_entrants']}" for placement in placement_data]
        
        if bracket_demon == None:
            bracket_demon_stats = None
        else:
            bracket_demon_player = await self.get_player_by_id(bracket_demon['id'])
            bracket_demon_name = bracket_demon_player['name']
            bracket_demon_wins = bracket_demon['wins']
            bracket_demon_losses = bracket_demon['losses']
            bracket_demon_stats = {
                'name': bracket_demon_name,
                'wins': bracket_demon_wins,
                'losses': bracket_demon_losses
            }
        if rival == None:
            rival_stats = None
        else:
            rival_player = await self.get_player_by_id(rival['id'])
            rival_player_name = rival_player['name']
            rival_wins = rival['wins']
            rival_losses = rival['losses']
            rival_stats = {
                'name': rival_player_name,
                'wins': rival_wins,
                'losses': rival_losses
            }
        
        player_stats = {
            'lifetime': {
                'wins': lifetime_wins,
                'losses': lifetime_losses,
                'winrate': round(lifetime_winrate, 2)
            },
            'season': {
                'wins': season_wins,
                'losses': season_losses,
                'winrate': round(season_winrate, 2)
            },
            'placements': placements,
            'bracket_demon': bracket_demon_stats,
            'rival': rival_stats,
        }
        return player_stats