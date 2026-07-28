"""
Computes rotated (oriented) bounding box corners for each AIS-matched ship,
using its real length/width (from AIS dimension fields A/B/C/D) and heading.
Saves one GeoJSON per scene with polygon geometries instead of points —
input for the tiling step.
"""
import glob
import math
import os

import geopandas as gpd
from shapely.geometry import Polygon

INPUT_DIR = "data/ground_truth"
OUTPUT_DIR = "data/ground_truth_obb"

os.makedirs(OUTPUT_DIR, exist_ok=True)

# Rough conversion: 1 degree latitude ~= 111,320 m everywhere.
# 1 degree longitude ~= 111,320 * cos(latitude) m — shrinks as you go north.
METERS_PER_DEG_LAT = 111_320.0


def ship_rectangle(lat: float, lon: float, length_m: float, width_m: float, heading_deg: float) -> Polygon:
    """
    Builds a rotated rectangle (in lon/lat degrees) centered on the ship's
    AIS position, oriented along its heading (0 = North, clockwise).
    """
    if length_m <= 0 or width_m <= 0:
        # Fallback for ships with missing/zero dimension fields.
        length_m, width_m = 20.0, 6.0

    meters_per_deg_lon = METERS_PER_DEG_LAT * math.cos(math.radians(lat))

    half_l = length_m / 2
    half_w = width_m / 2

    # Rectangle corners in a local "meters, heading-aligned" frame:
    # bow-right, bow-left, stern-left, stern-right.
    local_corners = [
        (half_w, half_l), (-half_w, half_l),
        (-half_w, -half_l), (half_w, -half_l),
    ]

    heading_rad = math.radians(heading_deg)
    geo_corners = []
    for x, y in local_corners:
        # Rotate around origin: heading is clockwise from North, so this
        # is a standard clockwise rotation (not the usual counter-clockwise
        # math convention).
        rot_x = x * math.cos(heading_rad) + y * math.sin(heading_rad)
        rot_y = -x * math.sin(heading_rad) + y * math.cos(heading_rad)

        d_lon = rot_x / meters_per_deg_lon
        d_lat = rot_y / METERS_PER_DEG_LAT
        geo_corners.append((lon + d_lon, lat + d_lat))

    return Polygon(geo_corners)


def process_file(path: str) -> None:
    gdf = gpd.read_file(path)

    # Real ship dimensions from AIS Class A fields (meters).
    gdf["length_m"] = gdf["A"].fillna(0) + gdf["B"].fillna(0)
    gdf["width_m"] = gdf["C"].fillna(0) + gdf["D"].fillna(0)
    gdf["Heading"] = gdf["Heading"].fillna(0)

    polygons = [
        ship_rectangle(row.geometry.y, row.geometry.x, row.length_m, row.width_m, row.Heading)
        for row in gdf.itertuples()
    ]
    gdf["geometry"] = polygons

    output_path = os.path.join(OUTPUT_DIR, os.path.basename(path))
    gdf.to_file(output_path, driver="GeoJSON")
    print(f"{os.path.basename(path)}: {len(gdf)} ship boxes -> {output_path}")


if __name__ == "__main__":
    files = glob.glob(os.path.join(INPUT_DIR, "*.geojson"))
    print(f"Found {len(files)} ground truth file(s).")

    for f in files:
        process_file(f)

    print("\nDone.")
    