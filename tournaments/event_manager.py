import discord

from formats import make_format
from tournaments.tournament_manager import TournamentManager
from utils.event_logger import EventLogger


def _default_label(fmt: str) -> str:
    return {
        'swiss': 'Swiss Rounds',
        'single elimination': 'Single Elimination',
        'double elimination': 'Double Elimination',
        'swiss filter': 'Swiss Rounds',
    }.get(fmt, fmt.title())


class EventManager:
    """
    Manages a multi-phase event.

    Owns: registration, check-in, config, Discord channels, phase lifecycle.
    Delegates: match calling, lobbies, format-specific logic → TournamentManager per phase.
    """

    def __init__(self, bot, event_doc):
        self.bot = bot
        self.event = event_doc
        self.guild = bot.guild
        self.debug = event_doc.get('debug', False)
        self.logger = EventLogger(event_doc['name'])

        # One TournamentManager per phase
        self.phase_managers: dict[int, TournamentManager] = {}

    @property
    def active_phase_index(self) -> int:
        return self.event.get('active_phase', 0)

    @property
    def active_phase(self) -> dict:
        phases = self.event.get('phases', [])
        idx = self.active_phase_index
        if idx < len(phases):
            return phases[idx]
        return {}

    @property
    def active_tm(self) -> TournamentManager | None:
        return self.phase_managers.get(self.active_phase_index)

    @property
    def is_multi_phase(self) -> bool:
        return len(self.event.get('phases', [])) > 1

    def get_phase_config(self, phase_index: int, key: str):
        """Resolve a config value: phase override wins, else event-level."""
        phases = self.event.get('phases', [])
        if phase_index >= len(phases):
            return self.event.get('config', {}).get(key)
        phase = phases[phase_index]
        overrides = phase.get('config_overrides', {})
        if key in overrides:
            return overrides[key]
        return self.event.get('config', {}).get(key)

    def get_phase_stagelist(self, phase_index: int) -> list:
        """Resolve stagelist: phase override wins, else event-level."""
        phases = self.event.get('phases', [])
        if phase_index >= len(phases):
            return self.event.get('stagelist', [])
        phase = phases[phase_index]
        overrides = phase.get('config_overrides', {})
        if 'stagelist' in overrides:
            return overrides['stagelist']
        return self.event.get('stagelist', [])

    async def initialize(self):
        """Called on bot startup for active events, and after creation."""
        for i, phase in enumerate(self.event.get('phases', [])):
            if phase['state'] in ('active', 'finished'):
                tm = await self._create_phase_tm(i)
                self.phase_managers[i] = tm

    async def _create_phase_tm(self, phase_index: int) -> TournamentManager:
        """Create a TournamentManager for a specific phase."""
        phase_doc = self._build_phase_tournament_doc(phase_index)
        tm = TournamentManager(self.bot, phase_doc)
        tm.format = make_format(tm)
        await tm.format.on_initialize()
        return tm

    def _build_phase_tournament_doc(self, phase_index: int) -> dict:
        """
        Build a dict that looks like a tournament document, combining
        event-level fields with phase-specific overrides.

        TournamentManager reads from this — it doesn't know about phases.
        """
        phases = self.event.get('phases', [])
        phase = phases[phase_index]
        event = self.event

        doc = {
            '_id': phase.get('tournament_id', event['_id']),
            'name': event['name'],
            'date': event.get('date', ''),
            'organizers': event['organizers'],
            'category_id': event.get('category_id'),
            'debug': event.get('debug', False),
            'format': phase['type'],
            'state': phase['state'],
            'entrants': {},         # populated during phase transition
            'checked_in': [],
            'dqs': event.get('dqs', []),
            'registration_open': False,
            'stagelist': self.get_phase_stagelist(phase_index),
            'config': {
                **event.get('config', {}),
                **phase.get('config_overrides', {}),
            },
        }

        if phase['type'] in ('swiss', 'swiss filter'):
            doc['round_limit'] = phase.get('round_limit', 8)

        # Bracket label prefix for lobby channel naming (e.g. 'pro', 'int', 'beg')
        doc['lobby_prefix'] = phase.get('label', '').lower()[:3]

        return doc

    # ── Phase lifecycle ────────────────────────────────────────────────────────

    async def on_phase_finished(self, phase_index: int):
        """Called when a phase's format signals completion."""
        phase = self.event['phases'][phase_index]
        await self._update_phase_state(phase_index, 'finished')
        self.logger.info('PHASE', f'Phase {phase_index} ({phase["label"]}) finished')

        # Refresh event doc to get latest states
        self.event = await self.bot.dh.get_tournament_by_id(self.event['_id'])

        # Check if there are waiting phases that depend on this one
        has_waiting = any(
            p.get('player_source', {}).get('phase_index') == phase_index
            and p['state'] == 'waiting'
            for p in self.event['phases']
        )

        if has_waiting:
            await self._post_swiss_standings(phase_index)
            self.logger.info('PHASE', 'Swiss phase complete — waiting for TO to start brackets')
        else:
            all_done = all(p['state'] == 'finished' for p in self.event['phases'])
            if all_done:
                await self._finish_event()

    async def _post_swiss_standings(self, phase_index: int):
        """Post final Swiss standings to event-info, prompting TO to start brackets."""
        tm = self.phase_managers.get(phase_index)
        if not tm:
            return
        try:
            channel = await tm.get_channel('event-info')
            if not channel:
                return
            swiss_event = await self.bot.dh.get_swiss_event_by_tournament(
                self.event['phases'][phase_index].get('tournament_id', self.event['_id'])
            )
            if not swiss_event:
                return
            standings = await self.bot.dh.swiss_get_standings(swiss_event['_id'])
            lines = []
            for i, p in enumerate(standings[:20], 1):
                user = await self.bot.dh.get_user(user_id=int(p['discord_id']))
                name = user['name'] if user else str(p['discord_id'])
                wins = p.get('wins', 0)
                losses = p.get('losses', 0)
                lines.append(f'{i}. {name} ({wins}-{losses})')
            embed = discord.Embed(
                title=f"{self.event['name']} — Swiss Standings",
                description='\n'.join(lines) or 'No results',
                color=discord.Color.blurple()
            )
            embed.set_footer(text='Use the dashboard to start the bracket phase.')
            await channel.send(embed=embed)
        except Exception as e:
            self.logger.info('PHASE', f'Failed to post Swiss standings: {e}')

    # ── Swiss Filter: wins-based bracket distribution ─────────────────────────

    async def _distribute_players_to_brackets(self) -> dict[int, list[str]]:
        """
        Read Swiss standings and distribute players into 3 brackets
        based on win count. Floated players go to Pro regardless of record.
        """
        swiss_phase = self.event['phases'][0]
        swiss_event = await self.bot.dh.get_swiss_event_by_tournament(
            swiss_phase.get('tournament_id', self.event['_id'])
        )
        if not swiss_event:
            raise ValueError('Swiss event not found')

        standings = await self.bot.dh.swiss_get_standings(swiss_event['_id'])
        config = self.event.get('config', {})

        floating_enabled = config.get('top_seed_floating', False)
        floating_count = config.get('top_seed_floating_count', 0) if floating_enabled else 0

        seeds = self.event.get('seeds', {})
        if seeds:
            standings_by_seed = sorted(
                standings, key=lambda p: seeds.get(str(p['discord_id']), 9999)
            )
        else:
            standings_by_seed = standings

        floated_ids: set[str] = set()
        if floating_count > 0:
            non_dropped = [p for p in standings_by_seed if not p.get('dropped')]
            floated_ids = {str(p['discord_id']) for p in non_dropped[:floating_count]}

        pro_players: list[str] = []
        intermediate_players: list[str] = []
        beginner_players: list[str] = []

        for player in standings:
            did = str(player['discord_id'])
            if player.get('dropped'):
                continue
            if did in floated_ids:
                pro_players.append(did)
                continue
            wins = player.get('wins', 0)
            if wins >= 3:
                pro_players.append(did)
            elif wins == 2:
                intermediate_players.append(did)
            else:
                beginner_players.append(did)

        return {
            1: pro_players,           # phase index 1 = Pro
            2: intermediate_players,  # phase index 2 = Intermediate
            3: beginner_players,      # phase index 3 = Beginner
        }

    async def _create_bracket_phase(self, phase_index: int, player_ids: list[str]):
        """Create a Challonge bracket and register players for one bracket phase."""
        phase = self.event['phases'][phase_index]
        event = self.event

        if not player_ids:
            await self._update_phase_state(phase_index, 'finished')
            self.logger.info('PHASE', f'{phase["label"]}: no players, skipping')
            return

        from tournaments.challonge_handler import ChallongeHandler
        ch = ChallongeHandler()

        bracket_name = f"{event['name']} - {phase['label']}"
        raw_slug = f"{event['name'].lower().replace(' ', '-')}-{phase['label'].lower().replace(' ', '-')}"
        url_slug = ''.join(c for c in raw_slug if c.isalnum() or c == '-')[:60]

        challonge_tournament = await ch.create_tournament(
            name=bracket_name,
            tournament_type='double elimination',
            url=url_slug,
        )

        challonge_url = challonge_tournament['url']
        challonge_id = challonge_tournament['id']

        entrant_map: dict[str, int] = {}
        for discord_id in player_ids:
            user = await self.bot.dh.get_user(user_id=int(discord_id))
            name = user['name'] if user else f'Player {discord_id}'
            participant_id = await ch.register_player(challonge_url, name)
            entrant_map[discord_id] = participant_id

        await ch.start_tournament(challonge_id)

        await self.bot.dh.tournament_collection.update_one(
            {'_id': event['_id']},
            {'$set': {
                f'phases.{phase_index}.state': 'active',
                f'phases.{phase_index}.challonge_data': {
                    'url': challonge_url,
                    'id': challonge_id,
                },
                f'phases.{phase_index}.entrants': entrant_map,
            }}
        )

        phase_doc = self._build_phase_tournament_doc(phase_index)
        phase_doc['entrants'] = entrant_map
        phase_doc['challonge_data'] = {'url': challonge_url, 'id': challonge_id}
        phase_doc['state'] = 'active'

        tm = TournamentManager(self.bot, phase_doc)
        tm.format = make_format(tm)
        await tm.format.on_initialize()
        self.phase_managers[phase_index] = tm

        self.bot.th.tournaments[phase_doc['_id']] = tm

        self.logger.info('PHASE',
            f'{phase["label"]}: created with {len(player_ids)} players — {challonge_url}')

    async def transition_to_brackets(self):
        """TO-triggered transition from Swiss phase to the three bracket phases."""
        swiss_phase = self.event['phases'][0]
        if swiss_phase['state'] != 'finished':
            raise ValueError('Swiss phase is not finished yet')

        distribution = await self._distribute_players_to_brackets()

        self.logger.info('PHASE',
            f'Distributing players: Pro={len(distribution[1])}, '
            f'Intermediate={len(distribution[2])}, '
            f'Beginner={len(distribution[3])}')

        for phase_index, player_ids in distribution.items():
            await self._create_bracket_phase(phase_index, player_ids)

        await self.bot.dh.tournament_collection.update_one(
            {'_id': self.event['_id']},
            {'$set': {'active_phase': 1}}
        )

        self.event = await self.bot.dh.get_tournament_by_id(self.event['_id'])

        await self._post_bracket_links()

        for phase_index in distribution:
            tm = self.phase_managers.get(phase_index)
            if tm and tm.format:
                await tm.format.on_tournament_start()
                await tm.start_tournament_loop()

    async def _post_bracket_links(self):
        """Post bracket links for all active bracket phases to event-info."""
        tm = self.active_tm
        if not tm:
            return
        channel = await tm.get_channel('event-info')
        if not channel:
            return

        from utils.get_bracket_link import get_bracket_link

        description = '**Bracket Phase**\n\n'
        for phase in self.event['phases'][1:]:
            if phase.get('challonge_data'):
                url = await get_bracket_link(phase['challonge_data']['url'])
                count = len(phase.get('entrants', {}))
                description += f"**{phase['label']}** — {count} players\n{url}\n\n"

        embed = discord.Embed(
            title=f"{self.event['name']} — Brackets",
            description=description,
            color=discord.Color.green()
        )
        await channel.send(embed=embed)

    # ── Generic (non-swiss-filter) phase transition ───────────────────────────

    async def transition_to_next_phase(self):
        """
        Called for non-swiss-filter formats when the active phase finishes.
        Reads standings, splits players by placement, and activates next phases.
        """
        current_idx = self.active_phase_index
        phases = self.event.get('phases', [])
        current_phase = phases[current_idx]

        if current_phase['state'] != 'finished':
            raise ValueError(
                f"Cannot transition: phase {current_idx} is {current_phase['state']}, not finished"
            )

        next_phases = [
            (i, p) for i, p in enumerate(phases)
            if p.get('player_source', {}).get('phase_index') == current_idx
            and p['state'] == 'waiting'
        ]

        if not next_phases:
            await self._finish_event()
            return

        standings = await self._get_phase_standings(current_idx)

        for phase_idx, phase_def in next_phases:
            player_ids = self._select_players_for_phase(standings, phase_def)
            await self._populate_and_start_phase(phase_idx, player_ids)

        first_active_idx = next_phases[0][0]
        await self.bot.dh.edit_tournament_config(
            self.event['_id'],
            active_phase=first_active_idx,
        )

        self.logger.info('PHASE', f'Transitioned from phase {current_idx} to bracket phases')

    def _select_players_for_phase(self, standings: list, phase_def: dict) -> list[str]:
        """Given standings, select which players go into this bracket phase."""
        source = phase_def.get('player_source', {})
        placement = source.get('placement', 'all')
        count = source.get('count')

        discord_ids = [p['discord_id'] for p in standings if not p.get('dropped')]

        if placement == 'top':
            return discord_ids[:count]
        elif placement == 'middle':
            top_count = count  # assumes top bracket has same count
            return discord_ids[top_count:top_count + count]
        elif placement == 'bottom':
            if count:
                return discord_ids[-count:]
            else:
                phases = self.event.get('phases', [])
                top_phases = [
                    p for p in phases
                    if p.get('player_source', {}).get('placement') in ('top', 'middle')
                ]
                claimed = sum(
                    p.get('player_source', {}).get('count', 0) or 0
                    for p in top_phases
                )
                return discord_ids[claimed:]
        else:
            return discord_ids

    async def _get_phase_standings(self, phase_index: int) -> list:
        """Get final standings from a completed phase."""
        tm = self.phase_managers.get(phase_index)
        if not tm:
            return []

        phase = self.event['phases'][phase_index]
        if phase['type'] in ('swiss', 'swiss filter'):
            swiss_event = await self.bot.dh.get_swiss_event_by_tournament(
                phase.get('tournament_id', self.event['_id'])
            )
            if swiss_event:
                return await self.bot.dh.swiss_get_standings(swiss_event['_id'])
        return []

    async def _populate_and_start_phase(self, phase_index: int, player_ids: list[str]):
        """Create and start a bracket phase with the given players."""
        tm = await self._create_phase_tm(phase_index)
        self.phase_managers[phase_index] = tm

        for discord_id in player_ids:
            user = await self.bot.dh.get_user(user_id=int(discord_id))
            await tm.format.on_player_register(int(discord_id), user)

        await self._update_phase_state(phase_index, 'active')
        await tm.format.on_tournament_start()

    # ── Shared helpers ────────────────────────────────────────────────────────

    async def _update_phase_state(self, phase_index: int, state: str):
        """Update a single phase's state in the event document."""
        await self.bot.dh.tournament_collection.update_one(
            {'_id': self.event['_id']},
            {'$set': {f'phases.{phase_index}.state': state}}
        )

    async def _finish_event(self):
        """All phases complete — transition event to finished."""
        await self.bot.dh.update_tournament_state(self.event['_id'], 'finished')
        self.logger.info('STATE', 'Event finished — all phases complete')
