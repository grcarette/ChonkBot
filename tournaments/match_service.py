class MatchService:
    """
    Owns the business logic of a single match.
    Knows nothing about Discord, tournament format, or what called it.
    Communicates completion upward via on_complete callback.

    on_complete signature: async def on_complete(result: dict) -> None
    result dict: { match_id, winner_id, loser_id, is_dq }
    """

    def __init__(self, match_id, players, stages, dh, on_complete):
        self.match_id = match_id
        self.players = players
        self.stages = stages
        self.dh = dh
        self.on_complete = on_complete  # async callable

    async def record_result(self, winner_id, loser_id, is_dq=False):
        result = {
            'match_id': self.match_id,
            'winner_id': winner_id,
            'loser_id': loser_id,
            'is_dq': is_dq,
        }
        await self.on_complete(result)
        