import motor.motor_asyncio
import re
import os
from bson import ObjectId
from dotenv import load_dotenv
from pathlib import Path

class TournamentDataAPI:
    def __init__(self):
        env_path = Path(__file__).resolve().parent.parent / '.env'
        load_dotenv(dotenv_path=env_path)
        TOURNAMENTDATA_URI = str(os.getenv("TOURNAMENTDATA_URI"))

        self.client = motor.motor_asyncio.AsyncIOMotorClient(TOURNAMENTDATA_URI)
        self.db = self.client['UCHTournamentData']
        
        self.players = self.db['players']
        self.matches = self.db['matches']
        self.tournaments = self.db['tournaments']

    async def lookup_player(self, name: str):
        """Finds a player by username or alias (case-insensitive)."""
        search_regex = f"^{re.escape(name)}$"
        return await self.players.find_one({
            "$or": [
                {"username": {"$regex": search_regex, "$options": "i"}},
                {"aliases": {"$regex": search_regex, "$options": "i"}}
            ]
        })

    async def link_discord(self, player_id: ObjectId, discord_id: str):
        """Links a Discord Snowflake to an Atlas Player document."""
        return await self.players.update_one(
            {"_id": player_id},
            {"$set": {"discord_id": discord_id}}
        )

    async def get_player_history(self, player_id: ObjectId):
        """Fetches matches and tournament placements for a player."""
        matches_cursor = self.matches.find({
            "$or": [{"winner_id": player_id}, {"loser_id": player_id}],
            "is_dq": False
        })
        matches = await matches_cursor.to_list(length=1000)

        tourneys_cursor = self.tournaments.find({"events.results.id": player_id})
        tourneys = await tourneys_cursor.to_list(length=200)

        return matches, tourneys

    async def get_recent_results(self, player_id: ObjectId, limit: int = 3):
        """Fetches the most recent tournament placements for a player."""
        cursor = self.tournaments.find(
            {"events.results.id": player_id}
        ).sort("date", -1).limit(limit)
        
        return await cursor.to_list(length=limit)