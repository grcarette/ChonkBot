# tests/test_swiss_pairing.py
"""
Tests for the Swiss pairing algorithm.

Covers:
- Basic pairing: 2, even, odd, single, empty player counts
- Points-based pairing: closest points paired together
- Elo tiebreaker when points are equal
- Rematch avoidance: never rematch if an alternative exists
- Forced rematch when no other option is possible
- Global optimality: greedy first-player selection does not override global cost
- Bye candidate selection: fewest points, fewest wins as tiebreaker
"""

import pytest
from tournaments.swiss_pairing import pair_players, select_bye_candidate


def make_player(discord_id, points, elo, match_history=None, dropped=False):
    return {
        'discord_id': discord_id,
        'points': float(points),
        'elo': elo,
        'wins': int(points),
        'match_history': match_history or [],
        'dropped': dropped,
    }


# ─── Basic pairing ────────────────────────────────────────────────────────────

def test_two_players_pair_together():
    players = [make_player(1, 0, 1500), make_player(2, 0, 1400)]
    pairs, unpaired = pair_players(players)
    assert len(pairs) == 1
    assert len(unpaired) == 0
    ids = {p['discord_id'] for p in pairs[0]}
    assert ids == {1, 2}


def test_even_number_all_paired():
    players = [make_player(i, 0, 1000 + i * 100) for i in range(1, 7)]
    pairs, unpaired = pair_players(players)
    assert len(pairs) == 3
    assert len(unpaired) == 0


def test_odd_number_one_unpaired():
    players = [make_player(i, 0, 1000 + i * 100) for i in range(1, 6)]
    pairs, unpaired = pair_players(players)
    assert len(pairs) == 2
    assert len(unpaired) == 1


def test_single_player_unpaired():
    players = [make_player(1, 2, 1800)]
    pairs, unpaired = pair_players(players)
    assert len(pairs) == 0
    assert len(unpaired) == 1


def test_empty_returns_empty():
    pairs, unpaired = pair_players([])
    assert pairs == []
    assert unpaired == []


def test_all_players_appear_exactly_once():
    players = [make_player(i, i % 3, 1000 + i * 50) for i in range(1, 9)]
    pairs, unpaired = pair_players(players)
    all_ids = [p['discord_id'] for pair in pairs for p in pair] + \
              [p['discord_id'] for p in unpaired]
    assert sorted(all_ids) == sorted(p['discord_id'] for p in players)


# ─── Points-based pairing ─────────────────────────────────────────────────────

def test_pairs_closest_points():
    players = [
        make_player(1, 2, 1500),
        make_player(2, 2, 1400),
        make_player(3, 0, 1600),
        make_player(4, 0, 1300),
    ]
    pairs, unpaired = pair_players(players)
    pair_id_sets = [{p['discord_id'] for p in pair} for pair in pairs]
    assert {1, 2} in pair_id_sets
    assert {3, 4} in pair_id_sets


def test_points_priority_over_elo():
    """A 2pt player should pair with another 2pt player even if elo gap is larger."""
    players = [
        make_player(1, 2, 2000),
        make_player(2, 2, 1000),
        make_player(3, 0, 1500),
        make_player(4, 0, 1400),
    ]
    pairs, unpaired = pair_players(players)
    pair_id_sets = [{p['discord_id'] for p in pair} for pair in pairs]
    assert {1, 2} in pair_id_sets


# ─── Elo tiebreaker ───────────────────────────────────────────────────────────

def test_elo_used_as_tiebreaker_when_points_equal():
    players = [
        make_player(1, 1, 1500),
        make_player(2, 1, 1480),
        make_player(3, 1, 1000),
        make_player(4, 1, 980),
    ]
    pairs, unpaired = pair_players(players)
    pair_id_sets = [{p['discord_id'] for p in pair} for pair in pairs]
    assert {1, 2} in pair_id_sets
    assert {3, 4} in pair_id_sets


