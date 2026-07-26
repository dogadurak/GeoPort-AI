"""
Merges whatever daily filtered AIS files currently exist in data/ into one
combined CSV — appends file by file to avoid loading everything into
memory at once.
"""
import os

import pandas as pd

DATA_DIR = "data"
COMBINED_PATH = os.path.join(DATA_DIR, "storebaelt_combined.csv")

daily_files = sorted(
    os.path.join(DATA_DIR, f) for f in os.listdir(DATA_DIR)
    if f.startswith("storebaelt_") and f.endswith(".csv") and "combined" not in f
)

if not daily_files:
    print("No daily files found yet.")
else:
    if os.path.exists(COMBINED_PATH):
        os.remove(COMBINED_PATH)  # start fresh

    total_rows = 0
    for i, f in enumerate(daily_files):
        df = pd.read_csv(f)
        write_header = (i == 0)  # only write column names once, at the top
        df.to_csv(COMBINED_PATH, mode="a", header=write_header, index=False)
        total_rows += len(df)
        print(f"[{i + 1}/{len(daily_files)}] Appended {f} ({len(df)} rows).")
        del df  # free memory immediately

    print(f"Combined {len(daily_files)} days into {COMBINED_PATH} ({total_rows} rows total).")