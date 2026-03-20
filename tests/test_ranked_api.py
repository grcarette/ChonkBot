"""
Standalone test for UCH Ranked API — report then confirm flow.

Run from the tests directory:
    python test_ranked_api.py

Players:
    Winner: 1449832127536304198
    Loser:  142798704703700992
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.uchranked_api import UCHRankedAPI

WINNER_ID = 1374498306020999230
LOSER_ID  = 142798704703700992


async def main():
    api = UCHRankedAPI()

    # ── Step 1: Verify both players exist ────────────────────────────────────
    print("=== Step 1: Checking players ===")

    winner = await api.get_player(WINNER_ID)
    if not winner:
        print(f"[ERROR] Winner ({WINNER_ID}) not found in UCH Ranked.")
        return
    print(f"Winner:  {winner.get('username')}  |  ELO: {winner.get('elo')}")

    loser = await api.get_player(LOSER_ID)
    if not loser:
        print(f"[ERROR] Loser ({LOSER_ID}) not found in UCH Ranked.")
        return
    print(f"Loser:   {loser.get('username')}  |  ELO: {loser.get('elo')}")

    # ── Step 2: Report the match ──────────────────────────────────────────────
    print("\n=== Step 2: Reporting match (2-1) ===")
    report_result = await api.report_match(
        player1_id=WINNER_ID,
        player2_id=LOSER_ID,
        score="2-1",
        vod=""
    )
    print(f"Response: {report_result}")

    if not report_result.get('success'):
        print(f"[ERROR] Report failed: {report_result.get('error')}")
        return

    match_id = report_result.get('match_id')
    print(f"Match reported successfully. match_id={match_id}")

    # ── Step 3: Check pending matches for both players ────────────────────────
    print("\n=== Step 3: Pending matches (winner) ===")
    winner_matches = await api.get_matches(WINNER_ID)
    print(winner_matches)

    print("\n=== Step 3: Pending matches (loser) ===")
    loser_matches = await api.get_matches(LOSER_ID)
    print(loser_matches)

    # ── Step 4: Confirm the match as both players ─────────────────────────────
    if not match_id:
        print("[ERROR] No match_id returned, cannot confirm.")
        return

    print(f"\n=== Step 4a: Confirming match {match_id} as winner ===")
    confirm_winner = await api.accept_match(
        discord_id=WINNER_ID,
        match_id=match_id
    )
    print(f"Confirm response (winner): {confirm_winner}")

    if not confirm_winner.get('success'):
        print(f"[ERROR] Winner confirm failed: {confirm_winner.get('error')}")
        return

    print(f"\n=== Step 4b: Confirming match {match_id} as loser (errors ignored) ===")
    try:
        confirm_loser = await api.accept_match(
            discord_id=LOSER_ID,
            match_id=match_id
        )
        print(f"Confirm response (loser): {confirm_loser}")
    except Exception as e:
        print(f"Loser confirm failed (ignored): {e}")

    print("Confirms fired.")

    # ── Step 5: Check updated ELOs ────────────────────────────────────────────
    print("\n=== Step 5: Updated ELOs ===")
    winner_after = await api.get_player(WINNER_ID)
    loser_after  = await api.get_player(LOSER_ID)

    winner_elo_before = winner.get('elo')
    winner_elo_after  = winner_after.get('elo')
    loser_elo_before  = loser.get('elo')
    loser_elo_after   = loser_after.get('elo')

    print(f"Winner: {winner_after.get('username')}  |  ELO: {winner_elo_after}  (was {winner_elo_before})")
    print(f"Loser:  {loser_after.get('username')}  |  ELO: {loser_elo_after}  (was {loser_elo_before})")

    assert winner_elo_after != winner_elo_before, (
        f"[FAIL] Winner ELO did not change (still {winner_elo_after})"
    )
    assert loser_elo_after != loser_elo_before, (
        f"[FAIL] Loser ELO did not change (still {loser_elo_after})"
    )
    assert winner_elo_after > winner_elo_before, (
        f"[FAIL] Winner ELO should have increased: {winner_elo_before} -> {winner_elo_after}"
    )
    assert loser_elo_after < loser_elo_before, (
        f"[FAIL] Loser ELO should have decreased: {loser_elo_before} -> {loser_elo_after}"
    )

    print("\n[PASS] ELOs updated correctly.")


if __name__ == "__main__":
    asyncio.run(main())