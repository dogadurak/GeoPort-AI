"""
Tiles normalized SAR GeoTIFFs into 512x512 chips (20% overlap), matches
each chip against the corresponding scene's ship OBB polygons, and writes
YOLO-OBB format labels. Splits scenes into train/val by scene (not by
tile) to avoid data leakage between near-duplicate overlapping chips.
"""
import glob
import os
import random
import re

import geopandas as gpd
import numpy as np
import rasterio
from PIL import Image
from rasterio.windows import Window
from shapely.geometry import box

NORMALIZED_DIR = "data/sentinel1/normalized"
GROUND_TRUTH_DIR = "data/ground_truth_obb"
OUTPUT_DIR = "data/yolo_dataset"

TILE_SIZE = 512
STRIDE = 410  # ~20% overlap
NEGATIVE_KEEP_RATIO = 0.15  # fraction of empty tiles to keep
VAL_SCENE_COUNT = 2  # scene-level split, not tile-level

TIMESTAMP_PATTERN = re.compile(r"_(\d{8}T\d{6})_")

random.seed(42)


def scene_key_from_filename(filename: str) -> str:
    """Extracts e.g. '20260504_053257' from a normalized tif filename."""
    match = TIMESTAMP_PATTERN.search(filename)
    raw = match.group(1)  # '20260504T053257'
    date_part, time_part = raw.split("T")
    return f"{date_part}_{time_part}"


def load_ground_truth(scene_key: str) -> gpd.GeoDataFrame | None:
    path = os.path.join(GROUND_TRUTH_DIR, f"matched_ships_{scene_key}.geojson")
    if not os.path.exists(path):
        print(f"  Warning: no ground truth found for {scene_key}")
        return None
    return gpd.read_file(path)


def tile_scene(tif_path: str, gdf: gpd.GeoDataFrame, split: str, scene_key: str) -> tuple[int, int]:
    n_positive, n_negative = 0, 0

    with rasterio.open(tif_path) as src:
        width, height = src.width, src.height

        for row_off in range(0, height, STRIDE):
            for col_off in range(0, width, STRIDE):
                win_h = min(TILE_SIZE, height - row_off)
                win_w = min(TILE_SIZE, width - col_off)
                if win_h < TILE_SIZE or win_w < TILE_SIZE:
                    continue  # skip partial edge tiles, keeps everything uniform size

                window = Window(col_off, row_off, TILE_SIZE, TILE_SIZE)
                tile_data = src.read(1, window=window)

                # Skip tiles that are almost entirely nodata (outside the SAR swath).
                if np.count_nonzero(tile_data) < (TILE_SIZE * TILE_SIZE * 0.5):
                    continue

                win_transform = rasterio.windows.transform(window, src.transform)
                tile_bounds = rasterio.windows.bounds(window, src.transform)
                tile_box = box(*tile_bounds)

                # Find ships whose centroid falls inside this tile.
                ships_in_tile = gdf[gdf.geometry.centroid.within(tile_box)]

                if ships_in_tile.empty:
                    n_negative += 1
                    if random.random() > NEGATIVE_KEEP_RATIO:
                        continue  # discard most empty tiles
                else:
                    n_positive += 1

                tile_name = f"{scene_key}_{row_off}_{col_off}"
                save_tile(tile_data, ships_in_tile, win_transform, split, tile_name)

    return n_positive, n_negative


def save_tile(tile_data: np.ndarray, ships: gpd.GeoDataFrame, win_transform, split: str, tile_name: str) -> None:
    img_dir = os.path.join(OUTPUT_DIR, "images", split)
    label_dir = os.path.join(OUTPUT_DIR, "labels", split)
    os.makedirs(img_dir, exist_ok=True)
    os.makedirs(label_dir, exist_ok=True)

    # Duplicate single band into 3 channels — most YOLO tooling expects RGB.
    rgb = np.stack([tile_data] * 3, axis=-1)
    Image.fromarray(rgb, mode="RGB").save(os.path.join(img_dir, f"{tile_name}.png"))

    lines = []
    inv_transform = ~win_transform
    for geom in ships.geometry:
        coords = list(geom.exterior.coords)[:4]  # 4 corners
        normalized = []
        for lon, lat in coords:
            col, row = inv_transform * (lon, lat)
            normalized.append(col / TILE_SIZE)
            normalized.append(row / TILE_SIZE)
        # class 0 = ship (only one class in this dataset)
        lines.append("0 " + " ".join(f"{v:.6f}" for v in normalized))

    with open(os.path.join(label_dir, f"{tile_name}.txt"), "w") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    tif_files = sorted(glob.glob(os.path.join(NORMALIZED_DIR, "*_normalized.tif")))
    print(f"Found {len(tif_files)} normalized scene(s).")

    scene_keys = [scene_key_from_filename(f) for f in tif_files]
    val_keys = set(random.sample(scene_keys, min(VAL_SCENE_COUNT, len(scene_keys))))

    total_pos, total_neg = 0, 0
    for tif_path, scene_key in zip(tif_files, scene_keys):
        split = "val" if scene_key in val_keys else "train"
        print(f"\n{scene_key} -> {split}")

        gdf = load_ground_truth(scene_key)
        if gdf is None:
            continue

        n_pos, n_neg = tile_scene(tif_path, gdf, split, scene_key)
        total_pos += n_pos
        total_neg += n_neg
        print(f"  {n_pos} tiles with ships, {n_neg} empty tiles found (some kept as negatives)")

    print(f"\nDone. Total positive tiles: {total_pos}, total empty tiles seen: {total_neg}")
    print(f"Val scenes: {val_keys}")