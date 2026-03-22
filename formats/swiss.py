# formats/swiss.py

from formats.base import BaseFormat
from tournaments.swiss_manager import SwissManager


class SwissFormat(BaseFormat):
    """
    Format implementation for Swiss-system tournaments.

    Owns:
    - Swiss event document creation and lifecycle
    - Player registration in the swiss event (with elo/tier assignment)
    - UCH Ranked account gate for registration
    - Match result recording and UCH Ranked API reporting
    - Final standings posting

    Match calling and round management are delegated to SwissManager,
    which this format owns as a private implementation detail.
    """

    def __init__(self, tm):
        super().__init__(tm)
        self.manager = SwissManager(tm)
        # Keep tm.swiss_manager in sync — TournamentManager still references
        # it in start_tournament_loop until step 7 removes it entirely.

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    async def on_initialize(self) -> None:
        """Create the swiss event document if it doesn't exist yet."""
        tournament = await self.tm.get_tournament()
        swiss_event = await self.dh.get_swiss_event_by_tournament(tournament['_id'])
        if not swiss_event:
            round_limit = tournament.get('round_limit', 8)
            await self.dh.create_swiss_event(tournament['_id'], round_limit)
        elif swiss_event.get('state') == 'active':
            self.manager.running = True

    async def on_player_register(self, user_id: int, user: dict) -> None:
        """
        Add the player to the swiss event's players dict with their elo and tier.
        Stores None as the Challonge ID so registration status checks work uniformly.
        If the tournament is already active, notify SwissManager to trigger pairing.
        """
        ranked_player = await self.tm.get_ranked_player(user_id)
        elo = ranked_player['elo'] if ranked_player else 1200
        username = user['name'] if user else f"Player {user_id}"

        swiss_event = await self.dh.get_swiss_event_by_tournament(self.tm.tournament['_id'])
        if swiss_event:
            await self.dh.swiss_add_player(swiss_event['_id'], user_id, username, elo)

        await self.dh.register_player(self.tm.tournament['_id'], user_id, None)

        tournament = await self.tm.get_tournament()
        if tournament['state'] == 'active':
            await self.manager.on_player_joined()

    async def on_player_unregister(self, user_id: int) -> None:
        """Mark the player as dropped in the swiss event."""
        swiss_event = await self.dh.get_swiss_event_by_tournament(self.tm.tournament['_id'])
        if swiss_event:
            await self.dh.swiss_drop_player(swiss_event['_id'], user_id)
            tournament = await self.tm.get_tournament()
            if tournament['state'] == 'active':
                await self.manager.on_player_dropped()

    async def on_tournament_start(self) -> None:
        """
        Backfill any debug players who registered before the swiss event existed,
        then enable the Start Round button via SwissManager.start().
        """
        if self.tm.debug:
            await self._backfill_debug_players()
        await self.manager.start()

    async def on_result(self, result: dict, lobby) -> None:
        """
        Record the match result in the swiss event, report to the UCH Ranked API
        (non-DQ, non-debug matches only), then notify SwissManager so it can
        check whether the round is complete.

        API flow:
        1. report_match  — submits the result, returns a match_id
        2. accept_match  — called for both winner and loser to confirm
           The winner confirm finalizes the match; the loser confirm may return
           a 500 if the match is already finalized, which is expected and ignored.
        """
        tournament = await self.tm.get_tournament()
        swiss_event = await self.dh.get_swiss_event_by_tournament(tournament['_id'])

        if not swiss_event:
            return

        await self.dh.swiss_record_result(
            swiss_event['_id'],
            result['match_id'],
            result['winner_id'],
            result['loser_id'],
        )

        if not self.tm.debug and not result['is_dq']:
            await self._report_to_ranked_api(result['winner_id'], result['loser_id'])

        await self.manager.on_match_complete(
            result['match_id'],
            result['winner_id'],
            result['loser_id'],
        )

    async def _report_to_ranked_api(self, winner_id: int, loser_id: int) -> None:
        try:
            result = await self.tm.bot.uchranked_api.report_match(
                player1_id=winner_id,
                player2_id=loser_id,
                score='1-0',
            )
            if not result.get('success'):
                await self._alert_ranked_api_failure(winner_id, loser_id, result.get('error'))
                return

            match_id = result.get('match_id')
            if not match_id:
                await self._alert_ranked_api_failure(winner_id, loser_id, "No match_id returned")
                return

            try:
                await self.tm.bot.uchranked_api.accept_match(winner_id, match_id)
            except Exception as e:
                print(f"[Swiss] Winner accept_match failed: {e}")

            try:
                await self.tm.bot.uchranked_api.accept_match(loser_id, match_id)
            except Exception:
                pass  # expected/ignored

        except Exception as e:
            await self._alert_ranked_api_failure(winner_id, loser_id, str(e))

    async def _alert_ranked_api_failure(self, winner_id: int, loser_id: int, error: str = None) -> None:
        print(f"[Swiss] UCH Ranked API failure: winner={winner_id} loser={loser_id} error={error}")
        try:
            channel = await self.tm.get_channel('bot-control')
            if channel:
                embed = discord.Embed(
                    title="⚠️ UCH Ranked API Failure",
                    description=(
                        f"Match result for <@{winner_id}> over <@{loser_id}> "
                        f"**was recorded in the Swiss DB** but **failed to reach UCH Ranked**.\n\n"
                        f"The tournament can continue normally. "
                        f"Use `/force_report_swiss_match` if you need to manually re-trigger the round check, "
                        f"or report the match to UCH Ranked manually.\n\n"
                        + (f"**Error:** `{error}`" if error else "")
                    ),
                    color=discord.Color.red(),
                )
                await channel.send(embed=embed)
        except Exception as e:
            print(f"[Swiss] Failed to send API failure alert: {e}")

    async def on_tournament_end(self) -> None:
        """Post final standings to the results channel."""
        if not self.tm.debug:
            await self.tm.post_final_results()

    async def on_tournament_delete(self) -> None:
        """Swiss has no external bracket to clean up."""
        pass

    # ─── Optional overrides ───────────────────────────────────────────────────

    async def on_registration_gate(self, user_id: int, interaction) -> bool:
        """
        Require a UCH Ranked account to register for Swiss events.
        In debug mode this gate is skipped entirely.
        Returns True to allow registration, False to block.
        """
        if self.tm.debug:
            return True
        ranked_player = await self.tm.get_ranked_player(user_id)
        if not ranked_player:
            await interaction.response.send_message(
                "You need a UCH Ranked account to participate in this event. "
                "You can sign up at <https://uchranked.com>.",
                ephemeral=True,
            )
            return False
        return True

    async def on_match_calling_loop(self) -> None:
        """
        SwissManager.start() already enabled the round button before this is
        called, so there's nothing left to do here.
        """
        pass

    async def get_active_buttons(self, state: str) -> list[str]:
        """Swiss shows the round button when active, nothing else."""
        if state == 'active':
            return ['round_button']
        return []

    @property
    def needs_match_call_refresh(self) -> bool:
        # Swiss drives its own pairing — TM should not call refresh_match_calls
        return False

    @property
    def supports_reset(self) -> bool:
        return False

    @property
    def shows_bracket_link(self) -> bool:
        return False

    # ─── Private helpers ──────────────────────────────────────────────────────

    async def _backfill_debug_players(self) -> None:
        """
        In debug mode, players are registered during open_registration before
        the swiss event document exists. This adds any entrants who are missing
        from the swiss event's players dict.
        """
        swiss_event = await self.dh.get_swiss_event_by_tournament(self.tm.tournament['_id'])
        if not swiss_event:
            return

        tournament = await self.tm.get_tournament()
        for discord_id_str in tournament.get('entrants', {}).keys():
            user_id = int(discord_id_str)
            if str(user_id) not in swiss_event.get('players', {}):
                ranked_player = await self.tm.get_ranked_player(user_id)
                await self.dh.swiss_add_player(
                    swiss_event['_id'],
                    user_id,
                    ranked_player['username'],
                    ranked_player['elo'],
                )