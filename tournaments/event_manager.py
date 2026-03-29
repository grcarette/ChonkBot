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

        return doc

    async def transition_to_next_phase(self):
        """
        Called when the active phase finishes.

        For Swiss Filter: reads Swiss standings, splits players into brackets,
        creates bracket-phase tournaments, and activates them.
        """
        current_idx = self.active_phase_index
        phases = self.event.get('phases', [])
        current_phase = phases[current_idx]

        if current_phase['state'] != 'finished':
            raise ValueError(
                f"Cannot transition: phase {current_idx} is {current_phase['state']}, not finished"
            )

        # Find next phases that source from the current one
        next_phases = [
            (i, p) for i, p in enumerate(phases)
            if p.get('player_source', {}).get('phase_index') == current_idx
            and p['state'] == 'waiting'
        ]

        if not next_phases:
            await self._finish_event()
            return

        # Get standings from the finished phase
        standings = await self._get_phase_standings(current_idx)

        # Distribute players to next phases
        for phase_idx, phase_def in next_phases:
            player_ids = self._select_players_for_phase(standings, phase_def)
            await self._populate_and_start_phase(phase_idx, player_ids)

        # Update active_phase to the first of the new phases
        first_active_idx = next_phases[0][0]
        await self.bot.dh.edit_tournament_config(
            self.event['_id'],
            active_phase=first_active_idx,
        )

        self.logger.info('PHASE', f'Transitioned from phase {current_idx} to bracket phases')

    def _select_players_for_phase(self, standings: list, phase_def: dict) -> list[str]:
        """Given Swiss standings, select which players go into this bracket phase."""
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
                # "remaining" — everyone not claimed by top/middle
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

        # Register players into the phase
        for discord_id in player_ids:
            user = await self.bot.dh.get_user(user_id=int(discord_id))
            await tm.format.on_player_register(int(discord_id), user)

        # Update phase state
        await self._update_phase_state(phase_index, 'active')

        # Start the format
        await tm.format.on_tournament_start()

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
