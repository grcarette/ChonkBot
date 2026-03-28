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
class ScoreCheck:
    """
    Expected score state for a player at a checkpoint.

    Any field set to None means "don't check this field".
    """
    player_id:     int
    points:        float | None = None
    wins:          int   | None = None
    losses:        int   | None = None
    rounds_played: int   | None = None
    dropped:       bool  | None = None


@dataclass
class Scenario:
    """A complete Swiss event simulation scenario."""
    name:                  str
    player_count:          int
    round_limit:           int
    ranked:                bool
    rounds:                list[RoundBehavior]
    expected_log_patterns: list[str]  # must appear in this order in the log
    score_checks:          dict[int, list[ScoreCheck]] = field(default_factory=dict)
    # score_checks maps round_number → list of ScoreChecks to verify after that round
    # round 0 = after setup but before any rounds (verifies elo bonus)


# ── Scenario definitions ──────────────────────────────────────────────────────

SCENARIOS: dict[str, Scenario] = {}


def register(scenario: Scenario) -> Scenario:
    SCENARIOS[scenario.name] = scenario
    return scenario


# ── 1. Happy path ─────────────────────────────────────────────────────────────
#
# 8 players, 3 rounds, ranked, player_1 always wins.
#
# Debug elo assignments (user_id % 8):
#   Player 1 → elo 2200 (tier 1, +2 bonus)
#   Player 2 → elo 1600 (tier 2, +1 bonus)
#   Player 3 → elo 1500 (tier 2, +1 bonus)
#   Player 4 → elo 1100 (tier 3, +0 bonus)
#   Player 5 → elo 1000 (tier 3, +0 bonus)
#   Player 6 → elo  900 (tier 3, +0 bonus)
#   Player 7 → elo  800 (tier 3, +0 bonus)
#   Player 8 → elo 2100 (tier 1, +2 bonus)  (8 % 8 = 0)

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
        r'\[SWISS\] Round 2 started — 8 players, 4 matches',
        r'\[RANKED\] Reported — winner: \S+, loser: \S+',
        r'\[RANKED\] Reported — winner: \S+, loser: \S+',
        r'\[RANKED\] Reported — winner: \S+, loser: \S+',
        r'\[RANKED\] Reported — winner: \S+, loser: \S+',
        r'\[SWISS\] Round 2 complete',
        r'\[SWISS\] Round 3 started — 8 players, 4 matches',
        r'\[RANKED\] Reported — winner: \S+, loser: \S+',
        r'\[RANKED\] Reported — winner: \S+, loser: \S+',
        r'\[RANKED\] Reported — winner: \S+, loser: \S+',
        r'\[RANKED\] Reported — winner: \S+, loser: \S+',
        r'\[SWISS\] Round 3 complete',
        r'\[STATE\] active → finished',
    ],
    score_checks={
        # Round 0 — verify elo bonus only (before any matches)
        0: [
            ScoreCheck(1, points=2.0, wins=0, losses=0, rounds_played=0),
            ScoreCheck(2, points=1.0, wins=0, losses=0, rounds_played=0),
            ScoreCheck(3, points=1.0, wins=0, losses=0, rounds_played=0),
            ScoreCheck(4, points=0.0, wins=0, losses=0, rounds_played=0),
            ScoreCheck(5, points=0.0, wins=0, losses=0, rounds_played=0),
            ScoreCheck(6, points=0.0, wins=0, losses=0, rounds_played=0),
            ScoreCheck(7, points=0.0, wins=0, losses=0, rounds_played=0),
            ScoreCheck(8, points=2.0, wins=0, losses=0, rounds_played=0),
        ],
        # After each round: every player should have rounds_played == round_num
        1: [
            ScoreCheck(1, rounds_played=1),
            ScoreCheck(2, rounds_played=1),
            ScoreCheck(3, rounds_played=1),
            ScoreCheck(4, rounds_played=1),
            ScoreCheck(5, rounds_played=1),
            ScoreCheck(6, rounds_played=1),
            ScoreCheck(7, rounds_played=1),
            ScoreCheck(8, rounds_played=1),
        ],
        2: [
            ScoreCheck(1, rounds_played=2),
            ScoreCheck(2, rounds_played=2),
            ScoreCheck(3, rounds_played=2),
            ScoreCheck(4, rounds_played=2),
            ScoreCheck(5, rounds_played=2),
            ScoreCheck(6, rounds_played=2),
            ScoreCheck(7, rounds_played=2),
            ScoreCheck(8, rounds_played=2),
        ],
        3: [
            ScoreCheck(1, rounds_played=3),
            ScoreCheck(2, rounds_played=3),
            ScoreCheck(3, rounds_played=3),
            ScoreCheck(4, rounds_played=3),
            ScoreCheck(5, rounds_played=3),
            ScoreCheck(6, rounds_played=3),
            ScoreCheck(7, rounds_played=3),
            ScoreCheck(8, rounds_played=3),
        ],
    },
))


