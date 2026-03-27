# tests/integration/scenarios.py
"""
Scenario definitions for Swiss integration tests.

Each scenario defines the tournament configuration, how each round
plays out, and what log patterns must appear for the run to pass.

Log patterns are regex strings matched against each log line in order.
Use .* to match any characters, \\d+ to match numbers.
"""

from dataclasses import dataclass, field


@dataclass
class RoundBehavior:
    """
    Defines how a single round plays out.

    winners:      'first'  — player_1 always wins
                  'second' — player_2 always wins
                  'random' — random winner each match
    dropouts:     list of player indices who drop out before this round
                  is reported (triggers opponent-wins-by-default)
    dqs:          list of player indices who get DQ'd mid-round
    force_start:  if True, TO force-starts the next round even if
                  some matches haven't been reported yet
    """
    winners:     str       = 'first'
    dropouts:    list[int] = field(default_factory=list)
    dqs:         list[int] = field(default_factory=list)
    force_start: bool      = False


@dataclass
class Scenario:
    """A complete Swiss event simulation scenario."""
    name:                  str
    player_count:          int
    round_limit:           int
    ranked:                bool
    rounds:                list[RoundBehavior]
    expected_log_patterns: list[str]  # must appear in this order in the log


# ── Scenario definitions ──────────────────────────────────────────────────────

SCENARIOS: dict[str, Scenario] = {}


def register(scenario: Scenario) -> Scenario:
    SCENARIOS[scenario.name] = scenario
    return scenario


# ── 1. Happy path ─────────────────────────────────────────────────────────────

register(Scenario(
    name='happy_path',
    player_count=8,
    round_limit=3,
    ranked=True,
    rounds=[
        RoundBehavior(winners='first'),
        RoundBehavior(winners='first'),
        RoundBehavior(winners='first'),
    ],
    expected_log_patterns=[
        r'\[STATE\] registration → active',
        r'\[SWISS\] Round 1 started — 8 players, 4 matches',
        r'\[SWISS\] Match \S+ reported — winner: \S+, loser: \S+',
        r'\[SWISS\] Match \S+ reported — winner: \S+, loser: \S+',
        r'\[SWISS\] Match \S+ reported — winner: \S+, loser: \S+',
        r'\[SWISS\] Match \S+ reported — winner: \S+, loser: \S+',
        r'\[SWISS\] Round 1 complete',
        r'\[RANKED\] Reported — winner: \S+, loser: \S+',
        r'\[RANKED\] Reported — winner: \S+, loser: \S+',
        r'\[RANKED\] Reported — winner: \S+, loser: \S+',
        r'\[RANKED\] Reported — winner: \S+, loser: \S+',
        r'\[SWISS\] Round 2 started — 8 players, 4 matches',
        r'\[SWISS\] Round 2 complete',
        r'\[RANKED\] Reported — winner: \S+, loser: \S+',
        r'\[RANKED\] Reported — winner: \S+, loser: \S+',
        r'\[RANKED\] Reported — winner: \S+, loser: \S+',
        r'\[RANKED\] Reported — winner: \S+, loser: \S+',
        r'\[SWISS\] Round 3 started — 8 players, 4 matches',
        r'\[SWISS\] Round 3 complete',
        r'\[STATE\] active → finished',
    ],
))


# ── 2. Odd player count (bye every round) ─────────────────────────────────────

register(Scenario(
    name='odd_players',
    player_count=7,
    round_limit=3,
    ranked=False,
    rounds=[
        RoundBehavior(winners='first'),
        RoundBehavior(winners='first'),
        RoundBehavior(winners='first'),
    ],
    expected_log_patterns=[
        r'\[STATE\] registration → active',
        r'\[SWISS\] Round 1 started — 7 players, 3 matches',
        r'\[SWISS\] Bye awarded to \S+',
        r'\[SWISS\] Round 1 complete',
        r'\[SWISS\] Round 2 started — 7 players, 3 matches',
        r'\[SWISS\] Bye awarded to \S+',
        r'\[SWISS\] Round 2 complete',
        r'\[SWISS\] Round 3 started — 7 players, 3 matches',
        r'\[SWISS\] Bye awarded to \S+',
        r'\[SWISS\] Round 3 complete',
        r'\[STATE\] active → finished',
    ],
))


# ── 3. Mid-round dropout ──────────────────────────────────────────────────────

register(Scenario(
    name='mid_round_dropout',
    player_count=8,
    round_limit=2,
    ranked=False,
    rounds=[
        # Player index 0 drops mid-round-1, triggering opponent wins by default
        RoundBehavior(winners='first', dropouts=[0]),
        # Round 2 has 7 remaining players (player 0 dropped), bye expected
        RoundBehavior(winners='first'),
    ],
    expected_log_patterns=[
        r'\[STATE\] registration → active',
        r'\[SWISS\] Round 1 started — 8 players, 4 matches',
        r'\[REGISTRATION\] \S+ dropped',
        r'\[SWISS\] Round 1 complete',
        r'\[SWISS\] Round 2 started — 7 players, 3 matches',
        r'\[SWISS\] Bye awarded to \S+',
        r'\[SWISS\] Round 2 complete',
        r'\[STATE\] active → finished',
    ],
))


# ── 4. DQ mid-round ───────────────────────────────────────────────────────────

register(Scenario(
    name='dq_mid_round',
    player_count=8,
    round_limit=2,
    ranked=False,
    rounds=[
        # Player index 1 gets DQ'd during round 1
        RoundBehavior(winners='first', dqs=[1]),
        RoundBehavior(winners='first'),
    ],
    expected_log_patterns=[
        r'\[STATE\] registration → active',
        r'\[SWISS\] Round 1 started — 8 players, 4 matches',
        r'\[DQ\] Player \S+ disqualified — active match ended, \S+ wins by default',
        r'\[SWISS\] Round 1 complete',
        r'\[SWISS\] Round 2 started',
        r'\[SWISS\] Round 2 complete',
        r'\[STATE\] active → finished',
    ],
))


# ── 5. Force start next round ─────────────────────────────────────────────────

register(Scenario(
    name='force_start',
    player_count=8,
    round_limit=2,
    ranked=False,
    rounds=[
        # Round 1 — last match never gets reported, TO force-starts round 2
        RoundBehavior(winners='first', force_start=True),
        RoundBehavior(winners='first'),
    ],
    expected_log_patterns=[
        r'\[STATE\] registration → active',
        r'\[SWISS\] Round 1 started — 8 players, 4 matches',
        # Only 3 of 4 matches reported before force-start
        r'\[SWISS\] Match \S+ reported',
        r'\[SWISS\] Match \S+ reported',
        r'\[SWISS\] Match \S+ reported',
        r'\[SWISS\] Round 2 started',
        r'\[SWISS\] Round 2 complete',
        r'\[STATE\] active → finished',
    ],
))


# ── 6. Ranked API failure ─────────────────────────────────────────────────────

register(Scenario(
    name='ranked_api_failure',
    player_count=4,
    round_limit=1,
    ranked=True,
    rounds=[
        RoundBehavior(winners='first'),
    ],
    expected_log_patterns=[
        r'\[STATE\] registration → active',
        r'\[SWISS\] Round 1 started — 4 players, 2 matches',
        r'\[SWISS\] Round 1 complete',
        # Ranked failures should be logged as errors
        r'\[ERROR\].*\[RANKED\] API failure',
        r'\[ERROR\].*\[RANKED\] API failure',
    ],
))
