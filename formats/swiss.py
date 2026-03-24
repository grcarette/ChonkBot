# formats/swiss.py

import discord

from formats.base import BaseFormat
from tournaments.swiss_manager import SwissManager


class SwissFormat(BaseFormat):
    """
    Format implementation for Swiss-system tournaments.

    Owns:
    - Swiss event document creation and lifecycle
    - Player registration in the swiss event (with elo/tier assignment)
    - Match result recording (deferred until next round start)
    - Final standings posting
    - Force-end flow

    Ranked reporting and the UCH Ranked registration gate are handled by
    TournamentManager based on the tournament's ranked_reporting config flag.

    Match calling and round management are delegated to SwissManager.
    """

    def __init__(self, tm):
        super().__init__(tm)
        self.manager = SwissManager(tm)
        self.pending_results: list[dict] = []

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    async def on_initialize(self) -> None:
        """Create the swiss event document if it doesn't exist yet,
        and rehydrate any pending results from finished lobbies."""
        tournament = await self.tm.get_tournament()
        swiss_event = await self.dh.get_swiss_event_by_tournament(tournament['_id'])
        if not swiss_event:
            round_limit = tournament.get('round_limit', 8)
            await self.dh.create_swiss_event(tournament['_id'], round_limit)
        elif swiss_event.get('state') == 'active':
            self.manager.running = True
            await self._rehydrate_pending_results(swiss_event)

    async def _rehydrate_pending_results(self, swiss_event: dict) -> None:
        """
        On bot restart, reconstruct pending_results for Ranked API calls
        that were deferred but not yet sent.
        """
        current_round = swiss_event.get('current_round', 0)
        if current_round == 0:
            return

        if not self.tm.is_ranked:
            return

        for m in swiss_event.get('matches', []):
            if (
                m.get('round_number') == current_round
                and m.get('winner') is not None
                and not m.get('flushed')
            ):
                winner_id = m['winner']
                loser_id  = m['player_1'] if m['player_2'] == winner_id else m['player_2']
                self.pending_results.append({
                    'match_id':  m['match_id'],
                    'winner_id': winner_id,
                    'loser_id':  loser_id,
                    'is_dq':     False,
                })

    async def on_player_register(self, user_id: int, user: dict) -> None:
        swiss_event = await self.dh.get_swiss_event_by_tournament(self.tm.tournament['_id'])
        if swiss_event:
            # If player already exists (rejoining), restore without resetting stats
            rejoined = await self.dh.swiss_rejoin_player(swiss_event['_id'], user_id)
            if not rejoined:
                # New player — add fresh with elo/tier
                ranked_player = await self.tm.get_ranked_player(user_id)
                elo = ranked_player['elo'] if ranked_player else 1200
                username = user['name'] if user else f"Player {user_id}"
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
        then start the SwissManager.
        """
        if self.tm.debug:
            await self._backfill_debug_players()
        await self.manager.start()

    async def on_result(self, result: dict, lobby) -> None:
        """
        Immediately record the match result in the swiss DB.
        Defer UCH Ranked API reporting until the next round starts or event ends.
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

        await self.manager.check_round_complete()

        if self.tm.is_ranked and not self.tm.debug and not result['is_dq']:
            self.pending_results.append(result)

    async def flush_pending_results(self) -> None:
        """
        Report all pending match results to UCH Ranked.
        Called at the start of each new round and at event end.
        """
        if not self.pending_results:
            return

        for result in self.pending_results:
            await self.tm.report_result_to_ranked_api(
                result['winner_id'], result['loser_id']
            )

        self.pending_results.clear()

    async def on_tournament_end(self) -> None:
        """Flush any remaining results then post final standings."""
        await self.flush_pending_results()
        if not self.tm.debug:
            await self.tm.post_final_results()

    async def on_tournament_delete(self) -> None:
        """Swiss has no external bracket to clean up."""
        pass

    async def on_match_calling_loop(self) -> None:
        """SwissManager.start() handles everything — nothing to do here."""
        pass

    async def on_reset(self) -> None:
        """Reset swiss state when reverting from active back to check-in."""
        self.manager.running = False
        self.pending_results.clear()
        swiss_event = await self.dh.get_swiss_event_by_tournament(self.tm.tournament['_id'])
        if swiss_event:
            await self.dh.swiss_reset_to_registration(swiss_event['_id'])

    # ─── Force-end flow ───────────────────────────────────────────────────────

    async def force_end_tournament(self, kwargs=None) -> None:
        """
        Force-end a Swiss tournament: flush results, close lobbies, post standings, finalize.
        Called by /end_swiss_tournament via ConfirmationView.
        """
        swiss_event = await self.dh.get_swiss_event_by_tournament(self.tm.tournament['_id'])
        if swiss_event:
            await self.dh.update_swiss_state(swiss_event['_id'], 'finished')

        self.manager.running = False
        await self.flush_pending_results()

        await self.tm.end_tournament()
        await self.tm.post_final_results()
        await self.dh.update_tournament_state(self.tm.tournament['_id'], 'finished')
        await self.tm.finalize_tournament()

    async def get_dashboard_state(self) -> dict:
        tournament  = await self.tm.get_tournament()
        swiss_event = await self.dh.get_swiss_event_by_tournament(tournament['_id'])
        if not swiss_event:
            return {}

        players           = swiss_event.get('players', {})
        active_matches    = sum(
            1 for p in players.values()
            if p.get('active_match_id') is not None and not p.get('dropped')
        ) // 2
        players_remaining = sum(1 for p in players.values() if not p.get('dropped'))
        current_round     = swiss_event.get('current_round', 0)
        round_limit       = swiss_event.get('round_limit', tournament.get('round_limit', 8))
        final_round_active = current_round >= round_limit
        round_ready       = (
            tournament.get('state') == 'active'
            and active_matches == 0
            and players_remaining > 1
            and not final_round_active
        )
        return {
            'current_round':     current_round,
            'round_limit':       round_limit,
            'active_matches':    active_matches,
            'players_remaining': players_remaining,
            'round_ready':       round_ready,
            'final_round_active': final_round_active,
        }

    # ─── Properties ───────────────────────────────────────────────────────────

    @property
    def needs_match_call_refresh(self) -> bool:
        return False

    @property
    def supports_reset(self) -> bool:
        return False

    @property
    def shows_bracket_link(self) -> bool:
        return False

    @property
    def ranked_compatible(self) -> bool:
        return True

    # ─── Private helpers ──────────────────────────────────────────────────────

    async def _backfill_debug_players(self) -> None:
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
                    ranked_player['username'] if ranked_player else f'Player {user_id}',
                    ranked_player['elo'] if ranked_player else 1200,
                )