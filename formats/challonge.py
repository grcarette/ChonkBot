# formats/challonge.py

import asyncio

from formats.base import BaseFormat
from tournaments.challonge_handler import ChallongeHandler
from tournaments.match_service import MatchService
from tournaments.match_lobby import MatchLobby


class ChallongeFormat(BaseFormat):
    """
    Format implementation for Challonge-backed brackets.
    Handles both Double Elimination and Single Elimination.

    Owns:
    - Challonge bracket creation and lifecycle
    - Participant registration / removal
    - Match result reporting to Challonge
    - Bracket finalization and deletion
    - Bracket reset
    - Pending match cache and match calling logic
    - autocall, hold_when_ready, called_match_ids state
    """

    def __init__(self, tm):
        super().__init__(tm)
        self.ch = ChallongeHandler()
        self.called_match_ids: set[int] = set()
        self.autocall_matches: bool = False
        self.hold_when_ready: set[int] = set()
        self._pending_cache: list[dict] | None = None

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    async def on_initialize(self) -> None:
        """
        Create the Challonge bracket if it doesn't exist yet,
        or rehydrate the ChallongeHandler with the stored URL if it does.

        Check the in-memory tournament doc first: _create_bracket_phase sets
        challonge_data on the phase_doc before calling on_initialize, but the
        phase TM's _id may equal the parent event's _id, so get_tournament()
        would re-fetch the parent event (format='swiss filter') and overwrite
        the phase_doc — causing Challonge to reject 'swiss filter' as a type.
        """
        if 'challonge_data' in self.tm.tournament:
            self.ch = ChallongeHandler(self.tm.tournament['challonge_data']['url'])
            return
        tournament = await self.tm.get_tournament()
        if 'challonge_data' in tournament:
            self.ch = ChallongeHandler(tournament['challonge_data']['url'])
        else:
            challonge_tournament = await self.ch.create_tournament(
                name=tournament['name'],
                tournament_type=tournament['format'],
                start_time=tournament['date'],
            )
            url          = challonge_tournament['url']
            tournament_id = challonge_tournament['id']
            await self.dh.add_challonge_to_tournament(tournament['name'], url, tournament_id)
            self.ch = ChallongeHandler(url)

    async def on_player_register(self, user_id: int, user: dict) -> None:
        """Register the player as a Challonge participant and store their participant ID."""
        tournament = await self.tm.get_tournament()
        if self.tm.debug:
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

    async def on_team_register(self, team_id: str, team_doc: dict) -> None:
        """Register the team as a single Challonge participant using the team name."""
        tournament = await self.tm.get_tournament()
        participant_id = await self.ch.register_player(
            tournament['challonge_data']['url'], team_doc['name']
        )
        await self.dh.register_team(tournament['_id'], team_id, participant_id)

    async def on_team_unregister(self, team_id: str) -> None:
        """Destroy the Challonge participant for this team."""
        tournament = await self.tm.get_tournament()
        participant_id = tournament['entrants'].get(str(team_id))
        if participant_id is not None:
            await self.ch.unregister_player(
                tournament['challonge_data']['id'], participant_id
            )

    async def on_tournament_start(self) -> None:
        """Lock in the bracket seeding on Challonge."""
        tournament = await self.tm.get_tournament()
        await self.ch.start_tournament(tournament['challonge_data']['id'])

    async def on_result(self, result: dict, lobby) -> None:
        import time
        t0 = time.perf_counter()

        tournament = await self.tm.get_tournament()
        winner_user_id = str(result['winner_id'])

        if winner_user_id not in tournament['entrants']:
            winner_int = int(winner_user_id)
            closest = min(tournament['entrants'].keys(), key=lambda k: abs(int(k) - winner_int))
            if abs(int(closest) - winner_int) < 100:
                winner_user_id = closest
            else:
                raise ValueError(f"Could not resolve winner {winner_user_id} to any entrant.")

        challonge_winner_id = tournament['entrants'][winner_user_id]

        await self.ch.report_match(
            tournament['challonge_data']['url'],
            result['match_id'],
            challonge_winner_id,
            result['is_dq'],
        )
        print(f"[timing] challonge report_match: {time.perf_counter()-t0:.3f}s")

        status, _ = await asyncio.gather(
            self.ch.check_tournament_status(tournament['challonge_data']['id']),
            self.tm.close_prereqs(lobby),
        )
        print(f"[timing] status+close_prereqs parallel: {time.perf_counter()-t0:.3f}s")

        if status == 'awaiting_review':
            await self.tm.bot.dh.update_tournament_state(self.tm.tournament['_id'], 'finished')
            self.invalidate_pending_cache()
        else:
            self.invalidate_pending_cache()
            if self.autocall_matches:
                await self.call_matches()
            elif self.hold_when_ready:
                pending = await self.get_pending_matches()
                for match_data in pending:
                    if match_data['match_id'] in self.hold_when_ready:
                        await self.call_match(match_data, hold_match=True)
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

    async def on_reset_report(self, lobby: dict) -> None:
        """Reopen the match on Challonge so it can be re-reported."""
        tournament = await self.tm.get_tournament()
        await self.ch.reset_match(tournament['challonge_data']['id'], lobby['match_id'])

    # ─── Pending match cache ──────────────────────────────────────────────────

    def invalidate_pending_cache(self):
        """Full invalidation — use when new matches may have become available."""
        self._pending_cache = None

    def _remove_from_pending_cache(self, match_id: int):
        """Partial invalidation — remove one match without discarding the whole cache."""
        if self._pending_cache is not None:
            self._pending_cache = [m for m in self._pending_cache if m['match_id'] != match_id]

    # ─── Match data parsing ───────────────────────────────────────────────────

    async def parse_match_data(self, match) -> dict | None:
        tournament = await self.tm.get_tournament()
        fmt = tournament['format']

        player_1_id = await self.tm.bot.dh.get_user_by_challonge(tournament['_id'], match['player1_id'])
        player_2_id = await self.tm.bot.dh.get_user_by_challonge(tournament['_id'], match['player2_id'])

        if player_1_id is None or player_2_id is None:
            return None

        round_number = match['round']
        if fmt == 'double elimination':
            bracket = 'Winners' if round_number > 0 else 'Losers'
        else:
            bracket = 'Singles'

        pre_reqs_raw = match.get('prerequisite_match_ids_csv', '')
        if not pre_reqs_raw:
            prereq_matches = []
        elif isinstance(pre_reqs_raw, float):
            prereq_matches = [int(pre_reqs_raw)]
        else:
            prereq_matches = [int(x) for x in str(pre_reqs_raw).split(',') if x.strip()]

        return {
            'match_id':       match['id'],
            'player_1_id':    player_1_id,
            'player_2_id':    player_2_id,
            'round':          round_number,
            'bracket':        bracket,
            'prereq_matches': prereq_matches,
        }

    async def get_players_from_match(self, match_data) -> tuple[dict, dict]:
        player_1_id = match_data['player_1_id']
        player_2_id = match_data['player_2_id']

        player_1 = await self.tm.bot.dh.get_user(user_id=player_1_id)
        player_2 = await self.tm.bot.dh.get_user(user_id=player_2_id)

        if self.tm.debug:
            if player_1 is None:
                player_1 = {'user_id': player_1_id, 'name': f'Debug User {player_1_id}'}
            if player_2 is None:
                player_2 = {'user_id': player_2_id, 'name': f'Debug User {player_2_id}'}

        if player_1 is None or player_2 is None:
            raise ValueError(
                f"[get_players_from_match] Could not find users: "
                f"p1={player_1_id} → {player_1}, p2={player_2_id} → {player_2}"
            )
        return player_1, player_2

    async def get_lobby_name(self, match_data) -> str:
        player_1, player_2 = await self.get_players_from_match(match_data)
        round_num = match_data['round']
        bracket   = match_data['bracket']
        if bracket == 'Winners':
            bracket_tag = 'w'
        elif bracket == 'Losers':
            bracket_tag = 'l'
        else:
            bracket_tag = 's'
        return f"{bracket_tag}r{round_num}-{player_1['name']} vs {player_2['name']}"

    # ─── Pending matches ──────────────────────────────────────────────────────

    async def get_pending_matches(self) -> list[dict]:
        if self._pending_cache is not None:
            return self._pending_cache

        tournament  = await self.tm.get_tournament()
        raw_matches = await self.ch.get_pending_matches(tournament['challonge_data']['url'])

        parsed = []
        for match in raw_matches:
            try:
                match_data = await self.parse_match_data(match)
            except Exception:
                continue
            if match_data is not None:
                parsed.append(match_data)

        candidate_ids = [m['match_id'] for m in parsed]
        existing_ids  = await self.tm.bot.dh.find_matches_bulk(candidate_ids)

        result = [
            m for m in parsed
            if m['match_id'] not in existing_ids
            and m['match_id'] not in self.called_match_ids
        ]

        self._pending_cache = result
        return result

    # ─── Match calling ────────────────────────────────────────────────────────

    def toggle_hold_when_ready(self, match_id: int) -> bool:
        if match_id in self.hold_when_ready:
            self.hold_when_ready.discard(match_id)
            return False
        else:
            self.hold_when_ready.add(match_id)
            return True

    async def call_match(self, match_data: dict, hold_match: bool = False) -> None:
        if match_data['match_id'] in self.called_match_ids:
            return
        if await self.tm.bot.dh.find_match(match_data['match_id']):
            self.called_match_ids.add(match_data['match_id'])
            self._remove_from_pending_cache(match_data['match_id'])
            return

        self.called_match_ids.add(match_data['match_id'])
        self._remove_from_pending_cache(match_data['match_id'])

        tournament = await self.tm.get_tournament()
        player_1, player_2 = await self.get_players_from_match(match_data)
        players    = [str(player_1['user_id']), str(player_2['user_id'])]
        lobby_name = await self.get_lobby_name(match_data)

        async def on_complete(result):
            await self.tm.report_match_from_result(result)

        service = MatchService(
            match_id=match_data['match_id'],
            players=players,
            stages=tournament['stagelist'],
            dh=self.tm.bot.dh,
            on_complete=on_complete,
        )

        async def _create_lobby_in_background():
            try:
                match_lobby = await MatchLobby.create(
                    tournament_id=tournament['_id'],
                    match_id=match_data['match_id'],
                    lobby_name=lobby_name,
                    prereq_matches=match_data['prereq_matches'],
                    players=players,
                    stages=tournament['stagelist'],
                    num_winners=1,
                    tournament_manager=self.tm,
                    datahandler=self.tm.bot.dh,
                    guild=self.tm.guild,
                    bracket=match_data['bracket'],
                    match_service=service,
                )
                self.tm.lobbies[match_data['match_id']] = match_lobby

                should_hold = hold_match or (match_data['match_id'] in self.hold_when_ready)
                print(f"[call_match] match {match_data['match_id']} hold_match={hold_match} "
                      f"in_hold_when_ready={match_data['match_id'] in self.hold_when_ready} "
                      f"should_hold={should_hold}")
                self.hold_when_ready.discard(match_data['match_id'])

                if str(player_1['user_id']) in tournament['dqs']:
                    await match_lobby.end_reporting(winner_id=player_2['user_id'], is_dq=True)
                elif str(player_2['user_id']) in tournament['dqs']:
                    await match_lobby.end_reporting(winner_id=player_1['user_id'], is_dq=True)
                else:
                    await match_lobby.initialize_match(should_hold)

            except Exception as e:
                print(f"[call_match] Background lobby creation failed for match "
                      f"{match_data['match_id']}: {e}")
                self.tm.lobbies.pop(match_data['match_id'], None)
                self.called_match_ids.discard(match_data['match_id'])

        asyncio.create_task(_create_lobby_in_background())

    async def call_matches(self) -> None:
        tournament  = await self.tm.get_tournament()
        raw_matches = await self.ch.get_pending_matches(tournament['challonge_data']['url'])
        print(f"[call_matches] {len(raw_matches)} pending matches from Challonge")
        for match in raw_matches:
            if self.tm.tournament_reset:
                return
            try:
                match_data = await self.parse_match_data(match)
            except Exception as e:
                print(f"[call_matches] Error parsing match {match.get('id')}: {e}")
                await self._alert_unresolvable_match(match, str(e))
                continue
            if match_data is None:
                await self._alert_unresolvable_match(match)
                continue
            print(f"[call_matches] match {match_data['match_id']} — "
                  f"in called_match_ids: {match_data['match_id'] in self.called_match_ids}, "
                  f"hold_when_ready: {match_data['match_id'] in self.hold_when_ready}")
            if match_data['match_id'] not in self.called_match_ids:
                should_hold = match_data['match_id'] in self.hold_when_ready
                print(f"[call_matches] calling match {match_data['match_id']} with hold={should_hold}")
                try:
                    await self.call_match(match_data, hold_match=should_hold)
                except Exception as e:
                    print(f"[call_matches] Failed to call match {match_data['match_id']}: {e}")
                    await self._alert_unresolvable_match(match, str(e))

    async def _alert_unresolvable_match(self, match, error: str = None) -> None:
        match_id = match.get('id', 'unknown')
        p1       = match.get('player1_id', '?')
        p2       = match.get('player2_id', '?')

        description = (
            f"Match **{match_id}** (Challonge players `{p1}` vs `{p2}`) "
            f"could not be resolved to Discord users and was skipped.\n\n"
            f"This usually means one or both players are not registered in the database. "
            f"Use `/call_match` to call this match manually once the issue is resolved."
        )
        if error:
            description += f"\n\n**Error:** `{error}`"

        embed = discord.Embed(
            title="⚠️ Unresolvable Match",
            description=description,
            color=discord.Color.orange()
        )
        try:
            channel = await self.tm.get_channel('bot-control')
            if channel:
                await channel.send(embed=embed)
        except Exception as e:
            print(f"[_alert_unresolvable_match] Failed to post alert: {e}")

    # ─── Properties ───────────────────────────────────────────────────────────

    async def get_dashboard_state(self) -> dict:
        return {
            'autocall_matches': getattr(self, 'autocall_matches', False),
        }

    @property
    def needs_match_call_refresh(self) -> bool:
        return True

    @property
    def supports_reset(self) -> bool:
        return True

    @property
    def shows_bracket_link(self) -> bool:
        return True

    @property
    def ranked_compatible(self) -> bool:
        return True