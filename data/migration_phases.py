"""
One-time migration: wrap existing tournament documents in a single-phase event.

Run with:
    python -m data.migration_phases
or call migrate_to_phase_model(tournament_collection) from a script.
"""


def _default_label(fmt: str) -> str:
    return {
        'swiss': 'Swiss Rounds',
        'single elimination': 'Single Elimination',
        'double elimination': 'Double Elimination',
        'swiss filter': 'Swiss Rounds',
    }.get(fmt, fmt.title())


async def migrate_to_phase_model(tournament_collection):
    """One-time migration: wrap existing tournaments in a single-phase event."""
    cursor = tournament_collection.find({'phases': {'$exists': False}})
    migrated = 0
    async for doc in cursor:
        fmt = doc.get('format', '')
        state = doc.get('state', 'setup')
        phase_state = state if state in ('active', 'finished') else 'setup'

        phase = {
            'index': 0,
            'type': fmt,
            'label': _default_label(fmt),
            'state': phase_state,
            'tournament_id': doc['_id'],    # self-referential for legacy
            'config_overrides': {},
        }
        if fmt in ('swiss', 'swiss filter'):
            phase['round_limit'] = doc.get('round_limit', 8)

        await tournament_collection.update_one(
            {'_id': doc['_id']},
            {'$set': {
                'phases': [phase],
                'active_phase': 0,
            }}
        )
        migrated += 1

    print(f'Migration complete: {migrated} documents updated.')
    return migrated
