"""
Downloads a single day of AIS (Automatic Identification System) vessel
traffic data from the Danish Maritime Authority, extracts it, and filters
it down to the Storebælt (Great Belt) strait bounding box.
"""

import os
import zipfile

import pandas as pd
import requests

# --- Settings ---
DATE = "2026-06-15"  # target day, format YYYY-MM-DD
DATA_DIR = "data"

# Storebælt bounding box
LAT_MIN, LAT_MAX = 55.0, 55.6
LON_MIN, LON_MAX = 10.5, 11.3

os.makedirs(DATA_DIR, exist_ok=True)

SOURCE_URL = f"http://aisdata.ais.dk/aisdk-{DATE}.zip"
ZIP_PATH = os.path.join(DATA_DIR, f"aisdk-{DATE}.zip")
CSV_PATH = os.path.join(DATA_DIR, f"aisdk-{DATE}.csv")
OUTPUT_PATH = os.path.join(DATA_DIR, f"storebaelt_{DATE}.csv")


def download(url: str, zip_path: str) -> None:
    """Stream-download the zip file (several hundred MB) in 1MB chunks."""
    if os.path.exists(zip_path):
        print(f"{zip_path} already exists, skipping download.")
        return

    print(f"Downloading: {url}")
    response = requests.get(url, stream=True)
    response.raise_for_status()

    total_size = int(response.headers.get("content-length", 0))
    downloaded = 0

    with open(zip_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            f.write(chunk)
            downloaded += len(chunk)
            if total_size:
                print(f"\r  {downloaded / total_size * 100:.1f}%", end="")

    print("\nDownload complete.")


def extract(zip_path: str, data_dir: str) -> None:
    """Extract the CSV file from the downloaded zip archive."""
    print("Extracting zip archive...")
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(data_dir)
    print("Extraction complete.")


def filter_region(csv_path: str, output_path: str) -> None:
    """
    Read the full-country CSV in chunks (it can be several GB) and keep
    only the rows that fall inside the Storebælt bounding box.
    """
    print("Filtering by region...")
    kept_chunks = []

    for chunk in pd.read_csv(csv_path, chunksize=200_000):
        filtered = chunk[
            (chunk["Latitude"] >= LAT_MIN) & (chunk["Latitude"] <= LAT_MAX) &
            (chunk["Longitude"] >= LON_MIN) & (chunk["Longitude"] <= LON_MAX)
        ]
        if not filtered.empty:
            kept_chunks.append(filtered)

    result = pd.concat(kept_chunks, ignore_index=True) if kept_chunks else pd.DataFrame()
    result.to_csv(output_path, index=False)
    print(f"Found {len(result)} rows in the target region -> {output_path}")


if __name__ == "__main__":
    download(SOURCE_URL, ZIP_PATH)
    extract(ZIP_PATH, DATA_DIR)
    filter_region(CSV_PATH, OUTPUT_PATH)
    