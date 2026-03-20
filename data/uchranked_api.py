import os
import httpx
import json
from dotenv import load_dotenv

load_dotenv()

UCHRANKED_BASE = "https://uchranked.com/api"


class UCHRankedAPI:
    def __init__(self):
        self.api_key = os.getenv("UCHRANKED_API_KEY")
        self.headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json"
        }

    async def _post(self, endpoint: str, payload: dict) -> dict:
        """Internal helper — POST to an endpoint and return parsed JSON."""
        url = f"{UCHRANKED_BASE}/{endpoint}"
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.post(url, json=payload, headers=self.headers)
            response.raise_for_status()
            try:
                return response.json()
            except json.JSONDecodeError:
                decoder = json.JSONDecoder()
                obj, _ = decoder.raw_decode(response.text.strip())
                return obj

    async def get_player(self, discord_id: int) -> dict | None:
        data = await self._post("elo.php", {"discord_id": int(discord_id)})
        if not data.get("found"):
            return None
        return data

    async def get_leaderboard(self, n: int) -> list:
        """Fetch the top n players by elo."""
        data = await self._post("leaderboard.php", {"n": n})
        return data

    async def get_recent_games(self, n: int) -> list:
        """Fetch the n most recent games."""
        data = await self._post("recent-games.php", {"n": n})
        return data

    async def get_winstreak_leaderboard(self, n: int) -> list:
        """Fetch the top n players by win streak."""
        data = await self._post("winstreak-leaderboard.php", {"n": n})
        return data.get("players", [])

    async def get_winrate(self, discord_id: int) -> dict | None:
        """
        Fetch a player's win/loss/winrate by Discord ID.
        Returns the response dict if found, None if not found.
        """
        data = await self._post("winrate.php", {"discord_id": int(discord_id)})
        if not data.get("found"):
            return None
        return data

    async def report_match(
        self,
        player1_id: int,
        player2_id: int,
        score: str,
        vod: str = ""
    ) -> dict:
        """
        Report a match result to UCH Ranked.
        score should be a string like "2-1".
        Returns the API response dict with keys: success, error, match_id.
        """
        data = await self._post("report-match.php", {
            "player1_id": int(player1_id),
            "player2_id": int(player2_id),
            "score": score,
            "vod": vod
        })
        return data

    async def accept_match(self, discord_id: int, match_id: int) -> dict:
        """Accept a reported match result."""
        data = await self._post("accept-match.php", {
            "discord_id": int(discord_id),
            "match_id": match_id
        })
        return data

    async def reject_match(self, discord_id: int, match_id: int) -> dict:
        """Reject a reported match result."""
        data = await self._post("reject-match.php", {
            "discord_id": int(discord_id),
            "match_id": match_id
        })
        return data

    async def accept_all(self, discord_id: int) -> dict:
        """Accept all pending match results for a player."""
        data = await self._post("accept-all.php", {
            "discord_id": int(discord_id)
        })
        return data

    async def get_matches(self, discord_id: int) -> list:
        """
        Fetch all pending/recent matches for a player.
        Returns a list of match dicts, or empty list on failure.
        """
        data = await self._post("get-matches.php", {
            "discord_id": int(discord_id)
        })
        if not data.get("success"):
            return []
        return data.get("response", [])


# ─── Standalone test ──────────────────────────────────────────────────────────

async def main():
    import asyncio
    api = UCHRankedAPI()

    print("=== Testing get_player (ivory_penguin) ===")
    player = await api.get_player(1374498306020999230)
    print(player)

    print("\n=== Testing get_leaderboard (top 5) ===")
    leaderboard = await api.get_leaderboard(5)
    for entry in leaderboard:
        print(entry)

    print("\n=== Testing get_recent_games (last 3) ===")
    games = await api.get_recent_games(3)
    for game in games:
        print(game)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())