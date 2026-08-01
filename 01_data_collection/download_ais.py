"""
Downloads a 2-month batch of AIS (Automatic Identification System) vessel traffic data
from the Danish Maritime Authority. Extracts, filters to the Storebælt bounding box,
cleans up raw files immediately, and merges everything into one combined dataset.
"""

raise SystemExit(
    "download_ais.py DEVRE DIŞI (Faz 0, 2026-08-01).\n"
    "Sebep: bbox'ı config.AOI_BBOX_WGS84'ten değil kendi içinden alıyor (üç ayrı\n"
    "       bbox sorununun kaynağı). Ayrıca çalıştırıldığında sorgusuz 250 MB'lık\n"
    "       günlük dosyaları indirmeye başlıyor — istenmeden ağ/disk tüketiyor.\n"
    "Not:   İhtiyaç duyulan AIS verisi (2026-05-01..06-15) zaten data/ altında.\n"
    "Yerine: Faz 2'de config'ten AOI okuyan sürüm gelecek.\n"
    "Ayrıntı: TECHNICAL_PLAN.md"
)

import os
import zipfile

import pandas as pd
import requests

# --- Settings ---
START_DATE = "2026-05-01"
END_DATE = "2026-06-30"
DATA_DIR = "data"
COMBINED_PATH = os.path.join(DATA_DIR, "storebaelt_combined.csv")

# Storebælt bounding box
LAT_MIN, LAT_MAX = 55.0, 55.6
LON_MIN, LON_MAX = 10.5, 11.3

os.makedirs(DATA_DIR, exist_ok=True)


def download_and_process(date_str: str) -> None:
    source_url = f"http://aisdata.ais.dk/aisdk-{date_str}.zip"
    zip_path = os.path.join(DATA_DIR, f"aisdk-{date_str}.zip")
    raw_csv_path = os.path.join(DATA_DIR, f"aisdk-{date_str}.csv")
    output_path = os.path.join(DATA_DIR, f"storebaelt_{date_str}.csv")

    if os.path.exists(output_path):
        print(f"[{date_str}] Filtered data already exists. Skipping.")
        return

    print(f"[{date_str}] Downloading raw data...")
    response = requests.get(source_url, stream=True)
    if response.status_code != 200:
        print(f"[{date_str}] Data not found on server (Status: {response.status_code}).")
        return

    with open(zip_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            f.write(chunk)

    print(f"[{date_str}] Extracting...")
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(DATA_DIR)

    print(f"[{date_str}] Filtering for Storebælt region...")
    kept_chunks = []
    for chunk in pd.read_csv(raw_csv_path, chunksize=200_000):
        filtered = chunk[
            (chunk["Latitude"] >= LAT_MIN) & (chunk["Latitude"] <= LAT_MAX) &
            (chunk["Longitude"] >= LON_MIN) & (chunk["Longitude"] <= LON_MAX)
        ]
        if not filtered.empty:
            kept_chunks.append(filtered)

    if kept_chunks:
        result = pd.concat(kept_chunks, ignore_index=True)
        if "# Timestamp" in result.columns:
            result.rename(columns={"# Timestamp": "Timestamp"}, inplace=True)
        result.to_csv(output_path, index=False)
        print(f"[{date_str}] Success! Kept {len(result)} rows.")
    else:
        print(f"[{date_str}] No target ships found in bounding box.")

    print(f"[{date_str}] Cleaning up raw files to save disk space...")
    if os.path.exists(zip_path):
        os.remove(zip_path)
    if os.path.exists(raw_csv_path):
        os.remove(raw_csv_path)


def combine_all(data_dir: str, combined_path: str) -> None:
    """Merge every daily filtered file into a single dataset for analysis."""
    daily_files = sorted(
        os.path.join(data_dir, f) for f in os.listdir(data_dir)
        if f.startswith("storebaelt_") and f.endswith(".csv") and "combined" not in f
    )
    if not daily_files:
        print("No daily files found to combine.")
        return

    frames = [pd.read_csv(f) for f in daily_files]
    combined = pd.concat(frames, ignore_index=True)
    combined.to_csv(combined_path, index=False)
    print(f"Combined {len(daily_files)} days into {combined_path} ({len(combined)} rows total).")


def main():
    print(f"Starting AIS Data Pipeline for {START_DATE} to {END_DATE}")
    print("=" * 50)

    dates = pd.date_range(start=START_DATE, end=END_DATE)
    for current_date in dates:
        date_str = current_date.strftime("%Y-%m-%d")
        download_and_process(date_str)
        print("-" * 50)

    combine_all(DATA_DIR, COMBINED_PATH)
    print("Pipeline Execution Completed.")


if __name__ == "__main__":
    main()