# ── 2. Odd player count (bye every round) ─────────────────────────────────────
#
# 7 players, 3 rounds, unranked. One player gets a bye each round.
# Bye candidate = fewest points, fewest wins tiebreaker.

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
    score_checks={
        0: [
            # Player 1 → elo 2200 (tier 1, +2), Player 2 → 1600 (tier 2, +1)
            # Player 3 → 1500 (tier 2, +1), Player 4 → 1100 (tier 3, +0)
            # Player 5 → 1000 (tier 3, +0), Player 6 → 900 (tier 3, +0)
            # Player 7 → 800 (tier 3, +0)
            ScoreCheck(1, points=2.0, wins=0, losses=0, rounds_played=0),
            ScoreCheck(2, points=1.0, wins=0, losses=0, rounds_played=0),
            ScoreCheck(3, points=1.0, wins=0, losses=0, rounds_played=0),
            ScoreCheck(4, points=0.0, wins=0, losses=0, rounds_played=0),
            ScoreCheck(5, points=0.0, wins=0, losses=0, rounds_played=0),
            ScoreCheck(6, points=0.0, wins=0, losses=0, rounds_played=0),
            ScoreCheck(7, points=0.0, wins=0, losses=0, rounds_played=0),
        ],
        # After each round: all 7 players should have played (6 matched + 1 bye)
        1: [
            ScoreCheck(1, rounds_played=1),
            ScoreCheck(2, rounds_played=1),
            ScoreCheck(3, rounds_played=1),
            ScoreCheck(4, rounds_played=1),
            ScoreCheck(5, rounds_played=1),
            ScoreCheck(6, rounds_played=1),
            ScoreCheck(7, rounds_played=1),
        ],
    },
))


# ── 3. Mid-round dropout ──────────────────────────────────────────────────────
#
# 8 players, 2 rounds. Player 1 drops mid-round-1.
# Opponent gets a default win, player 1 is marked dropped.
# Round 2 has 7 remaining players → bye expected.

register(Scenario(
    name='mid_round_dropout',
    player_count=8,
    round_limit=2,
    ranked=False,
    rounds=[
        RoundBehavior(winners='first', dropouts=[0]),
        RoundBehavior(winners='first'),
    ],
    expected_log_patterns=[
        r'\[STATE\] registration → active',
        r'\[SWISS\] Round 1 started — 8 players, 4 matches',
        r'\[SWISS\] Match \S+ reported — winner: \S+, loser: \S+',
        r'\[REGISTRATION\] .+ dropped',
        r'\[SWISS\] Round 1 complete',
        r'\[SWISS\] Round 2 started — 7 players, 3 matches',
        r'\[SWISS\] Bye awarded to \S+',
        r'\[SWISS\] Round 2 complete',
        r'\[STATE\] active → finished',
    ],
    score_checks={
        1: [
            # Player 1 dropped — should be marked dropped
            ScoreCheck(1, dropped=True),
            # All other players should have rounds_played=1
            ScoreCheck(2, rounds_played=1),
            ScoreCheck(3, rounds_played=1),
            ScoreCheck(4, rounds_played=1),
            ScoreCheck(5, rounds_played=1),
            ScoreCheck(6, rounds_played=1),
            ScoreCheck(7, rounds_played=1),
            ScoreCheck(8, rounds_played=1),
        ],
    },
))


# ── 4. DQ mid-round ───────────────────────────────────────────────────────────
#
# 8 players, 2 rounds. Player 2 gets DQ'd during round 1.
# Opponent wins by default. DQ'd player gets -1 point penalty.

