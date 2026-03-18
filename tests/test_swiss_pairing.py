import pytest
from tournaments.swiss_pairing import pair_players, select_bye_candidate


def make_player(discord_id, points, elo, match_history=None):
    return {
        'discord_id': discord_id,
        'points': float(points),
        'elo': elo,
        'wins': int(points),
        'match_history': match_history or [],
    }


# ─── Basic pairing ────────────────────────────────────────────────────────────

def test_two_players_pair_together():
    players = [
        make_player(1, 1, 1500),
        make_player(2, 1, 1400),
    ]
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


# ─── Points-based pairing ─────────────────────────────────────────────────────

def test_pairs_closest_points():
    """Players with equal points should be paired together."""
    players = [
        make_player(1, 2, 1500),   # 2 pts
        make_player(2, 2, 1400),   # 2 pts
        make_player(3, 0, 1600),   # 0 pts
        make_player(4, 0, 1300),   # 0 pts
    ]
    pairs, unpaired = pair_players(players)
    assert len(pairs) == 2
    pair_id_sets = [{p['discord_id'] for p in pair} for pair in pairs]
    assert {1, 2} in pair_id_sets
    assert {3, 4} in pair_id_sets


def test_staggered_bonus_points_pair_correctly():
    """Tier 1 players (2pts) should pair together, tier 3 (0pts) together."""
    players = [
        make_player(1, 2, 2100),   # tier 1
        make_player(2, 2, 2200),   # tier 1
        make_player(3, 0, 1200),   # tier 3
        make_player(4, 0, 1100),   # tier 3
    ]
    pairs, unpaired = pair_players(players)
    pair_id_sets = [{p['discord_id'] for p in pair} for pair in pairs]
    assert {1, 2} in pair_id_sets
    assert {3, 4} in pair_id_sets


# ─── Elo tiebreaking ──────────────────────────────────────────────────────────

def test_elo_used_as_tiebreaker():
    """
    When points are equal, the player with closest elo should be preferred.
    Player 1 (1500 elo) should pair with Player 2 (1480) not Player 3 (1000).
    """
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

def test_no_rematches():
    """Players who have already played should not be paired again."""
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


def test_rematch_forced_when_no_other_option():
    """
    With only 2 players who have already played each other,
    one ends up unpaired (rematch avoided, no other option).
    """
    players = [
        make_player(1, 1, 1500, match_history=[2]),
        make_player(2, 0, 1400, match_history=[1]),
    ]
    pairs, unpaired = pair_players(players)
    # Cannot pair — only option is a rematch
    assert len(pairs) == 0
    assert len(unpaired) == 2


# ─── Bye candidate selection ──────────────────────────────────────────────────

def test_bye_candidate_is_lowest_points():
    """The bye should go to the player with fewest points."""
    unpaired = [
        make_player(1, 3, 1500),
        make_player(2, 1, 1400),
    ]
    candidate = select_bye_candidate(unpaired)
    assert candidate['discord_id'] == 2


def test_bye_candidate_single_player():
    unpaired = [make_player(1, 0, 1200)]
    candidate = select_bye_candidate(unpaired)
    assert candidate['discord_id'] == 1


def test_bye_candidate_empty():
    assert select_bye_candidate([]) is None


# ─── All players already played each other ────────────────────────────────────

def test_all_rematches_no_pairs():
    """In a 3-player round-robin, eventually no pairings are possible."""
    players = [
        make_player(1, 2, 1500, match_history=[2, 3]),
        make_player(2, 1, 1400, match_history=[1, 3]),
        make_player(3, 0, 1300, match_history=[1, 2]),
    ]
    pairs, unpaired = pair_players(players)
    assert len(pairs) == 0