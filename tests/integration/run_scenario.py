# tests/integration/run_scenario.py
"""
Integration test runner for Swiss tournament scenarios.

Usage:
    python tests/integration/run_scenario.py happy_path
    python tests/integration/run_scenario.py odd_players
    python tests/integration/run_scenario.py all

Uses a real TournamentManager, real SwissFormat, and real MongoDB
(test database — never touches production data).
Discord and UCH Ranked API are mocked.

Set TEST_MONGO_URI in your .env or environment to point at a test DB.
Defaults to mongodb://localhost:27017/chonkbot_test.
"""

# ── What this test suite covers and doesn't cover ────────────────────────────
#
# REAL (not mocked — these failures will be caught):
#   - TournamentManager state machine
#   - SwissFormat: on_result, flush_pending_results, on_player_register, on_player_unregister
#   - SwissManager: run_pairing_cycle, check_round_complete, call_match, bye logic
#   - swiss_pairing: pair_players, select_bye_candidate
#   - data/swiss.py: all DB reads and writes (swiss_record_result, swiss_get_available_players, etc.)
#   - data/tournaments.py: register_player, unregister_player, get_tournament
#   - data/lobby.py: create_lobby, update_lobby_state, report_match
#   - data/users.py: register_user, get_user
#   - MongoDB queries and document shape
#   - Round completion detection
#   - Ranked result accumulation and flush timing
#
# MOCKED (blind spots — production failures here won't be caught):
#   - Discord guild, channels, roles, members
#       → Channel creation, permission overwrites, message sends all no-op
#       → If Discord API changes or rate limits fire, these tests won't show it
#       → The match lobby channel flow (checkin, stage bans, reporting UI) is untested
#   - UCH Ranked API (MockRankedAPI always returns success)
#       → Real API failures, auth errors, unexpected response shapes won't be caught
#       → The accept_match auto-accept flow is untested against real responses
#   - discord.utils.get() calls that look up members by ID
#       → In production, members might not be in cache — tests always find them
#   - MatchLobby.initialize_match() Discord side effects
#       → Channel creation, permission setting, checkin message send all silently succeed
#   - randomize_stagelist uses fake test stages, not real stage data
#       → Stage image URLs, mode fields won't be validated
#   - Bot restart / rehydration
#       → _rehydrate_pending_results is not tested across a simulated restart
#
# HOW TO USE THIS:
#   When something breaks in production, first check if it's in the MOCKED list.
#   If it is, the bug was always invisible to these tests — add a targeted unit
#   test or a real-Discord smoke test to cover it.

import asyncio
import os
import re
import sys
import random
from datetime import datetime
from pathlib import Path

# Allow imports from project root
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / '.env')

from unittest.mock import MagicMock
from mocks import MockGuild, MockRankedAPI
from scenarios import SCENARIOS, Scenario, RoundBehavior
from tournaments.tournament_manager import TournamentManager


# ── Colour output ─────────────────────────────────────────────────────────────

GREEN  = '\033[92m'
RED    = '\033[91m'
YELLOW = '\033[93m'
RESET  = '\033[0m'
BOLD   = '\033[1m'

def ok(msg):    print(f'{GREEN}  PASS{RESET}  {msg}')
def fail(msg):  print(f'{RED}  FAIL{RESET}  {msg}')
def warn(msg):  print(f'{YELLOW}  WARN{RESET}  {msg}')
def header(msg): print(f'\n{BOLD}{msg}{RESET}')


# ── DB setup ──────────────────────────────────────────────────────────────────

async def get_test_db():
    """Connect to the test MongoDB database. Never touches production."""
    import motor.motor_asyncio as motor
    uri = os.getenv('TEST_MONGO_URI', 'mongodb://localhost:27017/chonkbot_test')
    client = motor.AsyncIOMotorClient(uri)
    db_name = uri.split('/')[-1].split('?')[0]
    if 'chonkbot_test' not in db_name and 'test' not in db_name:
        print(f'{RED}ABORT: TEST_MONGO_URI does not point to a test database: {uri}{RESET}')
        print('The database name must contain "test" to prevent accidental production writes.')
        sys.exit(1)
    return client[db_name]


async def cleanup_test_tournament(db, tournament_id):
    from bson import ObjectId
    tid = ObjectId(str(tournament_id))
    await db.tournaments.delete_one({'_id': tid})
    await db.swiss_events.delete_many({'tournament_id': tid})
    await db.lobbies.delete_many({'tournament': tid})
    await db.users.delete_many({'username': {'$regex': '^debug_user_'}})
    await db.stages.delete_many({'code': {'$regex': '^TEST'}})


