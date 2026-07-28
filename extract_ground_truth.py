"""
For each selected Sentinel-1 scene, extracts the AIS records that fall
within a ±5 minute window of the scene's exact acquisition timestamp.
This produces a small "ground truth" CSV per scene, used later to
cross-check the SAR-based ship detections against real AIS positions.
"""
import json
import os
import re
from datetime import datetime, timedelta

import pandas as pd

CATALOGUE_PATH = "data/sentinel1_catalogue.json"
COMBINED_AIS_PATH = "data/storebaelt_combined.csv"
OUTPUT_DIR = "data/ground_truth"

SELECTED_DATES = [
    "20260501", "20260504", "20260508", "20260515", "20260518",
    "20260522", "20260529", "20260601", "20260604", "20260609",
]

WINDOW_MINUTES = 5

# Matches e.g. "S1C_IW_GRDH_1SDV_20260501T170825_..." -> 2026-05-01 17:08:25
TIMESTAMP_PATTERN = re.compile(r"_(\d{8}T\d{6})_")


def pick_scenes(catalogue: list[dict]) -> list[dict]:
    picked = []
    for date_str in SELECTED_DATES:
        match = next((p for p in catalogue if date_str in p["Name"]), None)
        if match:
            picked.append(match)
    return picked


def parse_scene_time(name: str) -> datetime:
    match = TIMESTAMP_PATTERN.search(name)
    return datetime.strptime(match.group(1), "%Y%m%dT%H%M%S")


if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(CATALOGUE_PATH) as f:
        catalogue = json.load(f)

    scenes = pick_scenes(catalogue)
    windows = []
    for scene in scenes:
        center = parse_scene_time(scene["Name"])
        windows.append({
            "name": scene["Name"],
            "start": center - timedelta(minutes=WINDOW_MINUTES),
            "end": center + timedelta(minutes=WINDOW_MINUTES),
            "rows": [],
        })

    print(f"Matching AIS records against {len(windows)} scene windows...")

    for i, chunk in enumerate(pd.read_csv(COMBINED_AIS_PATH, chunksize=1_000_000)):
        chunk["Timestamp"] = pd.to_datetime(
            chunk["Timestamp"], format="%d/%m/%Y %H:%M:%S", errors="coerce"
        )
        chunk = chunk.dropna(subset=["Timestamp"])

        for w in windows:
            match = chunk[(chunk["Timestamp"] >= w["start"]) & (chunk["Timestamp"] <= w["end"])]
            if not match.empty:
                w["rows"].append(match)

        print(f"Processed chunk {i + 1}.")

    for w in windows:
        if w["rows"]:
            result = pd.concat(w["rows"], ignore_index=True)
        else:
            result = pd.DataFrame()
        date_tag = w["name"][17:25]  # e.g. "20260501"
        output_path = os.path.join(OUTPUT_DIR, f"ground_truth_{date_tag}.csv")
        result.to_csv(output_path, index=False)
        print(f"{w['name']}: {len(result)} AIS records -> {output_path}")

    print("\nGround truth extraction complete.")
    