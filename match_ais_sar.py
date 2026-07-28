"""
Matches processed Sentinel-1 SAR scenes (.dim files) with AIS ship
positions from the combined dataset, within a time tolerance window
around each scene's acquisition time. Outputs one GeoJSON per scene
for visual cross-checking in QGIS.
"""
import glob
import os
from datetime import datetime, timedelta

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

SAR_DIR = "data/sentinel1/sentinel1_processed"
AIS_COMBINED_PATH = "data/storebaelt_combined.csv"  # single source of truth, no duplication
OUTPUT_DIR = "data/ground_truth"
TOLERANCE_MINUTES = 10

TIME_COLUMN = "Timestamp"
LAT_COLUMN = "Latitude"
LON_COLUMN = "Longitude"

os.makedirs(OUTPUT_DIR, exist_ok=True)


def extract_time_from_s1_filename(filename: str) -> datetime:
    basename = os.path.basename(filename)
    time_str = basename.split("_")[4]
    return datetime.strptime(time_str, "%Y%m%dT%H%M%S")


if __name__ == "__main__":
    sar_files = glob.glob(os.path.join(SAR_DIR, "*.dim"))
    print(f"Found {len(sar_files)} processed SAR scene(s).")

    windows = []
    for sar_file in sar_files:
        sar_time = extract_time_from_s1_filename(sar_file)
        windows.append({
            "sar_file": os.path.basename(sar_file),
            "sar_time": sar_time,
            "start": sar_time - timedelta(minutes=TOLERANCE_MINUTES),
            "end": sar_time + timedelta(minutes=TOLERANCE_MINUTES),
            "rows": [],
        })

    print(f"Scanning {AIS_COMBINED_PATH} once, in chunks, against {len(windows)} time window(s)...")

    for i, chunk in enumerate(pd.read_csv(AIS_COMBINED_PATH, chunksize=1_000_000)):
        chunk[TIME_COLUMN] = pd.to_datetime(
            chunk[TIME_COLUMN], format="%d/%m/%Y %H:%M:%S", errors="coerce"
        )
        chunk = chunk.dropna(subset=[TIME_COLUMN])

        for w in windows:
            match = chunk[(chunk[TIME_COLUMN] >= w["start"]) & (chunk[TIME_COLUMN] <= w["end"])]
            if not match.empty:
                w["rows"].append(match)

        print(f"Processed chunk {i + 1}.")

    for w in windows:
        if not w["rows"]:
            print(f"{w['sar_file']}: no AIS matches found.")
            continue

        matched = pd.concat(w["rows"], ignore_index=True)
        geometry = [Point(xy) for xy in zip(matched[LON_COLUMN], matched[LAT_COLUMN])]
        gdf = gpd.GeoDataFrame(matched, geometry=geometry, crs="EPSG:4326")

        output_filename = f"matched_ships_{w['sar_time'].strftime('%Y%m%d_%H%M%S')}.geojson"
        output_path = os.path.join(OUTPUT_DIR, output_filename)
        gdf.to_file(output_path, driver="GeoJSON")
        print(f"{w['sar_file']}: {len(matched)} ships matched -> {output_filename}")

    print("\nDone.")

    