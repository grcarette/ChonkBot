"""
Swiss pairing algorithm for ChonkBot.

Fold pairing: within each point group, the best player faces the worst
(seed 1 vs seed N, seed 2 vs seed N-1, etc). When seeds are not set,
falls back to elo-based fold pairing.

For small fields (≤ EXHAUSTIVE_THRESHOLD): uses minimum-weight perfect
matching over all possible pairings — globally optimal but O((n-1)!!).

For larger fields: uses a greedy fold approach — group by points, fold-pair
within each group, with rematch avoidance.

Pairing cost (lower is better):
1. Rematch penalty (highest priority — avoid at all costs)
2. Points difference (pair within same point group)
3. Negative skill difference (within a point group, MAXIMIZE gap = fold)
   Uses seed gap when seeds are set; elo gap otherwise.

Each player dict must have:
    discord_id: int | str
    points: float
    elo: int
    match_history: list   # discord_ids of past opponents
Optional:
    seed: int   # tournament seed (1 = best); enables seed-based fold pairing
"""

EXHAUSTIVE_THRESHOLD = 10


def _skill_diff(p1: dict, p2: dict) -> float:
    """
    Return a skill gap value for fold pairing. Larger = further apart.

    Uses seed when both players have one (seed 1 = best, higher = worse),
    otherwise falls back to elo difference.
    """
    s1 = p1.get('seed')
    s2 = p2.get('seed')
    if s1 is not None and s2 is not None:
        return abs(s1 - s2)
    return abs(p1['elo'] - p2['elo'])


def _pairing_cost(p1: dict, p2: dict) -> tuple:
    """
    Return a cost tuple for pairing two players. Lower is better.

    Within the same point group (points_diff == 0), we NEGATE the skill
    difference so the optimizer prefers the widest gap — this produces
    fold pairings (seed 1 vs seed N, seed 2 vs seed N-1, etc.).

    Across point groups the skill component is irrelevant since the
    points_diff term already dominates.
    """
    is_rematch = p2['discord_id'] in p1['match_history']
    points_diff = abs(p1['points'] - p2['points'])

    return (
        1000 if is_rematch else 0,
        points_diff,
        -_skill_diff(p1, p2),   # negative = prefer LARGE skill gaps (fold)
    )


def _total_cost(pairs: list[tuple[dict, dict]]) -> tuple:
    """Sum costs across all pairs for global comparison."""
    costs = [_pairing_cost(a, b) for a, b in pairs]
    return (
        sum(c[0] for c in costs),
        sum(c[1] for c in costs),
        sum(c[2] for c in costs),
    )


def _all_perfect_matchings(players: list[dict]) -> list[list[tuple[dict, dict]]]:
    """
    Generate all possible perfect matchings for an even-length player list.
    Only call this for small fields — complexity is O((n-1)!!).
    """
    if len(players) == 0:
        return [[]]
    if len(players) == 2:
        return [[(players[0], players[1])]]

    first = players[0]
    rest  = players[1:]
    matchings = []
    for i, partner in enumerate(rest):
        remaining = rest[:i] + rest[i+1:]
        for sub_matching in _all_perfect_matchings(remaining):
            matchings.append([(first, partner)] + sub_matching)
    return matchings


def _greedy_pair(players: list[dict]) -> list[tuple[dict, dict]]:
    """
    Fold pairing for large fields.

    For each unmatched player (taken from the top of the sorted list),
    find the best partner: same point group, maximum elo distance,
    no rematch. This naturally produces fold pairings — the strongest
    player in a group gets paired with the weakest.
    """
    remaining = list(players)  # already sorted by points desc, then seed/elo
    pairs = []

    while len(remaining) >= 2:
        p1 = remaining.pop(0)

        # Score each candidate: (rematch_penalty, points_diff, -skill_diff)
        best_idx = 0
        best_cost = _pairing_cost(p1, remaining[0])

        for i in range(1, len(remaining)):
            cost = _pairing_cost(p1, remaining[i])
            if cost < best_cost:
                best_cost = cost
                best_idx = i

        partner = remaining.pop(best_idx)
        pairs.append((p1, partner))

    return pairs


def pair_players(available: list[dict]) -> tuple[list[tuple[dict, dict]], list[dict]]:
    """
    Pair available players using fold pairing within point groups.

    For fields ≤ EXHAUSTIVE_THRESHOLD: exhaustive global optimum.
    For larger fields: greedy fold with rematch avoidance.

    For odd player counts, the bye candidate is selected first (fewest points,
    fewest wins as tiebreaker), then the remaining even field is paired.

    Returns:
        pairs:    list of (player1, player2) tuples
        unpaired: list of 0 or 1 players (the bye candidate)
    """
    if len(available) < 2:
        return [], list(available)

    # Sort: best points first, then by seed ascending (1 = best) when seeds
    # are set, or elo descending (higher = better) as fallback.
    use_seeds = any(p.get('seed') is not None for p in available)
    if use_seeds:
        players = sorted(available, key=lambda p: (-p['points'], p.get('seed', 9999)))
    else:
        players = sorted(available, key=lambda p: (-p['points'], -p['elo']))

    # Handle odd count — pull bye candidate out first
    unpaired = []
    if len(players) % 2 == 1:
        bye = select_bye_candidate(players)
        players = [p for p in players if p['discord_id'] != bye['discord_id']]
        unpaired = [bye]

    if len(players) == 0:
        return [], unpaired

    if len(players) <= EXHAUSTIVE_THRESHOLD:
        best_matching = None
        best_cost     = None
        for matching in _all_perfect_matchings(players):
            cost = _total_cost(matching)
            if best_cost is None or cost < best_cost:
                best_cost     = cost
                best_matching = matching
        return best_matching, unpaired
    else:
        pairs = _greedy_pair(players)
        return pairs, unpaired


def select_bye_candidate(unpaired: list[dict]) -> dict | None:
    """
    Select the bye candidate:
    1. Prefer players who have NOT had a bye yet
    2. Fewest points
    3. Fewest wins as tiebreaker
    """
    if not unpaired:
        return None
    return min(unpaired, key=lambda p: (
        p.get('has_bye', False),
        p['points'],
        p.get('wins', 0),
    ))