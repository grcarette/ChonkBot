"""
Migration: copy top-level challonge_data into phases[0] for single-phase bracket events.

Safe to run repeatedly — only writes to phases[0].challonge_data when it's currently
None/missing and a top-level challonge_data exists on a single-phase DE/SE tournament.
"""


async def migrate_challonge_to_phase(tournament_collection) -> int:
    cursor = tournament_collection.find({
        'challonge_data': {'$exists': True, '$ne': None},
        'phases.0': {'$exists': True},
    })
    migrated = 0
    async for doc in cursor:
        phases = doc.get('phases', [])
        if not phases:
            continue
        if len(phases) != 1:
            continue
        if phases[0].get('challonge_data'):
            continue  # already has it
        if phases[0].get('type') not in ('single elimination', 'double elimination'):
            continue

        await tournament_collection.update_one(
            {'_id': doc['_id']},
            {'$set': {'phases.0.challonge_data': doc['challonge_data']}}
        )
        migrated += 1

    print(f'[MIGRATION] challonge_to_phase: {migrated} document(s) updated.')
    return migrated
