"""
Swiss pairing algorithm for ChonkBot.

Uses minimum-weight perfect matching to find the globally optimal pairing,
rather than a greedy approach that can produce suboptimal results.

Pairing cost (lower is better):
1. Rematch penalty (highest priority — avoid at all costs)
2. Points difference (pair closest points)
3. Elo difference (tiebreaker)

Each player dict must have:
    discord_id: int
    points: float
    elo: int
    match_history: list[int]   # discord_ids of past opponents
"""

import itertools


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
    total_rematch   = sum(c[0] for c in (_pairing_cost(a, b) for a, b in pairs))
    total_points    = sum(c[1] for c in (_pairing_cost(a, b) for a, b in pairs))
    total_elo       = sum(c[2] for c in (_pairing_cost(a, b) for a, b in pairs))
    return (total_rematch, total_points, total_elo)


def _all_perfect_matchings(players: list[dict]) -> list[list[tuple[dict, dict]]]:
    """
    Generate all possible perfect matchings for an even-length player list.
    For n players this is (n-1)!! matchings. Scales fine up to ~16 players;
    for larger fields the search space grows but Swiss events are typically ≤32.
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


def pair_players(available: list[dict]) -> tuple[list[tuple[dict, dict]], list[dict]]:
    """
    Pair available players using globally optimal minimum-cost matching.

    For odd player counts, tries removing each player as the unpaired candidate
    and picks the removal that yields the best pairing for the rest.

    Returns:
        pairs:    list of (player1, player2) tuples
        unpaired: list of 0 or 1 players
    """
    if len(available) < 2:
        return [], list(available)

    # Sort by points desc, elo desc for deterministic ordering
    players = sorted(available, key=lambda p: (-p['points'], -p['elo']))

    if len(players) % 2 == 0:
        # Even — find the globally optimal perfect matching
        best_matching = None
        best_cost     = None

        for matching in _all_perfect_matchings(players):
            cost = _total_cost(matching)
            if best_cost is None or cost < best_cost:
                best_cost     = cost
                best_matching = matching

        return best_matching, []

    else:
        # Odd — try each player as the bye candidate, pick best result
        best_matching  = None
        best_cost      = None
        best_unpaired  = None

        for i, bye_candidate in enumerate(players):
            remaining = players[:i] + players[i+1:]
            for matching in _all_perfect_matchings(remaining):
                cost = _total_cost(matching)
                if best_cost is None or cost < best_cost:
                    best_cost     = cost
                    best_matching = matching
                    best_unpaired = bye_candidate

        return best_matching, [best_unpaired]


def select_bye_candidate(unpaired: list[dict]) -> dict | None:
    """
    If there is exactly one unpaired player, return them as the bye candidate.
    If somehow more than one is unpaired (shouldn't happen with new algorithm),
    pick the one with fewest points, then fewest wins.
    """
    if not unpaired:
        return None
    return min(unpaired, key=lambda p: (p['points'], p.get('wins', 0)))