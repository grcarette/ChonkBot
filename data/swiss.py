import hashlib
from datetime import datetime, timezone
from bson import ObjectId


def _now():
    return datetime.now(timezone.utc)


def get_tier(elo: int) -> tuple[int, int]:
    """
    Return (tier, bonus_points) based on elo.
    Tier 1: elo > 2000  → 2 bonus points
    Tier 2: elo 1400-2000 → 1 bonus point
    Tier 3: elo < 1400  → 0 bonus points
    """
    if elo > 2000:
        return 1, 2
    elif elo >= 1400:
        return 2, 1
    else:
        return 3, 0


def generate_match_id(tournament_id: str, sequence: int) -> int:
    """
    Generate a unique integer match_id from a tournament_id and sequence number.
    Result is guaranteed to fit in a signed 64-bit integer (BSON compatible).
    """
    key = f"{tournament_id}:{sequence}"
    hash_bytes = hashlib.md5(key.encode()).digest()[:8]
    unsigned = int.from_bytes(hash_bytes, byteorder='big')
    return unsigned & 0x7FFFFFFFFFFFFFFF


class SwissMethodsMixin:

    # ─── Event lifecycle ──────────────────────────────────────────────────────

    async def create_swiss_event(self, tournament_id: ObjectId, round_limit: int) -> dict:
        """Create a new swiss event document linked to a tournament."""
        event = {
            'tournament_id': tournament_id,
            'state': 'registration',
            'round_limit': round_limit,
            'players': {},
            'matches': [],
            'bye_queue': None,
            'bye_task_started_at': None,
            'next_match_sequence': 0,
            'created_at': _now(),
        }
        result = await self.swiss_collection.insert_one(event)
        return await self.get_swiss_event(result.inserted_id)

    async def get_swiss_event(self, event_id: ObjectId) -> dict | None:
        return await self.swiss_collection.find_one({'_id': ObjectId(event_id)})

    async def get_swiss_event_by_tournament(self, tournament_id: ObjectId) -> dict | None:
        return await self.swiss_collection.find_one({'tournament_id': ObjectId(tournament_id)})

    async def update_swiss_state(self, event_id: ObjectId, state: str):
        await self.swiss_collection.update_one(
            {'_id': ObjectId(event_id)},
            {'$set': {'state': state}}
        )

    # ─── Player management ────────────────────────────────────────────────────

    async def swiss_add_player(
        self,
        event_id: ObjectId,
        discord_id: int,
        username: str,
        elo: int,
    ) -> dict:
        """
        Add a player to the swiss event.
        Assigns tier and bonus points based on elo.
        Returns the created player dict.
        """
        tier, bonus_points = get_tier(elo)
        player_data = {
            'username': username,
            'elo': elo,
            'tier': tier,
            'points': float(bonus_points),
            'wins': 0,
            'losses': 0,
            'rounds_played': 0,
            'active_match_id': None,
            'dropped': False,
            'match_history': [],
            'joined_at': _now(),
        }
        await self.swiss_collection.update_one(
            {'_id': ObjectId(event_id)},
            {'$set': {f'players.{discord_id}': player_data}}
        )
        return player_data

    async def swiss_drop_player(self, event_id: ObjectId, discord_id: int):
        """Mark a player as dropped. Their record stands."""
        await self.swiss_collection.update_one(
            {'_id': ObjectId(event_id)},
            {'$set': {f'players.{discord_id}.dropped': True}}
        )

    async def swiss_set_active_match(
        self,
        event_id: ObjectId,
        discord_id: int,
        match_id: int | None
    ):
        """Set or clear a player's active match."""
        await self.swiss_collection.update_one(
            {'_id': ObjectId(event_id)},
            {'$set': {f'players.{discord_id}.active_match_id': match_id}}
        )

    # ─── Match management ─────────────────────────────────────────────────────

    async def swiss_next_match_id(self, event_id: ObjectId, tournament_id: str) -> int:
        """
        Atomically increment the match sequence and return a unique match_id.
        The returned ID is guaranteed unique across all tournaments.
        """
        result = await self.swiss_collection.find_one_and_update(
            {'_id': ObjectId(event_id)},
            {'$inc': {'next_match_sequence': 1}},
            return_document=True
        )
        sequence = result['next_match_sequence']
        return generate_match_id(str(tournament_id), sequence)

    async def swiss_create_match(
        self,
        event_id: ObjectId,
        match_id: int,
        player_1: int,
        player_2: int,
    ) -> dict:
        """
        Record a new match between two players.
        Also marks both players as having an active match
        and records them in each other's match history.
        """
        match = {
            'match_id': match_id,
            'player_1': player_1,
            'player_2': player_2,
            'winner': None,
            'state': 'active',
            'created_at': _now(),
        }
        await self.swiss_collection.update_one(
            {'_id': ObjectId(event_id)},
            {
                '$push': {'matches': match},
                '$set': {
                    f'players.{player_1}.active_match_id': match_id,
                    f'players.{player_2}.active_match_id': match_id,
                },
                '$addToSet': {
                    f'players.{player_1}.match_history': player_2,
                    f'players.{player_2}.match_history': player_1,
                }
            }
        )
        return match

    async def swiss_record_result(
        self,
        event_id: ObjectId,
        match_id: int,
        winner_id: int,
        loser_id: int,
    ):
        """
        Record the result of a match.
        - Winner gets 1 point, rounds_played + 1, active_match cleared
        - Loser gets rounds_played + 1, active_match cleared
        - Match state set to finished
        """
        event = await self.get_swiss_event(event_id)
        winner = event['players'][str(winner_id)]
        loser = event['players'][str(loser_id)]

        await self.swiss_collection.update_one(
            {'_id': ObjectId(event_id), 'matches.match_id': match_id},
            {
                '$set': {
                    'matches.$.winner': winner_id,
                    'matches.$.state': 'finished',
                    f'players.{winner_id}.active_match_id': None,
                    f'players.{winner_id}.points': winner['points'] + 1,
                    f'players.{winner_id}.wins': winner['wins'] + 1,
                    f'players.{winner_id}.rounds_played': winner['rounds_played'] + 1,
                    f'players.{loser_id}.active_match_id': None,
                    f'players.{loser_id}.losses': loser['losses'] + 1,
                    f'players.{loser_id}.rounds_played': loser['rounds_played'] + 1,
                }
            }
        )

    # ─── Bye management ───────────────────────────────────────────────────────

    async def swiss_set_bye_queue(
        self,
        event_id: ObjectId,
        discord_id: int | None,
    ):
        """Set or clear the player waiting for a bye."""
        update = {
            'bye_queue': discord_id,
            'bye_task_started_at': _now() if discord_id is not None else None,
        }
        await self.swiss_collection.update_one(
            {'_id': ObjectId(event_id)},
            {'$set': update}
        )

    async def swiss_award_bye(self, event_id: ObjectId, discord_id: int):
        """
        Award a bye to a player.
        Counts as a round played and grants 1 point.
        """
        event = await self.get_swiss_event(event_id)
        player = event['players'][str(discord_id)]
        await self.swiss_collection.update_one(
            {'_id': ObjectId(event_id)},
            {
                '$set': {
                    f'players.{discord_id}.points': player['points'] + 1,
                    f'players.{discord_id}.rounds_played': player['rounds_played'] + 1,
                    'bye_queue': None,
                    'bye_task_started_at': None,
                }
            }
        )

    # ─── Queries ──────────────────────────────────────────────────────────────

    async def swiss_get_available_players(self, event_id: ObjectId) -> list[dict]:
        """
        Return all players who are:
        - Not dropped
        - Not currently in a match
        - Have not hit the round limit
        Each returned dict includes the discord_id as a key for convenience.
        """
        event = await self.get_swiss_event(event_id)
        round_limit = event['round_limit']
        available = []
        for discord_id, player in event['players'].items():
            if (
                not player['dropped']
                and player['active_match_id'] is None
                and player['rounds_played'] < round_limit
            ):
                available.append({'discord_id': int(discord_id), **player})
        return available

    async def swiss_get_standings(self, event_id: ObjectId) -> list[dict]:
        """
        Return all players sorted by:
        1. Points (descending)
        2. Wins (descending)
        3. Elo (descending)
        Each returned dict includes discord_id for convenience.
        """
        event = await self.get_swiss_event(event_id)
        standings = [
            {'discord_id': int(did), **p}
            for did, p in event['players'].items()
        ]
        standings.sort(key=lambda p: (-p['points'], -p['wins'], -p['elo']))
        return standings

    async def swiss_is_event_complete(self, event_id: ObjectId) -> bool:
        """
        Returns True if all active (non-dropped) players have
        reached the round limit and have no active match.
        """
        event = await self.get_swiss_event(event_id)
        round_limit = event['round_limit']
        for player in event['players'].values():
            if player['dropped']:
                continue
            if player['rounds_played'] < round_limit:
                return False
            if player['active_match_id'] is not None:
                return False
        return True