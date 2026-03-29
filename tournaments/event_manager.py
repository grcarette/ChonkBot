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

        # Carry over challonge_data and entrants so ChallongeFormat.on_initialize()
        # can rehydrate from the existing bracket instead of creating a new one.
        if phase.get('challonge_data'):
            doc['challonge_data'] = phase['challonge_data']
        if phase.get('entrants'):
            doc['entrants'] = phase['entrants']

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
                self.event['phases'][phase_index].get('tournament_id') or self.event['_id']
            )
            if not swiss_event:
                return
            standings = await self.bot.dh.swiss_get_standings(swiss_event['_id'])
            config = self.event.get('config', {})
            if config.get('top_seed_floating'):
                count = config.get('top_seed_floating_count', 0)
                seeds = self.event.get('seeds', {})
                if count > 0 and seeds:
                    sorted_ids = sorted(seeds.keys(), key=lambda k: seeds[k])
                    floated_ids = set(sorted_ids[:count])
                    standings = [p for p in standings if str(p['discord_id']) not in floated_ids]
            top_standings = standings[:20]
            user_map = await self.bot.dh.get_users_bulk([str(p['discord_id']) for p in top_standings])
            lines = []
            for i, p in enumerate(top_standings, 1):
                user = user_map.get(str(p['discord_id']))
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
            swiss_phase.get('tournament_id') or self.event['_id']
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

    async def sync_floated_players(self):
        """
        For swiss filter events: ensure the top-N seeds are registered in the
        Pro Challonge bracket and removed from the Swiss phase, and vice-versa
        for players who fall out of the top N.

        No-op if: floating is disabled, the Pro bracket shell doesn't exist yet,
        or the Swiss phase has already started.
        """
        print(f'[FLOAT] sync_floated_players() called for event {self.event["_id"]}')
        try:
            self.event = await self.bot.dh.get_tournament_by_id(self.event['_id'])

            config = self.event.get('config', {})
            floating_enabled = config.get('top_seed_floating')
            floating_count   = config.get('top_seed_floating_count', 0)
            print(f'[FLOAT] top_seed_floating={floating_enabled} count={floating_count}')
            if not floating_enabled or not floating_count:
                print('[FLOAT] floating disabled or count=0 — skipping')
                return

            phases = self.event.get('phases', [])
            print(f'[FLOAT] phases count={len(phases)}, states={[p.get("state") for p in phases]}')
            if len(phases) < 2:
                print('[FLOAT] fewer than 2 phases — skipping')
                return

            swiss_state = phases[0].get('state')
            if swiss_state in ('active', 'finished'):
                print(f'[FLOAT] Swiss phase already {swiss_state} — skipping')
                return

            pro_phase = phases[1]
            ch_data   = pro_phase.get('challonge_data')
            print(f'[FLOAT] pro_phase challonge_data={ch_data}')
            if not ch_data:
                print('[FLOAT] Pro bracket shell not created yet — skipping')
                return

            swiss_entrants = self.event.get('entrants') or {}
            pro_entrants   = pro_phase.get('entrants') or {}
            all_ids        = set(str(k) for k in swiss_entrants) | set(str(k) for k in pro_entrants)
            print(f'[FLOAT] swiss_entrants={list(swiss_entrants.keys())[:5]}... ({len(swiss_entrants)} total)')
            print(f'[FLOAT] pro_entrants={list(pro_entrants.keys())[:5]}... ({len(pro_entrants)} total)')
            print(f'[FLOAT] all_ids count={len(all_ids)}')

            if not all_ids:
                print('[FLOAT] no entrants at all — skipping')
                return

            seeds      = self.event.get('seeds') or {}
            sorted_ids = sorted(all_ids, key=lambda did: seeds.get(str(did), 9999))
            target_floated = set(sorted_ids[:floating_count])
            current_pro    = set(str(k) for k in pro_entrants)
            print(f'[FLOAT] seeds sample={dict(list(seeds.items())[:5])}')
            print(f'[FLOAT] sorted_ids (first {floating_count+3})={sorted_ids[:floating_count+3]}')
            print(f'[FLOAT] target_floated={target_floated}')
            print(f'[FLOAT] current_pro={current_pro}')

            to_add_to_pro      = target_floated - current_pro
            to_remove_from_pro = current_pro - target_floated
            print(f'[FLOAT] to_add_to_pro={to_add_to_pro}')
            print(f'[FLOAT] to_remove_from_pro={to_remove_from_pro}')

            if not to_add_to_pro and not to_remove_from_pro:
                print('[FLOAT] nothing to change')
                return

            from tournaments.challonge_handler import ChallongeHandler
            ch = ChallongeHandler()

            challonge_url = ch_data['url']
            challonge_id  = ch_data['id']

            for discord_id in sorted(to_add_to_pro, key=lambda did: seeds.get(str(did), 9999)):
                print(f'[FLOAT] adding {discord_id} to Pro bracket ({challonge_url})')
                try:
                    user = await self.bot.dh.get_user(user_id=int(discord_id))
                    name = user['name'] if user else f'Player {discord_id}'
                    participant_id = await ch.register_player(challonge_url, name)
                    print(f'[FLOAT] registered {discord_id} ({name}) as participant {participant_id}')
                    await self.bot.dh.tournament_collection.update_one(
                        {'_id': self.event['_id']},
                        {'$set': {f'phases.1.entrants.{discord_id}': participant_id}}
                    )
                    print(f'[FLOAT] {discord_id} added to Pro')
                except Exception as e:
                    import traceback
                    print(f'[FLOAT] ERROR adding {discord_id} to Pro: {e}')
                    traceback.print_exc()

            for discord_id in to_remove_from_pro:
                print(f'[FLOAT] removing {discord_id} from Pro bracket')
                try:
                    participant_id = pro_entrants.get(discord_id) or pro_entrants.get(int(discord_id))
                    if participant_id:
                        await ch.unregister_player(challonge_id, participant_id)
                        print(f'[FLOAT] unregistered {discord_id} (participant {participant_id}) from Challonge')
                    await self.bot.dh.tournament_collection.update_one(
                        {'_id': self.event['_id']},
                        {'$unset': {f'phases.1.entrants.{discord_id}': ''}}
                    )
                    print(f'[FLOAT] {discord_id} removed from Pro')
                except Exception as e:
                    import traceback
                    print(f'[FLOAT] ERROR removing {discord_id} from Pro: {e}')
                    traceback.print_exc()

            self.event = await self.bot.dh.get_tournament_by_id(self.event['_id'])
            print(f'[FLOAT] sync complete: +{len(to_add_to_pro)} to Pro, -{len(to_remove_from_pro)} to Swiss')
            self.logger.info('FLOAT',
                f'Float sync: +{len(to_add_to_pro)} to Pro, -{len(to_remove_from_pro)} to Swiss')
        except Exception as e:
            import traceback
            print(f'[FLOAT] UNHANDLED ERROR in sync_floated_players: {e}')
            traceback.print_exc()

    async def create_bracket_shells(self):
        """
        Create empty Challonge brackets for all bracket phases.
        Triggered manually from the dashboard. Idempotent — skips any
        phase that already has challonge_data.
        """
        from tournaments.challonge_handler import ChallongeHandler

        # Always refresh from DB so the challonge_data guard is reliable
        self.event = await self.bot.dh.get_tournament_by_id(self.event['_id'])
        event = self.event

        # Fast exit: if every bracket phase already has challonge_data, nothing to do
        bracket_phases = [p for p in event.get('phases', [])
                         if p['type'] in ('single elimination', 'double elimination')]
        if bracket_phases and all(p.get('challonge_data') for p in bracket_phases):
            print(f'[BRACKETS] create_bracket_shells() — all brackets already exist, skipping')
            return
        print(f'[BRACKETS] create_bracket_shells() starting for event: {event["name"]} (id={event["_id"]})')
        print(f'[BRACKETS] phases: {[{"label": p.get("label"), "type": p["type"], "has_challonge": bool(p.get("challonge_data"))} for p in event.get("phases", [])]}')

        ch = ChallongeHandler()

        for i, phase in enumerate(event.get('phases', [])):
            if phase['type'] not in ('single elimination', 'double elimination'):
                print(f'[BRACKETS] phase {i} ({phase.get("label")}) type={phase["type"]} — skipping (not a bracket)')
                continue
            if phase.get('challonge_data'):
                print(f'[BRACKETS] phase {i} ({phase.get("label")}) — skipping (already has challonge_data: {phase["challonge_data"]})')
                continue

            bracket_name = f"{event['name']} - {phase['label']}"
            raw_slug = f"{event['name'].lower().replace(' ', '_')}_{phase['label'].lower().replace(' ', '_')}"
            url_slug = ''.join(c for c in raw_slug if c.isalnum() or c == '_')[:60]

            print(f'[BRACKETS] phase {i} ({phase.get("label")}): creating Challonge bracket name={bracket_name!r} url_slug={url_slug!r} type={phase["type"]}')

            try:
                challonge_tournament = await ch.create_tournament(
                    name=bracket_name,
                    tournament_type=phase['type'],
                    url=url_slug,
                )
            except Exception as e:
                import traceback
                print(f'[BRACKETS] phase {i} ({phase.get("label")}): Challonge create_tournament FAILED: {e}')
                traceback.print_exc()
                raise

            print(f'[BRACKETS] phase {i} ({phase.get("label")}): Challonge bracket created — id={challonge_tournament["id"]} url={challonge_tournament["url"]}')

            try:
                await self.bot.dh.tournament_collection.update_one(
                    {'_id': event['_id']},
                    {'$set': {
                        f'phases.{i}.challonge_data': {
                            'url': challonge_tournament['url'],
                            'id': challonge_tournament['id'],
                        },
                    }}
                )
                print(f'[BRACKETS] phase {i} ({phase.get("label")}): DB updated with challonge_data')
            except Exception as e:
                import traceback
                print(f'[BRACKETS] phase {i} ({phase.get("label")}): DB update FAILED: {e}')
                traceback.print_exc()
                raise

            self.logger.info('PHASE',
                f'{phase["label"]}: Challonge shell created — {challonge_tournament["url"]}')

        # Refresh cached event doc
        self.event = await self.bot.dh.get_tournament_by_id(event['_id'])
        print(f'[BRACKETS] create_bracket_shells() complete for event: {event["name"]}')

    async def _create_bracket_phase(self, phase_index: int, player_ids: list[str]):
        """
        Populate and start an existing Challonge bracket for one bracket phase.
        The Challonge bracket was already created at publish time by
        create_bracket_shells(). This method adds players and starts it.
        """
        phase = self.event['phases'][phase_index]
        event = self.event

        if not player_ids:
            await self._update_phase_state(phase_index, 'finished')
            self.logger.info('PHASE', f'{phase["label"]}: no players, skipping')
            return

        ch_data = phase.get('challonge_data')
        if not ch_data:
            raise ValueError(
                f'Phase {phase_index} ({phase.get("label")}) has no Challonge bracket — '
                f'was the event published?'
            )

        from tournaments.challonge_handler import ChallongeHandler
        ch = ChallongeHandler()

        challonge_url = ch_data['url']
        challonge_id = ch_data['id']

        # Players already pre-registered (e.g. floated players from sync_floated_players)
        existing_entrants: dict[str, int] = {
            str(k): v for k, v in (phase.get('entrants') or {}).items()
        }

        # Name lookup: users collection first, Swiss username as fallback
        player_user_map = await self.bot.dh.get_users_bulk(player_ids)
        swiss_phase = self.event['phases'][0]
        swiss_event = await self.bot.dh.get_swiss_event_by_tournament(
            swiss_phase.get('tournament_id') or self.event['_id']
        )
        swiss_name_map: dict[str, str] = {}
        if swiss_event:
            swiss_name_map = {
                pid: p.get('username', '')
                for pid, p in swiss_event.get('players', {}).items()
            }

        entrant_map: dict[str, int] = {}
        for discord_id in player_ids:
            did_str = str(discord_id)
            # Reuse existing participant ID — don't double-register
            if did_str in existing_entrants:
                entrant_map[did_str] = existing_entrants[did_str]
                continue
            user = player_user_map.get(did_str)
            name = (user['name'] if user
                    else swiss_name_map.get(did_str)
                    or f'Player {discord_id}')
            participant_id = await ch.register_player(challonge_url, name)
            entrant_map[did_str] = participant_id

        # Start the bracket
        await ch.start_tournament(challonge_id)

        # Update phase in DB
        await self.bot.dh.tournament_collection.update_one(
            {'_id': event['_id']},
            {'$set': {
                f'phases.{phase_index}.state': 'active',
                f'phases.{phase_index}.entrants': entrant_map,
            }}
        )

        # Create TournamentManager for this bracket
        phase_doc = self._build_phase_tournament_doc(phase_index)
        phase_doc['entrants'] = entrant_map
        phase_doc['challonge_data'] = {'url': challonge_url, 'id': challonge_id}
        phase_doc['state'] = 'active'

        tm = TournamentManager(self.bot, phase_doc)
        tm.format = make_format(tm)
        await tm.format.on_initialize()
        self.phase_managers[phase_index] = tm

        # Backward compat
        self.bot.th.tournaments[phase_doc['_id']] = tm

        self.logger.info('PHASE',
            f'{phase["label"]}: populated with {len(player_ids)} players, started')

    async def transition_to_brackets(self):
        """TO-triggered transition from Swiss phase to the three bracket phases."""
        # Refresh to pick up floated entrants written by sync_floated_players
        self.event = await self.bot.dh.get_tournament_by_id(self.event['_id'])
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
                phase.get('tournament_id') or self.event['_id']
            )
            if swiss_event:
                return await self.bot.dh.swiss_get_standings(swiss_event['_id'])
        return []

    async def _populate_and_start_phase(self, phase_index: int, player_ids: list[str]):
        """Create and start a bracket phase with the given players."""
        tm = await self._create_phase_tm(phase_index)
        self.phase_managers[phase_index] = tm

        player_user_map = await self.bot.dh.get_users_bulk(player_ids)
        for discord_id in player_ids:
            user = player_user_map.get(str(discord_id))
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

    async def destroy_bracket_shells(self):
        """Delete all Challonge brackets created for bracket phases."""
        from tournaments.challonge_handler import ChallongeHandler
        ch = ChallongeHandler()

        for i, phase in enumerate(self.event.get('phases', [])):
            ch_data = phase.get('challonge_data')
            if not ch_data:
                continue
            try:
                await ch.delete_tournament(ch_data['id'])
                self.logger.info('PHASE', f'{phase.get("label", i)}: Challonge bracket deleted')
            except Exception as e:
                self.logger.info('PHASE', f'{phase.get("label", i)}: failed to delete bracket — {e}')

            await self.bot.dh.tournament_collection.update_one(
                {'_id': self.event['_id']},
                {'$set': {
                    f'phases.{i}.challonge_data': None,
                    f'phases.{i}.entrants': {},
                    f'phases.{i}.state': 'waiting',
                }}
            )

        self.event = await self.bot.dh.get_tournament_by_id(self.event['_id'])

    async def _finish_event(self):
        """All phases complete — transition event to finished."""
        await self.bot.dh.update_tournament_state(self.event['_id'], 'finished')
        self.logger.info('STATE', 'Event finished — all phases complete')