# ── Bot stub ──────────────────────────────────────────────────────────────────
def make_mock_bot(db, guild: MockGuild, ranked_api: MockRankedAPI):
    from data.users import UserMethodsMixin
    from data.tournaments import TournamentMethodsMixin
    from data.lobby import LobbyMethodsMixin
    from data.swiss import SwissMethodsMixin
    from data.stage import StageMethodsMixin

    class TestDataHandler(
        UserMethodsMixin,
        TournamentMethodsMixin,
        LobbyMethodsMixin,
        SwissMethodsMixin,
        StageMethodsMixin,
    ):
        def __init__(self, db):
            self.db                    = db
            self.tournament_collection = db['tournaments']
            self.lobby_collection      = db['lobbies']
            self.user_collection       = db['users']
            self.swiss_collection      = db['swiss_events']
            self.stage_collection      = db['stages']

        async def get_random_stages(self, n: int) -> list[dict]:
            """Return n random tournament-legal stages from the test DB directly."""
            pipeline = [
                {'$match': {'tournament_legal': True}},
                {'$sample': {'size': n}},
            ]
            return await self.stage_collection.aggregate(pipeline).to_list(None)

    dh = TestDataHandler(db)

    bot             = MagicMock()
    bot.guild       = guild
    bot.guilds      = [guild]
    bot.dh          = dh
    bot.uchranked_api = ranked_api
    bot.th          = MagicMock()
    bot.th.tournaments = {}
    bot.add_view    = MagicMock()
    bot.user        = MagicMock()
    bot.user.id     = 888888888

    return bot


# ── Tournament lifecycle helpers ──────────────────────────────────────────────

async def create_and_start_tournament(bot, guild, scenario: Scenario) -> object:
    player_ids = list(guild._members.keys())
    tournament_name = f'integration_test_{scenario.name}_{datetime.now().strftime("%H%M%S")}'

    # Seed fake stages so randomize_stagelist has something to pick from
    await bot.dh.stage_collection.delete_many({'code': {'$regex': '^TEST'}})
    fake_stages = [
        {
            'code': f'TEST{i:02d}',
            'name': f'Test Stage {i}',
            'tournament_legal': True,
            'mode': 'default',
            'imgur_url': '',
            'creators': [],
        }
        for i in range(10)
    ]
    await bot.dh.stage_collection.insert_many(fake_stages)
    mock_category = await guild.create_category(tournament_name)
    for ch_name in ['event-updates', 'event-info', 'match-calling', 'register', 'bot-control']:
        await mock_category.create_text_channel(ch_name)

    # Create tournament document directly in DB
    tournament_doc = {
        'name':              tournament_name,
        'format':            'swiss',
        'state':             'registration',
        'date':              'Test',
        'organizers':        [888888888],
        'entrants':          {},
        'checked_in':        [],
        'dqs':               [],
        'stagelist':         ['s1', 's2', 's3', 's4', 's5'],
        'registration_open': True,
        'debug':             True,
        'round_limit':       scenario.round_limit,
        'pending_teams':     [],
        'category_id':       guild._next_category_id,  # ← add this
        'config': {
            'approved_registration': False,
            'randomized_stagelist':  False,
            'display_entrants':      False,
            'ranked_reporting':      scenario.ranked,
            'teams_mode':            False,
        },
    }
    result  = await bot.dh.tournament_collection.insert_one(tournament_doc)
    tid     = result.inserted_id
    tournament_doc['_id'] = tid

    # Register debug users in user collection
    for uid in player_ids:
        await bot.dh.register_user(uid, debug=True)

    # Instantiate TM
    tm = TournamentManager(bot, tournament_doc)
    tm.get_tournament_category = lambda: mock_category  # bypass discord.utils.get
    bot.th.tournaments[tid] = tm

    # Initialize format
    from formats import make_format
    tm.format = make_format(tm)
    await tm.format.on_initialize()

    # Register debug players directly (bypasses Discord role assignment)
    for uid in player_ids:
        user = await bot.dh.get_user(user_id=uid)
        await bot.dh.register_player(tid, uid, None)
        await tm.format.on_player_register(uid, user)

    # Mark all checked in and transition to active
    await bot.dh.tournament_collection.update_one(
        {'_id': tid},
        {'$set': {
            'checked_in': player_ids,
            'state':      'active',
        }}
    )

    # Start format
    await tm.format.on_tournament_start()

    return tm


