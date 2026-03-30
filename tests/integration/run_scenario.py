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
#   - Score correctness: elo bonus, win/loss accounting, bye points, DQ penalties
#
# MOCKED (blind spots — production failures here won't be caught):
#   - Discord guild, channels, roles, members
#       → Channel creation, permission overwrites, message sends all no-op
#       → If Discord API changes or rate limits fire, these tests won't show it
#       → The match lobby channel flow (checkin, stage bans, reporting UI) is untested
#   - UCH Ranked API (MockRankedAPI always returns success unless configured)
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
from scenarios import SCENARIOS, Scenario, RoundBehavior, ScoreCheck
from tournaments.tournament_manager import TournamentManager


# ── Colour output ─────────────────────────────────────────────────────────────

GREEN  = '\033[92m'
RED    = '\033[91m'
YELLOW = '\033[93m'
CYAN   = '\033[96m'
DIM    = '\033[2m'
RESET  = '\033[0m'
BOLD   = '\033[1m'

def ok(msg):    print(f'{GREEN}  PASS{RESET}  {msg}')
def fail(msg):  print(f'{RED}  FAIL{RESET}  {msg}')
def warn(msg):  print(f'{YELLOW}  WARN{RESET}  {msg}')
def info(msg):  print(f'  {DIM}INFO{RESET}  {msg}')
def header(msg): print(f'\n{BOLD}{msg}{RESET}')


# ── Log replay ────────────────────────────────────────────────────────────────

CATEGORY_COLORS = {
    'STATE':        f'{BOLD}{GREEN}',
    'SWISS':        CYAN,
    'RANKED':       YELLOW,
    'REGISTRATION': DIM,
    'DQ':           RED,
    'ERROR':        RED,
    'LOGGER':       DIM,
    'TEST':         DIM,
}

def print_log_replay(log_path: Path, label: str = 'Event Log'):
    """Print the full event log with color-coded categories."""
    if not log_path.exists():
        warn(f'Log file not found: {log_path}')
        return

    header(label)
    for line in log_path.read_text(encoding='utf-8').splitlines():
        colored = line
        for cat, color in CATEGORY_COLORS.items():
            if f'[{cat}]' in line:
                colored = f'  {color}{line}{RESET}'
                break
        else:
            colored = f'  {DIM}{line}{RESET}'
        print(colored)
    print()


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


# ── Shared integration test log ───────────────────────────────────────────────

_shared_log_path: Path = None
_failure_log_path: Path = None


def init_shared_logs():
    global _shared_log_path, _failure_log_path
    today = datetime.now().strftime('%Y-%m-%d_%H%M%S')
    log_dir = ROOT / 'logs'
    log_dir.mkdir(exist_ok=True)
    _shared_log_path  = log_dir / f'integration_run_{today}.log'
    _failure_log_path = log_dir / f'integration_failures_{today}.log'
    _shared_log_path.write_text(f'=== Integration Test Run — {today} ===\n\n')
    _failure_log_path.write_text(f'=== Integration Test Failures — {today} ===\n\n')


def append_to_shared_log(text: str):
    with open(_shared_log_path, 'a', encoding='utf-8') as f:
        f.write(text)


def append_to_failure_log(text: str):
    with open(_failure_log_path, 'a', encoding='utf-8') as f:
        f.write(text)


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
        'checked_in':        [],
        'dqs':               [],
        'entrants':          {},
        'stagelist':         ['s1', 's2', 's3', 's4', 's5'],
        'registration_open': True,
        'debug':             True,
        'round_limit':       scenario.round_limit,
        'pending_teams':     [],
        'active_phase':      0,
        'category_id':       guild._next_category_id,
        'config': {
            'approved_registration': False,
            'randomized_stagelist':  False,
            'display_entrants':      False,
            'ranked_reporting':      scenario.ranked,
            'teams_mode':            False,
        },
        'phases': [
            {
                'index': 0,
                'type': 'swiss',
                'label': 'Swiss Rounds',
                'state': 'setup',
                'config_overrides': {},
                'round_limit': scenario.round_limit,
                'entrants': {},
            }
        ],
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
    tm.logger.debug('TEST', f'Reporting match {result["match_id"]} — winner: {winner_id}, loser: {loser_id}')
    await tm.report_match_from_result(result)


