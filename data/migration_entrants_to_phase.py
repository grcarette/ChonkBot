"""
Migration: copy top-level entrants to phases[0].entrants for single-phase events.

Safe to run repeatedly — only writes to phases[0].entrants when it's currently
empty/missing and a top-level entrants dict exists on a single-phase tournament.
Swiss filter events are skipped (they use phase-level entrants already).
"""


async def migrate_entrants_to_phase(tournament_collection) -> int:
    cursor = tournament_collection.find({
        'entrants': {'$exists': True, '$ne': {}},
        'phases.0': {'$exists': True},
    })
    migrated = 0
    async for doc in cursor:
        phases = doc.get('phases', [])
        if not phases:
            continue
        # Only migrate single-phase events — swiss filter already has phase entrants
        if len(phases) != 1:
            continue
        if phases[0].get('entrants'):
            continue  # already has entrants on phase

        await tournament_collection.update_one(
            {'_id': doc['_id']},
            {'$set': {'phases.0.entrants': doc['entrants']}}
        )
        migrated += 1

    print(f'[MIGRATION] entrants_to_phase: {migrated} document(s) updated.')
    return migrated
