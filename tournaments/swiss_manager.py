import asyncio
import random
import discord

from tournaments.match_lobby import MatchLobby
from tournaments.swiss_pairing import pair_players, select_bye_candidate
from utils.messages import get_mentions

BYE_WAIT_SECONDS = 300  # 5 minutes


class SwissManager:
    """
    Handles all match calling logic for swiss format tournaments.
    Works alongside TournamentManager — TM handles Discord/DB setup,
    SwissManager handles the continuous pairing loop.
    """

    def __init__(self, tournament_manager):
        self.tm = tournament_manager
        self.bot = tournament_manager.bot
        self.dh = tournament_manager.bot.dh
        self.guild = tournament_manager.guild
        self.bye_task = None
        self.running = False

    # ─── Start ────────────────────────────────────────────────────────────────

    async def start(self):
        """Called when the tournament transitions to active state."""
        self.running = True
        swiss_event = await self.dh.get_swiss_event_by_tournament(self.tm.tournament['_id'])
        await self.dh.update_swiss_state(swiss_event['_id'], 'active')
        await self.run_pairing_cycle()

    # ─── Main pairing cycle ───────────────────────────────────────────────────

    async def run_pairing_cycle(self):
        """
        Pairs all available players and calls their matches.
        Called on tournament start and when the TO presses Start Next Round.
        """
        if not self.running:
            return

        swiss_event = await self.dh.get_swiss_event_by_tournament(self.tm.tournament['_id'])

        if await self.dh.swiss_is_event_complete(swiss_event['_id']):
            await self.end_event()
            return

        available = await self.dh.swiss_get_available_players(swiss_event['_id'])

        if len(available) < 2:
            if len(available) == 1 and self.bye_task is None:
                await self.start_bye_wait(available[0], swiss_event)
            return

        # Delete channels from previous round before creating new ones
        await self.close_previous_round_channels(swiss_event['_id'])

        # Increment the round counter — new round is now current
        current_round = await self.dh.swiss_increment_round(swiss_event['_id'])

        # Re-fetch after increment
        swiss_event = await self.dh.get_swiss_event_by_tournament(self.tm.tournament['_id'])

        await self.randomize_stagelist()

        pairs, unpaired = pair_players(available)

        for player_1, player_2 in pairs:
            await self.call_match(player_1, player_2, swiss_event, current_round)

        if unpaired:
            candidate = select_bye_candidate(unpaired)
            if candidate and self.bye_task is None:
                await self.start_bye_wait(candidate, swiss_event)

        # In debug mode all matches resolve instantly so check round complete now
        if self.tm.debug:
            await self.check_round_complete()

    # ─── Channel cleanup ─────────────────────────────────────────────────────

    async def close_previous_round_channels(self, event_id):
        for match_id in list(self.tm.lobbies.keys()):
            lobby = self.tm.lobbies[match_id]
            if lobby.channel is not None:
                try:
                    await lobby.channel.delete()
                    lobby.channel = None
                except discord.NotFound:
                    lobby.channel = None
                except Exception as e:
                    print(f"Error deleting swiss lobby channel {match_id}: {e}")

    # ─── Check if round is complete ───────────────────────────────────────────

    async def check_round_complete(self):
        swiss_event = await self.dh.get_swiss_event_by_tournament(self.tm.tournament['_id'])

        # Don't do anything if no rounds have started yet
        if swiss_event.get('current_round', 0) == 0:
            return

        for player in swiss_event['players'].values():
            if player.get('active_match_id') is not None:
                return

        if await self.dh.swiss_is_event_complete(swiss_event['_id']):
            await self.end_event()
            return

        await self.post_round_complete(swiss_event)

    async def post_round_complete(self, swiss_event):
        """Post a standings summary to match-calling and enable the Next Round button."""
        event_update_channel = await self.tm.get_channel('event-updates')
        if event_update_channel:
            standings = await self.dh.swiss_get_standings(swiss_event['_id'])
            top_players = standings[:5]
            standings_text = "\n".join(
                f"{i+1}. {p['username']} — {p['points']}pts ({p['wins']}W-{p['losses']}L)"
                for i, p in enumerate(top_players)
            )
            if len(standings) > 5:
                standings_text += f"\n*...and {len(standings) - 5} more*"

            embed = discord.Embed(
                title=f"Round {swiss_event.get('current_round', '?')} Complete",
                description=f"**Current Standings (Top 5):**\n{standings_text}",
                color=discord.Color.blue()
            )
            await event_update_channel.send(embed=embed)

        await self.tm.tc.bc.enable_next_round_button()

    # ─── Match calling ────────────────────────────────────────────────────────

    async def call_match(self, player_1, player_2, swiss_event, current_round):
        tournament = await self.tm.get_tournament()

        match_id = await self.dh.swiss_next_match_id(
            swiss_event['_id'],
            str(tournament['_id'])
        )

        await self.dh.swiss_create_match(
            swiss_event['_id'],
            match_id,
            player_1['discord_id'],
            player_2['discord_id'],
            current_round,
        )

        lobby_name = f"Round {current_round}-{player_1['username']}-vs-{player_2['username']}"

        match_lobby = await MatchLobby.create(
            tournament_id=tournament['_id'],
            match_id=match_id,
            lobby_name=lobby_name,
            prereq_matches=[],
            players=[player_1['discord_id'], player_2['discord_id']],
            stages=tournament['stagelist'],
            num_winners=1,
            tournament_manager=self.tm,
            datahandler=self.dh,
            guild=self.guild,
            bracket=None,
        )
        self.tm.lobbies[match_id] = match_lobby
        await match_lobby.initialize_match()

    # ─── Bye logic ────────────────────────────────────────────────────────────

    async def start_bye_wait(self, candidate: dict, swiss_event: dict):
        """Start a 5-minute wait before awarding a bye to the candidate."""
        await self.dh.swiss_set_bye_queue(swiss_event['_id'], candidate['discord_id'])

        match_call_channel = await self.tm.get_channel('match-calling')
        if match_call_channel:
            mention = f"<@{candidate['discord_id']}>"
            await match_call_channel.send(
                f"{mention} You currently have no opponent. "
                f"If no one becomes available in 5 minutes, you will receive a bye."
            )

        self.bye_task = asyncio.create_task(
            self._bye_timer(candidate['discord_id'], swiss_event['_id'])
        )

    async def _bye_timer(self, discord_id: int, event_id):
        """Wait then award the bye if the player is still in the queue."""
        try:
            await asyncio.sleep(BYE_WAIT_SECONDS)
        except asyncio.CancelledError:
            return

        event = await self.dh.get_swiss_event(event_id)
        if event.get('bye_queue') == discord_id:
            await self.dh.swiss_award_bye(event_id, discord_id)
            self.bye_task = None

            match_call_channel = await self.tm.get_channel('match-calling')
            if match_call_channel:
                mention = f"<@{discord_id}>"
                await match_call_channel.send(
                    f"{mention} No opponent was found. You have been awarded a bye (+1 point)."
                )

            await self.check_round_complete()

    async def cancel_bye_wait(self, event_id):
        """Cancel a pending bye wait."""
        if self.bye_task and not self.bye_task.done():
            self.bye_task.cancel()
            self.bye_task = None
        await self.dh.swiss_set_bye_queue(event_id, None)

    # ─── Called after a match finishes ───────────────────────────────────────

    async def on_match_complete(self, match_id: int, winner_id: int, loser_id: int):
        """Called by TournamentManager after a swiss match result is recorded."""
        await self.check_round_complete()

    # ─── Called when a player joins during active state ───────────────────────

    async def on_player_joined(self):
        """
        Called when a player registers during an active swiss event.
        Only triggers pairing if no matches are currently active (between rounds).
        """
        swiss_event = await self.dh.get_swiss_event_by_tournament(self.tm.tournament['_id'])

        if swiss_event.get('bye_queue') is not None:
            await self.cancel_bye_wait(swiss_event['_id'])

        for player in swiss_event['players'].values():
            if player.get('active_match_id') is not None:
                return

        await self.run_pairing_cycle()

    # ─── Called when a player drops ───────────────────────────────────────────

    async def on_player_dropped(self):
        swiss_event = await self.dh.get_swiss_event_by_tournament(self.tm.tournament['_id'])
        # Only check round complete if a round is actually in progress
        if swiss_event.get('current_round', 0) > 0:
            await self.check_round_complete()

    # ─── End event ────────────────────────────────────────────────────────────

    async def end_event(self):
        """
        All rounds complete. Clean up channels, mark the swiss event finished,
        then prompt the TO to end the tournament via the existing End Tournament button.
        """
        self.running = False

        swiss_event = await self.dh.get_swiss_event_by_tournament(self.tm.tournament['_id'])

        # Clean up any remaining channels from the final round
        if not self.tm.debug:
            for match_id in list(self.tm.lobbies.keys()):
                lobby = self.tm.lobbies[match_id]
                if lobby.channel is not None:
                    try:
                        await lobby.channel.delete()
                        lobby.channel = None
                    except discord.NotFound:
                        pass

        await self.dh.update_swiss_state(swiss_event['_id'], 'finished')

        # Post final standings to match-calling
        match_call_channel = await self.tm.get_channel('match-calling')
        if match_call_channel:
            standings = await self.dh.swiss_get_standings(swiss_event['_id'])
            standings_text = "\n".join(
                f"{i+1}. {p['username']} — {p['points']}pts ({p['wins']}W-{p['losses']}L)"
                for i, p in enumerate(standings)
            )
            embed = discord.Embed(
                title="All Rounds Complete — Final Standings",
                description=standings_text,
                color=discord.Color.gold()
            )
            await match_call_channel.send(embed=embed)

        # Prompt the TO to confirm ending — posts the End Tournament button to bot-control
        await self.tm.prompt_end_tournament()

    async def randomize_stagelist(self):
        """Replace the tournament stagelist with a fresh random set and regenerate the banner."""
        from bson import ObjectId
        DEFAULT_STAGE_NUMBER = 5

        tournament = await self.tm.get_tournament()

        # Clear existing stagelist
        await self.dh.tournament_collection.update_one(
            {'_id': ObjectId(tournament['_id'])},
            {'$set': {'stagelist': []}}
        )

        # Fetch and store new random stages
        stages = await self.dh.get_random_stages(DEFAULT_STAGE_NUMBER)
        stage_codes = [stage['code'] for stage in stages]
        await self.dh.add_stages_to_tournament(tournament['_id'], stage_codes)

        # Regenerate the banner
        self.tm.banner_filepath = await self.tm.tc.generate_banner()

        # Update the stagelist channel
        await self.tm.tc.refresh_stagelist()