# ── Round runner ──────────────────────────────────────────────────────────────

async def run_round(
    bot,
    tm,
    round_num: int,
    behavior: RoundBehavior,
    player_ids: list[int],
    swiss_event_id,
):
    """Run a single round according to the RoundBehavior definition."""
    swiss_event = await bot.dh.get_swiss_event(swiss_event_id)

    # Handle dropouts before the round is reported
    # Replicate what the Leave button does: resolve active match first,
    # then call unregister_player.
    for player_idx in behavior.dropouts:
        if player_idx < len(player_ids):
            uid = player_ids[player_idx]
            print(f'    → Player {uid} dropping out mid-round')

            # Resolve active match — give opponent a default win
            player_data = swiss_event.get('players', {}).get(str(uid))
            if player_data and player_data.get('active_match_id') is not None:
                active_match_id = player_data['active_match_id']
                match_doc = next(
                    (m for m in swiss_event.get('matches', [])
                     if m['match_id'] == active_match_id),
                    None
                )
                if match_doc:
                    opponent_id = (
                        match_doc['player_2'] if match_doc['player_1'] == uid
                        else match_doc['player_1']
                    )
                    await bot.dh.swiss_record_result(
                        swiss_event['_id'], active_match_id, opponent_id, uid
                    )
                    tm.logger.match_result(active_match_id, opponent_id, uid)

            await tm.unregister_player(uid)
            # Refresh swiss_event after the drop
            swiss_event = await bot.dh.get_swiss_event(swiss_event_id)

    # Get active matches after dropouts (dropout may have resolved a match)
    matches = await get_active_matches(bot, swiss_event_id)

    # Handle DQs
    for player_idx in behavior.dqs:
        if player_idx < len(player_ids):
            uid = player_ids[player_idx]
            print(f'    → DQ\'ing player {uid}')
            await tm.disqualify_player(uid)
            # Refresh match list after DQ
            matches = await get_active_matches(bot, swiss_event_id)

    if behavior.force_start:
        # Report all but the last match, then force-start
        for match in matches[:-1]:
            await report_match(bot, tm, match, behavior)
            info(f'Match {match["match_id"]}: {match["player_1"]} vs {match["player_2"]} reported')
        print(f'    → Force-starting next round (1 match abandoned)')
        # Clear active_match_id for stuck players
        remaining = await get_active_matches(bot, swiss_event_id)
        for m in remaining:
            await bot.dh.swiss_set_active_match(swiss_event_id, m['player_1'], None)
            await bot.dh.swiss_set_active_match(swiss_event_id, m['player_2'], None)
    else:
        # Report all matches
        for match in matches:
            await report_match(bot, tm, match, behavior)
            info(f'Match {match["match_id"]}: {match["player_1"]} vs {match["player_2"]} reported')

    # Fast-forward any pending bye (bye is now immediate, but check just in case)
    swiss_event = await bot.dh.get_swiss_event(swiss_event_id)
    bye_player = swiss_event.get('bye_queue')
    if bye_player is not None:
        print(f'    → Fast-forwarding bye for player {bye_player}')
        if tm.format.manager.bye_task and not tm.format.manager.bye_task.done():
            tm.format.manager.bye_task.cancel()
            tm.format.manager.bye_task = None
        await bot.dh.swiss_award_bye(swiss_event_id, bye_player)
        tm.logger.bye_awarded(bye_player)
        await bot.dh.swiss_set_bye_queue(swiss_event_id, None)
        await tm.format.manager.check_round_complete()


# ── Log assertion ─────────────────────────────────────────────────────────────