# ─── Rematch avoidance ────────────────────────────────────────────────────────

def test_no_rematches_when_alternatives_exist():
    players = [
        make_player(1, 1, 1500, match_history=[2]),
        make_player(2, 0, 1400, match_history=[1]),
        make_player(3, 1, 1300),
        make_player(4, 0, 1200),
    ]
    pairs, unpaired = pair_players(players)
    for p1, p2 in pairs:
        assert p2['discord_id'] not in p1['match_history']
        assert p1['discord_id'] not in p2['match_history']


def test_rematch_forced_when_only_two_players():
    players = [
        make_player(1, 1, 1500, match_history=[2]),
        make_player(2, 0, 1400, match_history=[1]),
    ]
    pairs, unpaired = pair_players(players)
    assert len(pairs) == 1
    assert len(unpaired) == 0


def test_rematch_penalty_overrides_points_affinity():
    """Even if a rematch would be a closer points match, avoid it."""
    players = [
        make_player(1, 2, 1500, match_history=[2]),
        make_player(2, 2, 1400, match_history=[1]),
        make_player(3, 2, 1300),
        make_player(4, 2, 1200),
    ]
    pairs, unpaired = pair_players(players)
    pair_id_sets = [{p['discord_id'] for p in pair} for pair in pairs]
    assert {1, 2} not in pair_id_sets


# ─── Global optimality ────────────────────────────────────────────────────────

def test_global_optimality_avoids_two_rematches():
    """
    After 2 rounds:
      Player 3 (2pts) played 2 and 1
      Player 2 (1pt)  played 3 and 0
      Player 1 (1pt)  played 0 and 3
      Player 0 (0pts) played 1 and 2

    Greedy pairs 3 with 2 (rematch) leaving 1 vs 0 (rematch) = 2 total rematches.
    Optimal pairs 3 with 0 and 2 with 1 = 0 rematches.
    """
    players = [
        make_player(3, 2, 1300, match_history=[2, 1]),
        make_player(2, 1, 1200, match_history=[3, 0]),
        make_player(1, 1, 1100, match_history=[0, 3]),
        make_player(0, 0, 1000, match_history=[1, 2]),
    ]
    pairs, unpaired = pair_players(players)
    pair_id_sets = [{p['discord_id'] for p in pair} for pair in pairs]
    # No rematches in the optimal solution
    for p1, p2 in pairs:
        assert p2['discord_id'] not in p1['match_history'], \
            f"Rematch detected: {p1['discord_id']} vs {p2['discord_id']}"


def test_all_rematches_forces_pairings():
    """In a fully round-robined 3-player group, force rematches rather than leaving everyone unpaired."""
    players = [
        make_player(1, 2, 1500, match_history=[2, 3]),
        make_player(2, 1, 1400, match_history=[1, 3]),
        make_player(3, 0, 1300, match_history=[1, 2]),
    ]
    pairs, unpaired = pair_players(players)
    assert len(pairs) == 1
    assert len(unpaired) == 1


# ─── Bye candidate selection ──────────────────────────────────────────────────

def test_bye_candidate_is_lowest_points():
    unpaired = [make_player(1, 3, 1500), make_player(2, 1, 1400)]
    candidate = select_bye_candidate(unpaired)
    assert candidate['discord_id'] == 2


def test_bye_candidate_uses_wins_as_tiebreaker():
    unpaired = [
        make_player(1, 1, 1500),
        {**make_player(2, 1, 1400), 'wins': 0},
    ]
    candidate = select_bye_candidate(unpaired)
    assert candidate['discord_id'] == 2


def test_bye_candidate_single_player():
    unpaired = [make_player(1, 0, 1200)]
    candidate = select_bye_candidate(unpaired)
    assert candidate['discord_id'] == 1


def test_bye_candidate_empty_returns_none():
    assert select_bye_candidate([]) is None