register(Scenario(
    name='dq_mid_round',
    player_count=8,
    round_limit=2,
    ranked=False,
    rounds=[
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
    score_checks={
        1: [
            # Player 2 (index 1) was DQ'd — should have -1 point penalty
            # Elo bonus for player 2 = 1.0 (tier 2), then -1 for DQ loss = 0.0
            ScoreCheck(2, losses=1, rounds_played=1),
        ],
    },
))


# ── 5. Force start next round ─────────────────────────────────────────────────
#
# 8 players, 2 rounds. Round 1: last match never reported, TO force-starts.
# 3 of 4 matches reported, then round 2 starts.

register(Scenario(
    name='force_start',
    player_count=8,
    round_limit=2,
    ranked=False,
    rounds=[
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
#
# 4 players, 1 round, ranked. MockRankedAPI always fails.
# Results should still be recorded in swiss DB, but ranked reports fail.

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
        r'\[SWISS\] Match \S+ reported — winner: \S+, loser: \S+',
        r'\[SWISS\] Match \S+ reported — winner: \S+, loser: \S+',
        r'\[ERROR\].*\[RANKED\] API failure',
        r'\[ERROR\].*\[RANKED\] API failure',
        r'\[SWISS\] Round 1 complete',
        r'\[STATE\] active → finished',
    ],
    score_checks={
        0: [
            # Player 1 → elo 2200 (tier 1, +2), Player 2 → 1600 (tier 2, +1)
            # Player 3 → 1500 (tier 2, +1), Player 4 → 1100 (tier 3, +0)
            ScoreCheck(1, points=2.0, wins=0, losses=0, rounds_played=0),
            ScoreCheck(2, points=1.0, wins=0, losses=0, rounds_played=0),
            ScoreCheck(3, points=1.0, wins=0, losses=0, rounds_played=0),
            ScoreCheck(4, points=0.0, wins=0, losses=0, rounds_played=0),
        ],
        # After round 1: all players played, ranked failures don't affect swiss scores
        1: [
            ScoreCheck(1, rounds_played=1),
            ScoreCheck(2, rounds_played=1),
            ScoreCheck(3, rounds_played=1),
            ScoreCheck(4, rounds_played=1),
        ],
    },
))

# ── 7. Chaos — stress test with mixed behavior ────────────────────────────────
#
# 10 players, 4 rounds, ranked.
# Round 1: random winners, player 10 drops mid-round
# Round 2: random winners, player 9 gets DQ'd (9 remaining → 8 active → bye)
# Round 3: random winners, player 8 drops (8 remaining → 7 active → bye)
# Round 4: player_2 always wins, no disruptions, 7 remaining → bye
#
# This scenario exercises:
#   - Random winner selection (non-deterministic pairings)
#   - Mid-round dropout with active match resolution
#   - Mid-round DQ with point penalty
#   - Bye logic triggered by drops reducing to odd count
#   - Ranked reporting across chaotic rounds
#   - Score accumulation under compounding disruptions
#
# Debug elo assignments (user_id % 8):
#   Player 1  → 2200 (T1, +2)    Player 6  → 900  (T3, +0)
#   Player 2  → 1600 (T2, +1)    Player 7  → 800  (T3, +0)
#   Player 3  → 1500 (T2, +1)    Player 8  → 2100 (T1, +2)  (8%8=0)
#   Player 4  → 1100 (T3, +0)    Player 9  → 2200 (T1, +2)  (9%8=1)
#   Player 5  → 1000 (T3, +0)    Player 10 → 1600 (T2, +1)  (10%8=2)

register(Scenario(
    name='chaos',
    player_count=10,
    round_limit=4,
    ranked=True,
    rounds=[
        # Round 1: random winners, player 10 (index 9) drops mid-round
        RoundBehavior(winners='random', dropouts=[9]),
        # Round 2: random winners, player 9 (index 8) gets DQ'd
        RoundBehavior(winners='random', dqs=[8]),
        # Round 3: random winners, player 8 (index 7) drops
        RoundBehavior(winners='random', dropouts=[7]),
        # Round 4: player_2 always wins, clean round
        RoundBehavior(winners='second'),
    ],
    expected_log_patterns=[
        r'\[STATE\] registration → active',
        # Round 1: 10 players, player 10 drops
        r'\[SWISS\] Round 1 started — 10 players, 5 matches',
        r'\[SWISS\] Match \S+ reported — winner: \S+, loser: \S+',
        r'\[REGISTRATION\] .+ dropped',
        r'\[SWISS\] Round 1 complete',
        # Round 2: 9 remaining, player 9 DQ'd
        r'\[SWISS\] Round 2 started — 9 players',
        r'\[DQ\] Player \S+ disqualified',
        r'\[SWISS\] Round 2 complete',
        # Round 3: 8 remaining (9 minus DQ), player 8 drops → 7 active → bye
        r'\[SWISS\] Round 3 started',
        r'\[REGISTRATION\] .+ dropped',
        r'\[SWISS\] Round 3 complete',
        # Round 4: 7 remaining → bye
        r'\[SWISS\] Round 4 started — 7 players',
        r'\[SWISS\] Bye awarded to \S+',
        r'\[SWISS\] Round 4 complete',
        r'\[STATE\] active → finished',
    ],
    score_checks={
        # Round 0: elo bonuses only
        0: [
            ScoreCheck(1,  points=2.0, wins=0, losses=0, rounds_played=0),
            ScoreCheck(2,  points=1.0, wins=0, losses=0, rounds_played=0),
            ScoreCheck(3,  points=1.0, wins=0, losses=0, rounds_played=0),
            ScoreCheck(4,  points=0.0, wins=0, losses=0, rounds_played=0),
            ScoreCheck(5,  points=0.0, wins=0, losses=0, rounds_played=0),
            ScoreCheck(6,  points=0.0, wins=0, losses=0, rounds_played=0),
            ScoreCheck(7,  points=0.0, wins=0, losses=0, rounds_played=0),
            ScoreCheck(8,  points=2.0, wins=0, losses=0, rounds_played=0),
            ScoreCheck(9,  points=2.0, wins=0, losses=0, rounds_played=0),
            ScoreCheck(10, points=1.0, wins=0, losses=0, rounds_played=0),
        ],
        # After round 1: everyone played 1 round, player 10 dropped
        1: [
            ScoreCheck(1,  rounds_played=1),
            ScoreCheck(2,  rounds_played=1),
            ScoreCheck(3,  rounds_played=1),
            ScoreCheck(4,  rounds_played=1),
            ScoreCheck(5,  rounds_played=1),
            ScoreCheck(6,  rounds_played=1),
            ScoreCheck(7,  rounds_played=1),
            ScoreCheck(8,  rounds_played=1),
            ScoreCheck(9,  rounds_played=1),
            ScoreCheck(10, dropped=True),
        ],
        # After round 2: survivors played 2, player 9 DQ'd with loss
        2: [
            ScoreCheck(1, rounds_played=2),
            ScoreCheck(2, rounds_played=2),
            ScoreCheck(3, rounds_played=2),
            ScoreCheck(4, rounds_played=2),
            ScoreCheck(5, rounds_played=2),
            ScoreCheck(6, rounds_played=2),
            ScoreCheck(7, rounds_played=2),
            ScoreCheck(8, rounds_played=2),
            ScoreCheck(9, rounds_played=2),
        ],
        # After round 3: survivors played 3, player 8 dropped
        3: [
            ScoreCheck(1, rounds_played=3),
            ScoreCheck(2, rounds_played=3),
            ScoreCheck(3, rounds_played=3),
            ScoreCheck(4, rounds_played=3),
            ScoreCheck(5, rounds_played=3),
            ScoreCheck(6, rounds_played=3),
            ScoreCheck(7, rounds_played=3),
            ScoreCheck(8, dropped=True),
        ],
        # After round 4: survivors played 4
        4: [
            ScoreCheck(1, rounds_played=4),
            ScoreCheck(2, rounds_played=4),
            ScoreCheck(3, rounds_played=4),
            ScoreCheck(4, rounds_played=4),
            ScoreCheck(5, rounds_played=4),
            ScoreCheck(6, rounds_played=4),
            ScoreCheck(7, rounds_played=4),
        ],
    },
))