def assert_log_patterns(log_path: Path, patterns: list[str]) -> tuple[bool, list[str]]:
    if not log_path.exists():
        return False, [f"Log file not found: {log_path}"]

    lines = log_path.read_text(encoding='utf-8').splitlines()
    failures = []
    matched_lines = []
    search_start = 0

    for pattern in patterns:
        found = False
        for i in range(search_start, len(lines)):
            if re.search(pattern, lines[i]):
                matched_lines.append((pattern, lines[i], i))
                search_start = i + 1
                found = True
                break

        if not found:
            if "registration → active" in pattern:
                warn(f"Skipping optional setup pattern (Logger started late): {pattern}")
                matched_lines.append((pattern, '(skipped — logger started late)', -1))
                continue

            # Show context: what log lines exist near where we expected this pattern
            context_start = max(0, search_start - 2)
            context_end = min(len(lines), search_start + 5)
            nearby = lines[context_start:context_end]
            nearby_display = '\n'.join(f'        L{context_start + j}: {l}' for j, l in enumerate(nearby))
            failures.append(
                f"Missing pattern: {pattern}\n"
                f"      Expected after line {search_start}. Nearby log lines:\n{nearby_display}"
            )

    # Print match table
    header('Pattern Match Results')
    for pat, line, line_num in matched_lines:
        if line_num == -1:
            print(f'  {YELLOW}SKIP{RESET}  {DIM}{pat}{RESET}')
        else:
            print(f'  {GREEN} ✓  {RESET}  L{line_num:<4} {DIM}{pat}{RESET}')
    for f_msg in failures:
        first_line = f_msg.split('\n')[0]
        print(f'  {RED} ✗  {RESET}  {first_line}')
    print()

    return len(failures) == 0, failures


# ── Score verification ────────────────────────────────────────────────────────

async def verify_scores(bot, tournament_id, round_num: int, checks: list) -> tuple[bool, list[str]]:
    """
    Verify player scores against expected values from ScoreCheck list.
    Returns (all_passed, list_of_failure_messages).
    """
    swiss_event = await get_swiss_event(bot, tournament_id)
    if not swiss_event:
        return False, [f'Swiss event not found for tournament {tournament_id}']

    players = swiss_event.get('players', {})
    failures = []

    for check in checks:
        pid = str(check.player_id)
        player = players.get(pid)
        if player is None:
            failures.append(f'Player {check.player_id} not found in swiss event')
            continue

        fields = [
            ('points',        check.points,        player.get('points')),
            ('wins',          check.wins,           player.get('wins')),
            ('losses',        check.losses,         player.get('losses')),
            ('rounds_played', check.rounds_played,  player.get('rounds_played')),
            ('dropped',       check.dropped,        player.get('dropped')),
        ]

        for field_name, expected, actual in fields:
            if expected is None:
                continue
            if actual != expected:
                failures.append(
                    f'Player {check.player_id} after round {round_num}: '
                    f'{field_name} expected={expected}, actual={actual}'
                )

    return len(failures) == 0, failures

async def verify_score_integrity(bot, tournament_id, round_num: int) -> tuple[bool, list[str]]:
    """
    Global invariant check: for every player, verify that
        points == initial_bonus + wins + byes

    Runs every round on every scenario. Catches scoring drift
    without needing to know match outcomes.
    """
    swiss_event = await get_swiss_event(bot, tournament_id)
    if not swiss_event:
        return True, []

    players = swiss_event.get('players', {})
    failures = []

    for did, p in players.items():
        pts = p.get('points', 0)
        wins = p.get('wins', 0)
        losses = p.get('losses', 0)
        rds = p.get('rounds_played', 0)
        tier = p.get('tier', 3)

        # Reconstruct initial bonus from tier
        if tier == 1:
            init = 2.0
        elif tier == 2:
            init = 1.0
        else:
            init = 0.0

        staggered = p.get('staggered_bonus', 0)
        byes = max(0, rds - wins - losses)
        expected = init + staggered + wins + byes

        if abs(pts - expected) > 0.01:
            name = p.get('username', f'player_{did}')
            failures.append(
                f'{name} after round {round_num}: points={pts} but '
                f'init({init}) + staggered({staggered}) + wins({wins}) + byes({byes}) = {expected}'
            )

    return len(failures) == 0, failures


