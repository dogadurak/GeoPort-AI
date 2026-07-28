"""
Reads the filtered (waiting/anchored) AIS dataset in chunks, aggregates
vessel positions into a coarse spatial grid to build a density map, and
renders it as an interactive HTML heatmap.
"""
import os
from collections import defaultdict

import folium
import pandas as pd
from folium.plugins import HeatMap

DATA_DIR = "data"
INPUT_PATH = os.path.join(DATA_DIR, "storebaelt_anchored.csv")
GRID_OUTPUT_PATH = os.path.join(DATA_DIR, "density_grid.csv")
HEATMAP_OUTPUT_PATH = os.path.join(DATA_DIR, "density_heatmap.html")

# Grid cell size in degrees. ~0.001 degrees is roughly 100m at this latitude.
GRID_SIZE = 0.001

# Map center, roughly the middle of the Storebælt strait.
MAP_CENTER = [55.3, 10.9]


def build_density_grid(csv_path: str) -> pd.DataFrame:
    """
    Stream through the CSV in chunks and count how many AIS pings fall
    into each grid cell. Returns a small DataFrame: one row per grid cell,
    with its center coordinates and a ping count.
    """
    counts: dict[tuple[float, float], int] = defaultdict(int)

    chunk_iter = pd.read_csv(
        csv_path,
        chunksize=500_000,
        usecols=["Latitude", "Longitude"],  # we only need these two columns here
    )

    for i, chunk in enumerate(chunk_iter):
        # Snap every point to the nearest grid cell center.
        lat_bin = (chunk["Latitude"] / GRID_SIZE).round() * GRID_SIZE
        lon_bin = (chunk["Longitude"] / GRID_SIZE).round() * GRID_SIZE

        # Count occurrences per (lat_bin, lon_bin) pair in this chunk...
        chunk_counts = pd.DataFrame({"lat_bin": lat_bin, "lon_bin": lon_bin}) \
            .value_counts().reset_index(name="count")

        # ...and add them to the running totals.
        for _, row in chunk_counts.iterrows():
            counts[(row["lat_bin"], row["lon_bin"])] += row["count"]

        print(f"Processed chunk {i + 1} ({len(chunk)} rows).")

    grid_df = pd.DataFrame(
        [(lat, lon, count) for (lat, lon), count in counts.items()],
        columns=["Latitude", "Longitude", "count"],
    )
    grid_df = grid_df.sort_values("count", ascending=False).reset_index(drop=True)
    return grid_df


def save_heatmap(grid_df: pd.DataFrame, output_path: str) -> None:
    """Render the density grid as an interactive Leaflet heatmap (HTML file)."""
    m = folium.Map(location=MAP_CENTER, zoom_start=10, tiles="cartodbpositron")

    heat_data = grid_df[["Latitude", "Longitude", "count"]].values.tolist()
    HeatMap(heat_data, radius=8, blur=6, max_zoom=13).add_to(m)

    m.save(output_path)


if __name__ == "__main__":
    print(f"Building density grid from {INPUT_PATH}...")
    grid = build_density_grid(INPUT_PATH)
    grid.to_csv(GRID_OUTPUT_PATH, index=False)
    print(f"Saved {len(grid)} grid cells -> {GRID_OUTPUT_PATH}")

    print("Rendering heatmap...")
    save_heatmap(grid, HEATMAP_OUTPUT_PATH)
    print(f"Heatmap saved -> {HEATMAP_OUTPUT_PATH}")
    