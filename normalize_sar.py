"""
Converts preprocessed Sentinel-1 Sigma0 bands (linear scale, from SNAP)
into normalized 8-bit GeoTIFFs (dB scale, 0-255), ready for tiling.
Processes block-by-block to avoid loading the entire (multi-GB) scene
into memory at once.
"""
import glob
import os

import numpy as np
import rasterio
from rasterio.windows import Window

INPUT_DIR = "data/sentinel1/sentinel1_processed"
OUTPUT_DIR = "data/sentinel1/normalized"

DB_MIN = -30.0
DB_MAX = 5.0
BLOCK_SIZE = 1024  # process 1024x1024 pixel chunks at a time

os.makedirs(OUTPUT_DIR, exist_ok=True)


def db_normalize(data_dir: str) -> None:
    img_files = glob.glob(os.path.join(data_dir, "*_VV.img"))
    if not img_files:
        img_files = glob.glob(os.path.join(data_dir, "*.img"))
    if not img_files:
        print(f"Skipping {data_dir}: no .img file found.")
        return

    band_path = img_files[0]
    scene_name = os.path.basename(data_dir).replace(".data", "")
    output_path = os.path.join(OUTPUT_DIR, f"{scene_name}_normalized.tif")

    if os.path.exists(output_path):
        print(f"{scene_name}: already normalized, skipping.")
        return

    print(f"{scene_name}: processing in {BLOCK_SIZE}x{BLOCK_SIZE} blocks...")
    with rasterio.open(band_path) as src:
        profile = src.profile
        profile.update(driver="GTiff", dtype=rasterio.uint8, count=1, nodata=0, compress="lzw")

        with rasterio.open(output_path, "w", **profile) as dst:
            for row_off in range(0, src.height, BLOCK_SIZE):
                for col_off in range(0, src.width, BLOCK_SIZE):
                    win_h = min(BLOCK_SIZE, src.height - row_off)
                    win_w = min(BLOCK_SIZE, src.width - col_off)
                    window = Window(col_off, row_off, win_w, win_h)

                    block = src.read(1, window=window)
                    np.clip(block, 1e-6, None, out=block)
                    db = 10 * np.log10(block)
                    np.clip(db, DB_MIN, DB_MAX, out=db)
                    normalized = ((db - DB_MIN) / (DB_MAX - DB_MIN) * 255).astype(np.uint8)

                    dst.write(normalized, 1, window=window)

    print(f"{scene_name}: saved -> {output_path}")


if __name__ == "__main__":
    data_dirs = glob.glob(os.path.join(INPUT_DIR, "*.data"))
    print(f"Found {len(data_dirs)} processed scene(s).")

    for data_dir in data_dirs:
        db_normalize(data_dir)

    print("\nNormalization complete.")