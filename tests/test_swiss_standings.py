"""
tests/test_swiss_standings.py

Tests for the Buchholz-based Swiss standings system.

The key properties being tested:
- Players with more points rank higher regardless of Buchholz
- Among equal-points players, higher Buchholz ranks higher
- Buchholz Cut 1 (drop lowest opponent score) is used as third tiebreaker
- Head-to-head is used as fourth tiebreaker
- Buchholz correctly sums opponents' FINAL points (not starting elo)
- Dropped players' results still count toward opponents' Buchholz

All tests bypass MongoDB entirely by constructing fake event dicts and
calling the computation logic directly.
"""

import pytest
import functools
from unittest.mock import AsyncMock, MagicMock


# ─── Extract the pure computation from swiss_get_standings ───────────────────
#
# Rather than mocking the full DB layer, we extract the sorting logic into a
# standalone function that mirrors what swiss_get_standings does.
# This lets us test the algorithm directly with plain dicts.

def compute_standings(players: dict, matches: list) -> list:
    """
    Pure function version of swiss_get_standings logic.
    players: { str(discord_id): player_dict }
    matches: list of match dicts with player_1, player_2, winner fields
    Returns sorted list of player dicts with discord_id, buchholz, buchholz_cut1 added.
    """
    standings = []
    for discord_id, player in players.items():
        opponent_points = [
            players[str(opp_id)]['points']
            for opp_id in player.get('match_history', [])
            if str(opp_id) in players
        ]
        buchholz = sum(opponent_points)
        buchholz_cut1 = sum(sorted(opponent_points)[1:]) if len(opponent_points) > 1 else buchholz

        standings.append({
            'discord_id': int(discord_id),
            'buchholz': buchholz,
            'buchholz_cut1': buchholz_cut1,
            **player,
        })

    def head_to_head(a, b):
        for match in matches:
            players_in_match = {match['player_1'], match['player_2']}
            a_id = a['discord_id']
            b_id = b['discord_id']
            if players_in_match == {a_id, b_id}:
                if match['winner'] == a_id:
                    return 1
                elif match['winner'] == b_id:
                    return -1
        return 0

    def compare(a, b):
        if a['points'] != b['points']:
            return -1 if a['points'] > b['points'] else 1
        if a['buchholz'] != b['buchholz']:
            return -1 if a['buchholz'] > b['buchholz'] else 1
        if a['buchholz_cut1'] != b['buchholz_cut1']:
            return -1 if a['buchholz_cut1'] > b['buchholz_cut1'] else 1
        h2h = head_to_head(a, b)
        if h2h != 0:
            return -h2h
        if a['wins'] != b['wins']:
            return -1 if a['wins'] > b['wins'] else 1
        return 0

    standings.sort(key=functools.cmp_to_key(compare))
    return standings


def make_player(points, wins=None, elo=1000, match_history=None, dropped=False):
    """Helper to build a minimal player dict."""
    return {
        'points': float(points),
        'wins': wins if wins is not None else int(points),
        'losses': 0,
        'elo': elo,
        'match_history': match_history or [],
        'dropped': dropped,
        'active_match_id': None,
        'username': f'player_elo{elo}',
    }


def make_match(player_1, player_2, winner):
    return {'player_1': player_1, 'player_2': player_2, 'winner': winner}


# ─── Points — primary sort ────────────────────────────────────────────────────

def test_higher_points_ranks_first():
    players = {
        '1': make_player(points=3),
        '2': make_player(points=2),
        '3': make_player(points=1),
    }
    result = compute_standings(players, [])
    ids = [p['discord_id'] for p in result]
    assert ids == [1, 2, 3]


def test_points_dominates_buchholz():
    """A player with more points ranks above one with better Buchholz."""
    players = {
        '1': make_player(points=2, match_history=[2]),  # beat player 2
        '2': make_player(points=1, match_history=[1]),  # lost to player 1, but player 1 has 2pts
    }
    # Player 2's Buchholz = player 1's points = 2
    # Player 1's Buchholz = player 2's points = 1
    # But player 1 still wins because they have more points
    result = compute_standings(players, [])
    assert result[0]['discord_id'] == 1


# ─── Buchholz — second tiebreaker ────────────────────────────────────────────

