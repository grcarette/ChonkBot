"""
Temporary startup migration: ensure swiss filter events have the current 4-phase schema.

Safe to run repeatedly — only writes fields that are missing or wrong,
and NEVER touches top-level entrants or per-phase entrants.

Remove this file once all swiss filter events in the DB are confirmed up to date.
"""

# The canonical 4-phase structure for a swiss filter event.
# These are default values only — existing data always wins.
_PHASE_DEFAULTS = [
    {
        'index':           0,
        'type':            'swiss',
        'label':           'Swiss Rounds',
        'round_limit':     3,
        'state':           'setup',
        'tournament_id':   None,
        'config_overrides': {},
    },
    {
        'index':           1,
        'type':            'double elimination',
        'label':           'Pro Bracket',
        'state':           'waiting',
        'tournament_id':   None,
        'challonge_data':  None,
        'config_overrides': {},
        'player_source': {
            'phase_index':    0,
            'method':         'points',
            'points_required':  3,
            'accepts_floated': True,
        },
    },
    {
        'index':           2,
        'type':            'double elimination',
        'label':           'Intermediate Bracket',
        'state':           'waiting',
        'tournament_id':   None,
        'challonge_data':  None,
        'config_overrides': {},
        'player_source': {
            'phase_index':    0,
            'method':         'points',
            'points_required':  2,
            'accepts_floated': False,
        },
    },
    {
        'index':           3,
        'type':            'double elimination',
        'label':           'Beginner Bracket',
        'state':           'waiting',
        'tournament_id':   None,
        'challonge_data':  None,
        'config_overrides': {},
        'player_source': {
            'phase_index':    0,
            'method':         'wins',
            'wins_remaining': True,
        },
    },
]

_VALID_STATES = {'setup', 'waiting', 'active', 'finished'}


def _merge_phase(existing: dict, defaults: dict) -> dict:
    """
    Build a phase doc by starting from defaults and overlaying existing values.
    Never carries over 'entrants' — those are handled separately to avoid
    accidental data loss.
    """
    phase = dict(defaults)

    # Preserve every existing key except entrants
    for key, val in existing.items():
        if key == 'entrants':
            continue
        phase[key] = val

    return phase


async def migrate_swiss_filter_schema(tournament_collection):
    """
    Idempotent: inspect every swiss filter event and patch any schema gaps.
    Returns the number of documents that were updated.
    """
    cursor = tournament_collection.find({'format': 'swiss filter'})
    patched = 0

    async for doc in cursor:
        updates = {}

        # ── Top-level scalar fields ───────────────────────────────────────────

        if doc.get('round_limit') != 3:
            updates['round_limit'] = 3

        if 'active_phase' not in doc:
            updates['active_phase'] = 0

        # ── Phase array ───────────────────────────────────────────────────────

        existing_phases = doc.get('phases', [])

        if len(existing_phases) != 4:
            # Wrong count (missing entirely, or old single-phase migration).
            # Rebuild all 4 phases, preserving any data that exists at each index.
            new_phases = []
            for i, defaults in enumerate(_PHASE_DEFAULTS):
                existing = existing_phases[i] if i < len(existing_phases) else {}
                phase = _merge_phase(existing, defaults)
                # Re-attach entrants from existing phase if present, so we
                # don't wipe bracket phase data that may already be populated.
                if 'entrants' in existing:
                    phase['entrants'] = existing['entrants']
                new_phases.append(phase)

            updates['phases'] = new_phases
            print(f'[MIGRATE] {doc.get("name")}: rebuilt phases array '
                  f'({len(existing_phases)} → 4)')

        else:
            # 4 phases exist — patch only missing or incorrect fields.
            for i, (existing, defaults) in enumerate(zip(existing_phases, _PHASE_DEFAULTS)):
                for key, default_val in defaults.items():
                    if key == 'entrants':
                        continue
                    if key not in existing:
                        updates[f'phases.{i}.{key}'] = default_val
                        print(f'[MIGRATE] {doc.get("name")}: phases[{i}] missing '
                              f'{key!r} → setting to {default_val!r}')

                # Phase 0 round_limit must be exactly 3
                if i == 0 and existing.get('round_limit') != 3:
                    updates['phases.0.round_limit'] = 3
                    print(f'[MIGRATE] {doc.get("name")}: phases[0].round_limit '
                          f'{existing.get("round_limit")!r} → 3')

                # State must be a known value
                if existing.get('state') not in _VALID_STATES:
                    updates[f'phases.{i}.state'] = defaults['state']
                    print(f'[MIGRATE] {doc.get("name")}: phases[{i}].state '
                          f'{existing.get("state")!r} → {defaults["state"]!r}')

        if updates:
            await tournament_collection.update_one(
                {'_id': doc['_id']},
                {'$set': updates}
            )
            patched += 1

    if patched:
        print(f'[MIGRATE] swiss_filter_schema: patched {patched} event(s)')
    else:
        print('[MIGRATE] swiss_filter_schema: all events up to date')

    return patched
