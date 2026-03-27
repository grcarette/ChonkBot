"""
Swiss pairing algorithm for ChonkBot.

For small fields (≤ EXHAUSTIVE_THRESHOLD players): uses minimum-weight perfect
matching over all possible pairings — globally optimal but O((n-1)!!).

For larger fields: uses a fast greedy approach — sort by points desc, pair
adjacent players, with rematch avoidance by swapping down the list.

Pairing cost (lower is better):
1. Rematch penalty (highest priority — avoid at all costs)
2. Points difference (pair closest points)
3. Elo difference (tiebreaker)

Each player dict must have:
    discord_id: int | str
    points: float
    elo: int
    match_history: list   # discord_ids of past opponents
"""

EXHAUSTIVE_THRESHOLD = 10  # use exhaustive matching for fields this size or smaller


def _pairing_cost(p1: dict, p2: dict) -> tuple:
    """Return a (rematch_penalty, points_diff, elo_diff) cost tuple for a pair."""
    is_rematch = p2['discord_id'] in p1['match_history']
    return (
        1000 if is_rematch else 0,
        abs(p1['points'] - p2['points']),
        abs(p1['elo'] - p2['elo']),
    )


def _total_cost(pairs: list[tuple[dict, dict]]) -> tuple:
    """Sum costs across all pairs for global comparison."""
    total_rematch = sum(c[0] for c in (_pairing_cost(a, b) for a, b in pairs))
    total_points  = sum(c[1] for c in (_pairing_cost(a, b) for a, b in pairs))
    total_elo     = sum(c[2] for c in (_pairing_cost(a, b) for a, b in pairs))
    return (total_rematch, total_points, total_elo)


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
    Greedy pairing for large fields. Players are pre-sorted by points desc.
    Pair adjacent players, then attempt single swaps to eliminate rematches.
    """
    remaining = list(players)
    pairs = []

    while len(remaining) >= 2:
        p1 = remaining.pop(0)
        # Find the best partner: first non-rematch adjacent player
        partner_idx = None
        for i, candidate in enumerate(remaining):
            if candidate['discord_id'] not in p1['match_history']:
                partner_idx = i
                break

        if partner_idx is None:
            # All remaining players are rematches — just take the closest
            partner_idx = 0

        partner = remaining.pop(partner_idx)
        pairs.append((p1, partner))

    return pairs


def pair_players(available: list[dict]) -> tuple[list[tuple[dict, dict]], list[dict]]:
    """
    Pair available players optimally.

    For fields ≤ EXHAUSTIVE_THRESHOLD: exhaustive global optimum.
    For larger fields: fast greedy with rematch avoidance.

    For odd player counts, the bye candidate is selected first (fewest points,
    fewest wins as tiebreaker), then the remaining even field is paired.

    Returns:
        pairs:    list of (player1, player2) tuples
        unpaired: list of 0 or 1 players (the bye candidate)
    """
    if len(available) < 2:
        return [], list(available)

    # Sort by points desc, elo desc for deterministic ordering
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
        # Exhaustive: find globally optimal matching
        best_matching = None
        best_cost     = None
        for matching in _all_perfect_matchings(players):
            cost = _total_cost(matching)
            if best_cost is None or cost < best_cost:
                best_cost     = cost
                best_matching = matching
        return best_matching, unpaired
    else:
        # Greedy: fast O(n log n) approach
        pairs = _greedy_pair(players)
        return pairs, unpaired


def select_bye_candidate(unpaired: list[dict]) -> dict | None:
    """
    Select the bye candidate: fewest points, fewest wins as tiebreaker.
    """
    if not unpaired:
        return None
    return min(unpaired, key=lambda p: (p['points'], p.get('wins', 0)))