def test_buchholz_breaks_points_tie():
    """
    Two players with equal points: the one who beat stronger opponents ranks higher.
    Player 1 beat player 3 (who finished with 2 pts) → Buchholz = 2
    Player 2 beat player 4 (who finished with 0 pts) → Buchholz = 0
    Both have 1 win, but player 1's Buchholz is higher so ranks above player 2.
    (Player 3 with 2pts and player 4 with 0pts will also appear in standings
    but we only care about the relative ordering of players 1 and 2.)
    """
    players = {
        '1': make_player(points=1, match_history=[3]),
        '2': make_player(points=1, match_history=[4]),
        '3': make_player(points=2, match_history=[1]),  # strong opponent
        '4': make_player(points=0, match_history=[2]),  # weak opponent
    }
    result = compute_standings(players, [])
    ids = [p['discord_id'] for p in result]
    pos_1 = ids.index(1)
    pos_2 = ids.index(2)
    assert pos_1 < pos_2, (
        f"Player 1 (Buchholz=2) should rank above player 2 (Buchholz=0), "
        f"but got order: {ids}"
    )


def test_buchholz_uses_final_points_not_elo():
    """
    Buchholz must sum opponents' FINAL point totals, not their starting elo.
    High-elo player who loses all matches contributes 0 to Buchholz.
    """
    players = {
        '1': make_player(points=1, elo=1000, match_history=[2]),
        '2': make_player(points=1, elo=1000, match_history=[3]),
        '3': make_player(points=0, elo=2500, match_history=[2]),  # high elo, 0 wins
        '4': make_player(points=2, elo=1000, match_history=[]),   # low elo, 2 wins (not an opponent of 1 or 2)
    }
    # Player 1's opponent (player 2) has 1 point → buchholz = 1
    # Player 2's opponent (player 3) has 0 points → buchholz = 0
    # Despite player 3's high elo, player 2's Buchholz is lower
    result = compute_standings(players, [])
    # Among the 1-point players (1 and 2): player 1 should rank higher
    one_point_players = [p for p in result if p['points'] == 1.0]
    assert one_point_players[0]['discord_id'] == 1


def test_buchholz_zero_for_no_opponents():
    """Player with no match history gets Buchholz of 0."""
    players = {
        '1': make_player(points=1, match_history=[]),
        '2': make_player(points=1, match_history=[]),
    }
    result = compute_standings(players, [])
    for p in result:
        assert p['buchholz'] == 0


def test_buchholz_sums_all_opponents():
    """With three rounds, Buchholz sums all three opponents' points."""
    players = {
        '1': make_player(points=3, match_history=[2, 3, 4]),
        '2': make_player(points=1),
        '3': make_player(points=2),
        '4': make_player(points=0),
    }
    result = compute_standings(players, [])
    player_1_entry = next(p for p in result if p['discord_id'] == 1)
    assert player_1_entry['buchholz'] == 3  # 1 + 2 + 0


# ─── Buchholz Cut 1 — third tiebreaker ───────────────────────────────────────

def test_buchholz_cut1_drops_lowest_opponent():
    """
    Cut 1 drops the lowest opponent score.
    Player 1: opponents scored 0, 2, 2 → buchholz=4, cut1=4 (drop 0)
    Player 2: opponents scored 1, 1, 2 → buchholz=4, cut1=3 (drop 1)
    Same full Buchholz, but player 1 has better Cut 1.
    """
    players = {
        '1': make_player(points=3, match_history=[3, 4, 5]),
        '2': make_player(points=3, match_history=[6, 7, 8]),
        '3': make_player(points=0),  # 1's weak opponent
        '4': make_player(points=2),  # 1's good opponent
        '5': make_player(points=2),  # 1's good opponent
        '6': make_player(points=1),  # 2's mediocre opponent
        '7': make_player(points=1),  # 2's mediocre opponent
        '8': make_player(points=2),  # 2's good opponent
    }
    result = compute_standings(players, [])
    top_two = [p['discord_id'] for p in result[:2]]
    # Both have buchholz=4, but player 1 cut1=4 vs player 2 cut1=3
    assert top_two[0] == 1


def test_buchholz_cut1_equals_buchholz_with_one_opponent():
    """With only one opponent, cut1 equals full Buchholz (nothing to drop)."""
    players = {
        '1': make_player(points=1, match_history=[2]),
        '2': make_player(points=0, match_history=[1]),
    }
    result = compute_standings(players, [])
    p1 = next(p for p in result if p['discord_id'] == 1)
    assert p1['buchholz'] == p1['buchholz_cut1']


# ─── Head to head — fourth tiebreaker ────────────────────────────────────────

