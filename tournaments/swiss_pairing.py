"""
Swiss pairing algorithm for ChonkBot.

Pairing priority:
1. Closest points
2. Closest elo as tiebreaker
3. Never rematch

Takes a list of available player dicts and returns a list of (player1, player2)
tuples plus a list of unpaired players (0 or 1).

Each player dict must have:
    discord_id: int
    points: float
    elo: int
    match_history: list[int]   # discord_ids of past opponents
"""


def pair_players(available: list[dict]) -> tuple[list[tuple[dict, dict]], list[dict]]:
    """
    Pair available players optimally.

    Returns:
        pairs: list of (player1, player2) tuples
        unpaired: list of 0 or 1 players who could not be paired
    """
    if len(available) < 2:
        return [], list(available)

    # Sort by points descending, elo descending as tiebreaker
    # This means we try to pair the highest-pointed players first
    players = sorted(available, key=lambda p: (-p['points'], -p['elo']))

    pairs = []
    unpaired_ids = set()
    used = set()

    for i, player in enumerate(players):
        if player['discord_id'] in used:
            continue

        best_opponent = None
        best_score = None

        for j, candidate in enumerate(players):
            if i == j:
                continue
            if candidate['discord_id'] in used:
                continue
            if candidate['discord_id'] in player['match_history']:
                continue  # never rematch

            # Score this pairing — lower is better
            # Primary: absolute points difference
            # Secondary: absolute elo difference (scaled down so it doesn't
            #            override points unless points are equal)
            points_diff = abs(player['points'] - candidate['points'])
            elo_diff = abs(player['elo'] - candidate['elo'])
            score = (points_diff, elo_diff)

            if best_score is None or score < best_score:
                best_score = score
                best_opponent = candidate

        if best_opponent is not None:
            pairs.append((player, best_opponent))
            used.add(player['discord_id'])
            used.add(best_opponent['discord_id'])
        else:
            # No valid opponent found (everyone is a rematch or already used)
            unpaired_ids.add(player['discord_id'])

    unpaired = [p for p in players if p['discord_id'] in unpaired_ids and p['discord_id'] not in used]
    return pairs, unpaired


def select_bye_candidate(unpaired: list[dict]) -> dict | None:
    """
    If there is exactly one unpaired player, return them as the bye candidate.
    If somehow more than one is unpaired (all rematches scenario), pick the one
    with the fewest points, then fewest wins, to minimise bye advantage.
    """
    if not unpaired:
        return None
    return min(unpaired, key=lambda p: (p['points'], p.get('wins', 0)))