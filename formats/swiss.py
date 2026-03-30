# formats/swiss.py

import asyncio
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

    def _get_flush_lock(self) -> asyncio.Lock:
        lock = getattr(self, '_flush_lock_instance', None)
        if lock is None:
            lock = asyncio.Lock()
            self._flush_lock_instance = lock
        return lock

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    async def on_initialize(self) -> None:
        """Create the swiss event document if it doesn't exist yet,
        and rehydrate any pending results from finished lobbies."""
        tournament = self.tm.tournament  # use in-memory doc — avoids DB overwrite crash for phase TMs
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
        rejoined = False
        if swiss_event:
            rejoined = await self.dh.swiss_rejoin_player(swiss_event['_id'], user_id)
            if not rejoined:
                tournament = await self.tm.get_tournament()
                if str(user_id) in tournament.get('dqs', []):
                    return
                ranked_player = await self.tm.get_ranked_player(user_id)
                elo = ranked_player['elo'] if ranked_player else 1200
                username = user['name'] if user else f"Player {user_id}"
                await self.dh.swiss_add_player(swiss_event['_id'], user_id, username, elo, ranked=self.tm.is_ranked)

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

    async def on_team_register(self, team_id: str, team_doc: dict) -> None:
        """Register the team as a single swiss player entry using the team name."""
        swiss_event = await self.dh.get_swiss_event_by_tournament(self.tm.tournament['_id'])
        if swiss_event:
            team_name = team_doc.get('name', str(team_id))
            await self.dh.swiss_add_player(swiss_event['_id'], team_id, team_name, 1200, ranked=False)
        await self.dh.register_team(self.tm.tournament['_id'], team_id, None)

        tournament = await self.tm.get_tournament()
        if tournament['state'] == 'active':
            await self.manager.on_player_joined()

    async def on_team_unregister(self, team_id: str) -> None:
        """Mark the team entry as dropped in the swiss event."""
        swiss_event = await self.dh.get_swiss_event_by_tournament(self.tm.tournament['_id'])
        if swiss_event:
            await self.dh.swiss_drop_player(swiss_event['_id'], team_id)
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

        # ── Staggered start bonus ─────────────────────────────────────────────
        tournament = await self.tm.get_tournament()
        config = tournament.get('config', {})

        if config.get('staggered_start'):
            swiss_event = await self.dh.get_swiss_event_by_tournament(tournament['_id'])
            if swiss_event:
                entrant_ids = list(tournament.get('entrants', {}).keys())
                import math
                threshold = math.ceil(len(entrant_ids) / 2)
                top_players = [int(did) for did in entrant_ids[:threshold]]

                existing = set(swiss_event.get('players', {}).keys())
                eligible = [did for did in top_players if str(did) in existing]

                if eligible:
                    await self.dh.swiss_apply_staggered_bonus(swiss_event['_id'], eligible)
                    self.tm.logger.info(
                        'SWISS',
                        f'Staggered start: +1 bonus to top {len(eligible)} of {len(entrant_ids)} players'
                    )

    async def on_result(self, result: dict, lobby) -> None:
        tournament = await self.tm.get_tournament()
        swiss_event = await self.dh.get_swiss_event_by_tournament(tournament['_id'])

        if not swiss_event:
            return

        await self.dh.swiss_record_result(
            swiss_event['_id'],
            result['match_id'],
            result['winner_id'],
            result['loser_id'],
            result.get('is_dq', False),
        )

        self.tm.logger.match_result(result['match_id'], result['winner_id'], result['loser_id'], result.get('is_dq', False))

        if self.tm.is_ranked and not result['is_dq']:
            self.pending_results.append(result)

        await self.manager.check_round_complete()

    async def flush_pending_results(self) -> None:
        """
        Report all pending match results to UCH Ranked.
        Protected by a lock to prevent double-flush from concurrent
        check_round_complete calls. Marks each match as flushed in the DB
        so bot restarts don't double-report.
        """
        async with self._get_flush_lock():
            if not self.pending_results:
                return

            to_flush = list(self.pending_results)
            self.pending_results.clear()

            swiss_event = await self.dh.get_swiss_event_by_tournament(self.tm.tournament['_id'])
            if not swiss_event:
                return

            for result in to_flush:
                await self.tm.report_result_to_ranked_api(
                    result['winner_id'], result['loser_id']
                )
                match_id = result.get('match_id')
                if match_id is not None:
                    await self.dh.swiss_mark_match_flushed(
                        swiss_event['_id'], match_id
                    )

    async def on_tournament_end(self) -> None:
        """Flush any remaining results then post final standings."""
        await self.flush_pending_results()
        if not self.tm.debug:
            await self.tm.post_final_results()

    async def on_tournament_delete(self):
        tournament = await self.tm.get_tournament()
        await self.dh.delete_swiss_event_by_tournament(tournament['_id'])

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
        round_ready = (
            tournament.get('state') == 'active'
            and active_matches == 0
            and players_remaining > 1
            and swiss_event.get('current_round', 0) < swiss_event.get('round_limit', 8)
        )
        return {
            'current_round':     current_round,
            'round_limit':       round_limit,
            'active_matches':    active_matches,
            'players_remaining': players_remaining,
            'round_ready':       round_ready,
            'final_round_active': final_round_active,
        }

    async def on_lobby_reopen(self, match_lobby, lobby_db):
        """Undo the swiss result so the match can be replayed."""
        swiss_event = await self.dh.get_swiss_event_by_tournament(self.tm.tournament['_id'])
        if not swiss_event:
            raise ValueError('Swiss event not found')

        # Find which round this match belongs to
        match_doc = next(
            (m for m in swiss_event.get('matches', [])
            if m['match_id'] == match_lobby.match_id),
            None,
        )
        if not match_doc:
            raise ValueError('Match not found in swiss event')

        # Block reopen if the next round has already started
        match_round = match_doc.get('round_number', 0)
        current_round = swiss_event.get('current_round', 0)
        if match_round < current_round:
            raise ValueError(
                f'Cannot reopen a match from round {match_round} — round {current_round} has already started'
            )

        # Undo the recorded result (reverses wins/losses/points, restores active_match_id)
        await self.dh.swiss_unrecord_result(swiss_event['_id'], match_lobby.match_id)

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

    @property
    def allows_late_registration(self) -> bool:
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
                    ranked=self.tm.is_ranked,
                )