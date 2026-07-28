"""
Filters the combined AIS dataset down to vessels that are waiting/anchored
rather than transiting, using two cross-validated signals: speed over
ground (SOG) and self-reported navigational status.
"""
import os

import pandas as pd

INPUT_FILE = "data/storebaelt_combined.csv"
OUTPUT_FILE = "data/storebaelt_anchored.csv"

SOG_THRESHOLD = 0.5  # knots

# Only these two statuses genuinely mean "waiting due to congestion" —
# "Not under command" or "Restricted maneuverability" mean something else
# (a safety condition, not a queue), so we don't count them here.
WAITING_STATUSES = {"At anchor", "Moored"}


def filter_waiting_ships() -> None:
    print(f"Reading {INPUT_FILE} in chunks...")
    kept_chunks = []
    total_rows = 0

    for chunk in pd.read_csv(INPUT_FILE, chunksize=1_000_000):
        total_rows += len(chunk)

        by_speed = chunk["SOG"] < SOG_THRESHOLD
        by_status = chunk["Navigational status"].isin(WAITING_STATUSES)

        waiting = chunk[by_speed | by_status].copy()

        # Tag *why* each row was kept — useful for later confidence checks
        # and for explaining the method (e.g. in an interview or README).
        waiting["match_reason"] = "unknown"
        waiting.loc[by_speed & by_status, "match_reason"] = "both"
        waiting.loc[by_speed & ~by_status, "match_reason"] = "speed_only"
        waiting.loc[~by_speed & by_status, "match_reason"] = "status_only"

        kept_chunks.append(waiting)
        print(f"Processed {total_rows:,} rows...")

    print("\nMerging filtered anchored data...")
    final_df = pd.concat(kept_chunks, ignore_index=True)

    print("-" * 30)
    print(f"Original total rows: {total_rows:,}")
    print(f"Waiting/anchored rows: {len(final_df):,}")
    print(final_df["match_reason"].value_counts())
    print("-" * 30)

    final_df.to_csv(OUTPUT_FILE, index=False)
    print(f"Saved refined data to {OUTPUT_FILE}")


if __name__ == "__main__":
    filter_waiting_ships()
    