# formats/challonge.py

from formats.base import BaseFormat
from tournaments.challonge_handler import ChallongeHandler


class ChallongeFormat(BaseFormat):
    """
    Format implementation for Challonge-backed brackets.
    Handles both Double Elimination and Single Elimination,
    since both use the same Challonge API surface.

    Owns:
    - Challonge bracket creation and lifecycle
    - Participant registration / removal
    - Match result reporting to Challonge
    - Bracket finalization and deletion
    - Bracket reset
    """

    def __init__(self, tm):
        super().__init__(tm)
        self.ch = ChallongeHandler()

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    async def on_initialize(self) -> None:
        """
        Create the Challonge bracket if it doesn't exist yet,
        or rehydrate the ChallongeHandler with the stored URL if it does.
        Syncs self.ch back to tm.ch so TM utilities still work.
        """
        tournament = await self.tm.get_tournament()
        if 'challonge_data' in tournament:
            self.ch = ChallongeHandler(tournament['challonge_data']['url'])
        else:
            challonge_tournament = await self.ch.create_tournament(
                name=tournament['name'],
                tournament_type=tournament['format'],
                start_time=tournament['date'],
            )
            url = challonge_tournament['url']
            tournament_id = challonge_tournament['id']
            await self.dh.add_challonge_to_tournament(tournament['name'], url, tournament_id)
            self.ch = ChallongeHandler(url)
        # Keep tm.ch in sync — TM utilities (reset_match etc.) still reference it
        self.tm.ch = self.ch

    async def on_player_register(self, user_id: int, user: dict) -> None:
        """
        Register the player as a Challonge participant and store their participant ID.
        In debug mode, uses the player's display name directly without an API call
        since debug players are already created with fake names by register_player.
        """
        tournament = await self.tm.get_tournament()
        if self.tm.debug:
            # Debug: register fake players on Challonge with their debug username
            username = user['name'] if user else f'debug_user_{user_id}'
            player_id = await self.ch.register_player(
                tournament['challonge_data']['url'], username
            )
        else:
            player_id = await self.ch.register_player(
                tournament['challonge_data']['url'], user['name']
            )
        await self.dh.register_player(tournament['_id'], user_id, player_id)

    async def on_player_unregister(self, user_id: int) -> None:
        """Destroy the Challonge participant for this player."""
        tournament = await self.tm.get_tournament()
        player_id = tournament['entrants'].get(str(user_id))
        print(f"[on_player_unregister] user_id={user_id} player_id={player_id}")
        if player_id is not None:
            await self.ch.unregister_player(tournament['challonge_data']['id'], player_id)

    async def on_tournament_start(self) -> None:
        """Lock in the bracket seeding on Challonge."""
        tournament = await self.tm.get_tournament()
        await self.ch.start_tournament(tournament['challonge_data']['id'])

    async def on_result(self, result: dict, lobby) -> None:
        import time
        t0 = time.perf_counter()

        tournament = await self.tm.get_tournament()
        winner_user_id = str(result['winner_id'])
        challonge_winner_id = tournament['entrants'][winner_user_id]

        await self.ch.report_match(
            tournament['challonge_data']['url'],
            result['match_id'],
            challonge_winner_id,
            result['is_dq'],
        )
        print(f"[timing] challonge report_match: {time.perf_counter()-t0:.3f}s")

        status = await self.ch.check_tournament_status(tournament['challonge_data']['id'])
        print(f"[timing] check_tournament_status: {time.perf_counter()-t0:.3f}s")

        await self.tm.close_prereqs(lobby)
        print(f"[timing] close_prereqs: {time.perf_counter()-t0:.3f}s")

        if status == 'awaiting_review':
            await self.tm.bot.dh.update_tournament_state(self.tm.tournament['_id'], 'finished')
            self.tm.invalidate_pending_cache()
        else:
            if getattr(self.tm, 'autocall_matches', False):
                await self.tm.call_matches()
        print(f"[timing] call_matches/finish: {time.perf_counter()-t0:.3f}s")

        print(f"[timing] on_result TOTAL: {time.perf_counter()-t0:.3f}s")

    async def on_tournament_end(self) -> None:
        """Finalize the Challonge bracket (locks it, prevents further edits)."""
        tournament = await self.tm.get_tournament()
        await self.ch.finalize_tournament(tournament['challonge_data']['id'])

    async def on_tournament_delete(self) -> None:
        """Delete the Challonge bracket entirely."""
        tournament = await self.tm.get_tournament()
        if 'challonge_data' in tournament:
            await self.ch.delete_tournament(tournament['challonge_data']['id'])

    # ─── Optional overrides ───────────────────────────────────────────────────

    async def on_reset(self) -> None:
            """Reset the Challonge bracket to pre-start state."""
            tournament = await self.tm.get_tournament()
            challonge_id = tournament['challonge_data']['id']
            status = await self.ch.check_tournament_status(challonge_id)
            if status in ('underway', 'awaiting_review', 'complete'):
                await self.ch.reset_tournament(challonge_id)
            # If still 'pending', nothing to reset — bracket was never started

    async def on_reset_report(self, lobby: dict) -> None:
        """Reopen the match on Challonge so it can be re-reported."""
        tournament = await self.tm.get_tournament()
        await self.ch.reset_match(tournament['challonge_data']['id'], lobby['match_id'])

    @property
    def needs_match_call_refresh(self) -> bool:
        return True

    @property
    def supports_reset(self) -> bool:
        return True

    @property
    def shows_bracket_link(self) -> bool:
        return True