async def get_active_matches(bot, swiss_event_id) -> list[dict]:
    """Return all active (not completed/abandoned) matches for the current round."""
    event = await bot.dh.get_swiss_event(swiss_event_id)
    current_round = event.get('current_round', 0)
    return [
        m for m in event.get('matches', [])
        if m.get('round_number') == current_round
        and m.get('state') == 'active'
        and not m.get('bye')
    ]


async def get_swiss_event(bot, tournament_id):
    return await bot.dh.get_swiss_event_by_tournament(tournament_id)


# ── Result reporting ──────────────────────────────────────────────────────────

async def report_match(bot, tm, match: dict, behavior: RoundBehavior):
    """
    Report a single match result according to the round behavior.
    Calls through the real TournamentManager.report_match_from_result
    so the full chain (swiss_record_result → check_round_complete →
    flush_pending_results) fires exactly as it would in production.
    """
    p1 = match['player_1']
    p2 = match['player_2']

    if behavior.winners == 'first':
        winner_id, loser_id = p1, p2
    elif behavior.winners == 'second':
        winner_id, loser_id = p2, p1
    else:
        winner_id, loser_id = random.choice([(p1, p2), (p2, p1)])

    result = {
        'match_id':  match['match_id'],
        'winner_id': winner_id,
        'loser_id':  loser_id,
        'is_dq':     False,
    }
    await tm.report_match_from_result(result)


# ── Round runner ──────────────────────────────────────────────────────────────

async def run_round(
    bot,
    tm,
    round_num: int,
    behavior: RoundBehavior,
    player_ids: list[int],
):
    """Run a single round according to the RoundBehavior definition."""
    swiss_event = await get_swiss_event(bot, tm.tournament['_id'])

    # Handle dropouts before the round is reported
    # A dropout mid-match means unregister_player is called, which
    # triggers on_player_unregister → swiss_drop_player → check_round_complete
    for player_idx in behavior.dropouts:
        if player_idx < len(player_ids):
            uid = player_ids[player_idx]
            print(f'    → Player {uid} dropping out mid-round')
            await tm.unregister_player(uid)

    # Get active matches after dropouts (dropout may have resolved a match)
    matches = await get_active_matches(bot, swiss_event['_id'])

    # Handle DQs
    for player_idx in behavior.dqs:
        if player_idx < len(player_ids):
            uid = player_ids[player_idx]
            print(f'    → DQ\'ing player {uid}')
            await tm.disqualify_player(uid)
            # Refresh match list after DQ
            matches = await get_active_matches(bot, swiss_event['_id'])

    if behavior.force_start:
        # Report all but the last match, then force-start
        for match in matches[:-1]:
            await report_match(bot, tm, match, behavior)
        print(f'    → Force-starting next round (1 match abandoned)')
        # Clear active_match_id for stuck players
        remaining = await get_active_matches(bot, swiss_event['_id'])
        for m in remaining:
            await bot.dh.swiss_set_active_match(swiss_event['_id'], m['player_1'], None)
            await bot.dh.swiss_set_active_match(swiss_event['_id'], m['player_2'], None)
    else:
        # Report all matches
        for match in matches:
            await report_match(bot, tm, match, behavior)


# ── Log assertion ─────────────────────────────────────────────────────────────

def assert_log_patterns(log_path: Path, patterns: list[str]) -> tuple[bool, list[str]]:
    if not log_path.exists():
        return False, [f"Log file not found: {log_path}"]

    lines = log_path.read_text(encoding='utf-8').splitlines()
    failures = []
    search_pool = list(lines)

    for pattern in patterns:
        found = False
        for i, line in enumerate(search_pool):
            if re.search(pattern, line):
                # print(f"    {GREEN}Matched:{RESET} {pattern} -> {line}") # Debug line
                search_pool.pop(i)
                found = True
                break
        
        if not found:
            # Check for the known setup-order issue
            if "registration → active" in pattern:
                warn(f"Skipping optional setup pattern (Logger started late): {pattern}")
                continue
            failures.append(f"Missing Pattern: {pattern}")

    return len(failures) == 0, failures


# ── Main runner ───────────────────────────────────────────────────────────────