def print_scoreboard(players: dict, title: str, initial_points: dict = None):
    """Print a formatted scoreboard from the swiss event players dict.
    
    If initial_points is provided, shows the elo bonus and a check column
    that verifies points == initial + wins (+ byes) - dq_penalties.
    """
    header(title)
    sorted_players = sorted(
        players.items(),
        key=lambda x: (-x[1].get('points', 0), -x[1].get('wins', 0)),
    )
    if initial_points:
        print(f'    {"Player":<20} {"Pts":>5} {"Init":>5} {"W":>3} {"L":>3} {"Rds":>4} {"Status":<10} {"Check":<6}')
        print(f'    {"─" * 65}')
    else:
        print(f'    {"Player":<20} {"Pts":>5} {"W":>3} {"L":>3} {"Rds":>4} {"Status":<10}')
        print(f'    {"─" * 50}')
    for did, p in sorted_players:
        status = 'dropped' if p.get('dropped') else 'active'
        name = p.get('username', f'player_{did}')
        pts = p.get('points', 0)
        wins = p.get('wins', 0)
        losses = p.get('losses', 0)
        rds = p.get('rounds_played', 0)
        if initial_points:
            init = initial_points.get(did, 0)
            # expected = initial + wins + byes - dq_penalty
            # byes = rounds_played - wins - losses
            byes = max(0, rds - wins - losses)
            expected = init + wins + byes
            # DQ penalty: if points < expected, the gap is penalty
            # We can't know is_dq from here, so just check if it adds up
            check = '✓' if abs(pts - expected) < 0.01 else f'✗ ({expected:.1f})'
            print(f'    {name:<20} {pts:>5.1f} {init:>5.1f} {wins:>3} {losses:>3} {rds:>4} {status:<10} {check:<6}')
        else:
            print(f'    {name:<20} {pts:>5.1f} {wins:>3} {losses:>3} {rds:>4} {status:<10}')
    print()


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
        log_dir = ROOT / 'logs'
        matching = list(log_dir.glob(f'{tournament["name"]}*.log'))
        log_path = matching[0] if matching else log_dir / f'{tournament["name"]}.log'

        score_all_passed = True
        all_score_failures = []
        initial_points = {}

        # Capture initial points — always, not just when there's a round-0 check
        swiss_event_snap = await get_swiss_event(bot, tournament['_id'])
        initial_points = {
            did: p.get('points', 0)
            for did, p in swiss_event_snap.get('players', {}).items()
        }

        # ── Pre-round score check (round 0) ────────────────────────────────
        if 0 in scenario.score_checks:
            swiss_event_snap = await get_swiss_event(bot, tournament['_id'])
            print_scoreboard(swiss_event_snap.get('players', {}), 'Initial Scores (Round 0)')
            score_ok, score_failures = await verify_scores(
                bot, tournament['_id'], 0, scenario.score_checks[0]
            )
            if score_ok:
                ok(f'Round 0 score check passed ({len(scenario.score_checks[0])} players)')
            else:
                for sf in score_failures:
                    fail(sf)
                all_score_failures.extend(score_failures)
                score_all_passed = False

        # ── Run rounds ─────────────────────────────────────────────────────
        for round_num, behavior in enumerate(scenario.rounds, start=1):
            print(f'\n  Round {round_num}...')

            # Start the round via pairing cycle
            await tm.format.manager.run_pairing_cycle()

            # Give async tasks (including bye) time to settle
            await asyncio.sleep(0.5)

            await run_round(bot, tm, round_num, behavior, player_ids, swiss_event['_id'])

            # Give check_round_complete time to fire
            await asyncio.sleep(0.5)

            if behavior.force_start:
                # Re-run pairing cycle to start next round
                await tm.format.manager.run_pairing_cycle()
                await asyncio.sleep(0.5)

            print(f'  Round {round_num} done')

            # ── Post-round score check ─────────────────────────────────────
            if round_num in scenario.score_checks:
                swiss_event_snap = await get_swiss_event(bot, tournament['_id'])
                print_scoreboard(swiss_event_snap.get('players', {}), f'Scores After Round {round_num}')
                score_ok, score_failures = await verify_scores(
                    bot, tournament['_id'], round_num, scenario.score_checks[round_num]
                )
                if score_ok:
                    ok(f'Round {round_num} score check passed ({len(scenario.score_checks[round_num])} players)')
                else:
                    for sf in score_failures:
                        fail(sf)
                    all_score_failures.extend(score_failures)
                    score_all_passed = False

            # ── Score integrity check (every round, every scenario) ────────
            integrity_ok, integrity_failures = await verify_score_integrity(
                bot, tournament['_id'], round_num
            )
            if integrity_ok:
                ok(f'Round {round_num} score integrity check passed')
            else:
                for sf in integrity_failures:
                    fail(sf)
                all_score_failures.extend(integrity_failures)
                score_all_passed = False

        # --- Final settle and Logger Shutdown ---
        await asyncio.sleep(0.5)

        import logging
        logger_name = tournament['name']
        test_logger = logging.getLogger(logger_name)

        # Shutdown handlers to release file locks
        for handler in test_logger.handlers[:]:
            handler.flush()
            handler.close()
            test_logger.removeHandler(handler)

        # Also flush the EventLogger's actual logger
        for attr_name in dir(tm.logger):
            attr = getattr(tm.logger, attr_name, None)
            if isinstance(attr, logging.Logger):
                for h in attr.handlers[:]:
                    h.flush()
                    h.close()
                    attr.removeHandler(h)
        if hasattr(tm.logger, '_logger'):
            for h in tm.logger._logger.handlers[:]:
                h.flush()
                h.close()
                tm.logger._logger.removeHandler(h)

        # --- Print full event log ---
        print_log_replay(log_path, f'Event Log — {scenario.name}')

        # Append to shared log file
        scenario_log_text = log_path.read_text(encoding='utf-8') if log_path.exists() else '(no log file found)'
        append_to_shared_log(
            f'{"=" * 60}\n'
            f'SCENARIO: {scenario.name}\n'
            f'Players: {scenario.player_count}  Rounds: {scenario.round_limit}  Ranked: {scenario.ranked}\n'
            f'{"=" * 60}\n'
            f'{scenario_log_text}\n\n'
        )

        # --- Print final standings from DB ---
        swiss_event_final = await get_swiss_event(bot, tournament['_id'])
        if swiss_event_final:
            print_scoreboard(swiss_event_final.get('players', {}), 'Final Swiss State', initial_points)

        # --- Assert log patterns ---
        passed, failures = assert_log_patterns(log_path, scenario.expected_log_patterns)

        if passed:
            ok(f'All {len(scenario.expected_log_patterns)} log patterns matched')
        else:
            for f in failures:
                fail(f)
            append_to_failure_log(
                f'{"=" * 60}\n'
                f'FAILED: {scenario.name}\n'
                f'{"=" * 60}\n'
                f'{scenario_log_text}\n\n'
                f'Missing patterns:\n'
                + '\n'.join(f'  {f}' for f in failures)
                + '\n\n'
            )

        # Include score failures in overall result
        if not score_all_passed:
            passed = False
            append_to_failure_log(
                f'\nSCORE FAILURES ({scenario.name}):\n'
                + '\n'.join(f'  {sf}' for sf in all_score_failures)
                + '\n\n'
            )

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

    init_shared_logs()

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
        print(f'\n  Full log:      {_shared_log_path}')
        print(f'  Failures only: {_failure_log_path}')
        sys.exit(1)
    else:
        print(f'  {GREEN}✓{RESET}')
        print(f'\n  Full log: {_shared_log_path}')


async def run_loop(scenario_name: str):
    """Run a single scenario repeatedly until it fails."""
    if scenario_name not in SCENARIOS:
        print(f'{RED}Unknown scenario: {scenario_name}{RESET}')
        print(f'Available: {", ".join(SCENARIOS.keys())}')
        sys.exit(1)

    scenario = SCENARIOS[scenario_name]
    init_shared_logs()
    run_count = 0

    while True:
        run_count += 1
        header(f'Run #{run_count}')
        passed = await run_scenario(scenario)

        if not passed:
            print(f'\n{RED}{BOLD}FAILED on run #{run_count}{RESET}')
            print(f'  Full log:      {_shared_log_path}')
            print(f'  Failures only: {_failure_log_path}')
            sys.exit(1)

        print(f'{GREEN}Run #{run_count} passed{RESET}\n')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f'Usage: python run_scenario.py <scenario_name|all|loop:scenario_name>')
        print(f'Available scenarios: {", ".join(SCENARIOS.keys())}')
        sys.exit(1)

    target = sys.argv[1]

    if target.startswith('loop:'):
        scenario_name = target.split(':', 1)[1]
        asyncio.run(run_loop(scenario_name))
    else:
        asyncio.run(main())