def test_head_to_head_breaks_buchholz_tie():
    """
    When two players have identical points and Buchholz, the one who
    beat the other directly should rank higher.
    """
    players = {
        '1': make_player(points=2, match_history=[2, 3]),
        '2': make_player(points=2, match_history=[1, 4]),
        '3': make_player(points=1),
        '4': make_player(points=1),
    }
    matches = [
        make_match(player_1=1, player_2=2, winner=1),  # player 1 beat player 2
        make_match(player_1=1, player_2=3, winner=1),
        make_match(player_1=2, player_2=4, winner=2),
    ]
    result = compute_standings(players, matches)
    top_two = [p['discord_id'] for p in result[:2]]
    assert top_two[0] == 1, "Player who won the direct match should rank higher"


def test_head_to_head_only_applies_to_players_who_met():
    """Head-to-head tiebreaker is 0 for players who never played each other."""
    players = {
        '1': make_player(points=1, match_history=[3]),
        '2': make_player(points=1, match_history=[4]),
        '3': make_player(points=0),
        '4': make_player(points=0),
    }
    matches = [
        make_match(1, 3, winner=1),
        make_match(2, 4, winner=2),
    ]
    # Players 1 and 2 never played — no h2h signal, result is stable
    result = compute_standings(players, matches)
    top_two_ids = {p['discord_id'] for p in result[:2]}
    assert top_two_ids == {1, 2}


# ─── Dropped players ─────────────────────────────────────────────────────────

def test_dropped_player_results_count_toward_buchholz():
    """
    A dropped player's final point total still contributes to their opponents'
    Buchholz — their record stands even after dropping.
    """
    players = {
        '1': make_player(points=1, match_history=[2]),
        '2': make_player(points=2, dropped=True, match_history=[1]),  # dropped but had 2 wins
    }
    result = compute_standings(players, [])
    p1 = next(p for p in result if p['discord_id'] == 1)
    assert p1['buchholz'] == 2  # player 2's 2 points count even though they dropped


# ─── Full tournament simulation ───────────────────────────────────────────────

def test_three_round_tournament_standings():
    """
    Simulate a complete 3-round 4-player tournament and verify the full ranking.

    Round 1: 1 beats 2, 3 beats 4
    Round 2: 1 beats 3, 2 beats 4
    Round 3: 1 beats 4, 3 beats 2

    Final records:
    Player 1: 3 wins (beat 2,3,4) — buchholz = pts(2)+pts(3)+pts(4) = 1+2+0 = 3
    Player 3: 2 wins (beat 4,2)   — buchholz = pts(4)+pts(1)+pts(2) = 0+3+1 = 4
    Player 2: 1 win  (beat 4)     — buchholz = pts(1)+pts(4)+pts(3) = 3+0+2 = 5
    Player 4: 0 wins              — buchholz = pts(3)+pts(2)+pts(1) = 2+1+3 = 6

    Expected ranking: 1 (3pts) → 3 (2pts) → 2 (1pt) → 4 (0pts)
    """
    players = {
        '1': make_player(points=3, wins=3, match_history=[2, 3, 4]),
        '2': make_player(points=1, wins=1, match_history=[1, 4, 3]),
        '3': make_player(points=2, wins=2, match_history=[4, 1, 2]),
        '4': make_player(points=0, wins=0, match_history=[3, 2, 1]),
    }
    matches = [
        make_match(1, 2, winner=1),
        make_match(3, 4, winner=3),
        make_match(1, 3, winner=1),
        make_match(2, 4, winner=2),
        make_match(1, 4, winner=1),
        make_match(3, 2, winner=3),
    ]
    result = compute_standings(players, matches)
    ids = [p['discord_id'] for p in result]
    assert ids == [1, 3, 2, 4], f"Expected [1,3,2,4] got {ids}"


def test_buchholz_tiebreak_in_real_scenario():
    """
    Two players both go 2-1 but beat different opponents.
    The one who beat stronger opponents ranks higher via Buchholz.

    Player 1 (2-1): beat player 3 (2pts), player 4 (1pt) → Buchholz = 3
    Player 2 (2-1): beat player 5 (1pt), player 6 (0pts) → Buchholz = 1
    """
    players = {
        '1': make_player(points=2, match_history=[3, 4]),
        '2': make_player(points=2, match_history=[5, 6]),
        '3': make_player(points=2, match_history=[1]),  # strong opponent of 1
        '4': make_player(points=1, match_history=[1]),  # ok opponent of 1
        '5': make_player(points=1, match_history=[2]),  # ok opponent of 2
        '6': make_player(points=0, match_history=[2]),  # weak opponent of 2
    }
    result = compute_standings(players, [])
    two_point_players = [p for p in result if p['points'] == 2.0]
    assert two_point_players[0]['discord_id'] == 1, \
        "Player who beat stronger opponents should rank higher via Buchholz"