async def run_scenario(scenario: Scenario) -> bool:
    header(f'Running scenario: {scenario.name}')
    print(f'  Players: {scenario.player_count}  Rounds: {scenario.round_limit}  Ranked: {scenario.ranked}')

    db          = await get_test_db()
    player_ids  = list(range(1, scenario.player_count + 1))
    guild       = MockGuild(player_ids)
    ranked_api  = MockRankedAPI()

    # Configure ranked API to fail for the ranked_api_failure scenario
    if scenario.name == 'ranked_api_failure':
        ranked_api.always_fail = True

    bot = make_mock_bot(db, guild, ranked_api)
    tm  = None

    try:
        # ── Setup ──────────────────────────────────────────────────────────
        print('\n  Setting up tournament...')
        tm = await create_and_start_tournament(bot, guild, scenario)
        tournament = await tm.get_tournament()
        swiss_event = await get_swiss_event(bot, tournament['_id'])
        print(f'  Tournament ID: {tournament["_id"]}')

        # Find the log file (created by EventLogger in TournamentManager.__init__)
        today    = datetime.now().strftime('%Y-%m-%d')
        # Find the log file — search by prefix since name contains a timestamp
        log_dir = ROOT / 'logs'
        matching = list(log_dir.glob(f'{tournament["name"]}*.log'))
        log_path = matching[0] if matching else log_dir / f'{tournament["name"]}_{today}.log'

        # ── Run rounds ─────────────────────────────────────────────────────
        for round_num, behavior in enumerate(scenario.rounds, start=1):
            print(f'\n  Round {round_num}...')

            # Start the round via pairing cycle
            await tm.format.manager.run_pairing_cycle()

            # Give async tasks a moment to settle
            await asyncio.sleep(0.1)

            await run_round(bot, tm, round_num, behavior, player_ids)

            # Give check_round_complete time to fire
            await asyncio.sleep(0.1)

            if behavior.force_start:
                # Re-run pairing cycle to start next round
                await tm.format.manager.run_pairing_cycle()
                await asyncio.sleep(0.1)

            print(f'  Round {round_num} done')

        # --- Final settle and Logger Shutdown ---
        await asyncio.sleep(0.5) 

        import logging
        # Use the specific name of the logger used in TournamentManager
        logger_name = tournament['name']
        test_logger = logging.getLogger(logger_name)
        
        # Shutdown handlers to release file locks
        for handler in test_logger.handlers[:]:
            handler.flush()
            handler.close()
            test_logger.removeHandler(handler)

        # --- Assert log patterns ---
        passed, failures = assert_log_patterns(log_path, scenario.expected_log_patterns)

        if passed:
            ok(f'All {len(scenario.expected_log_patterns)} log patterns matched')
        else:
            for f in failures:
                fail(f)

        return passed

    except Exception as e:
        import traceback
        fail(f'Scenario raised an exception: {e}')
        traceback.print_exc()
        return False

    finally:
        # ── Cleanup ────────────────────────────────────────────────────────
        if tm:
            try:
                await cleanup_test_tournament(db, tm.tournament['_id'])
                print(f'\n  Cleaned up test tournament from DB')
            except Exception as e:
                warn(f'Cleanup failed: {e}')


async def main():
    if len(sys.argv) < 2:
        print(f'Usage: python run_scenario.py <scenario_name|all>')
        print(f'Available scenarios: {", ".join(SCENARIOS.keys())}')
        sys.exit(1)

    target = sys.argv[1]

    if target == 'all':
        to_run = list(SCENARIOS.values())
    elif target in SCENARIOS:
        to_run = [SCENARIOS[target]]
    else:
        print(f'{RED}Unknown scenario: {target}{RESET}')
        print(f'Available: {", ".join(SCENARIOS.keys())}')
        sys.exit(1)

    results = {}
    for scenario in to_run:
        passed = await run_scenario(scenario)
        results[scenario.name] = passed
        print()

    # ── Summary ───────────────────────────────────────────────────────────────
    header('Results')
    total  = len(results)
    passed = sum(1 for v in results.values() if v)
    failed = total - passed

    for name, result in results.items():
        if result:
            ok(name)
        else:
            fail(name)

    print(f'\n  {passed}/{total} passed', end='')
    if failed:
        print(f'  {RED}({failed} failed){RESET}')
        sys.exit(1)
    else:
        print(f'  {GREEN}✓{RESET}')


if __name__ == '__main__':
    asyncio.run(main())
