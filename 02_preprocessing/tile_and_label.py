"""
Slices processed Sentinel-1 SAR scenes into smaller tiles (512x512) and
generates YOLO-OBB training labels from the ground truth OBB GeoJSON files.
"""

raise SystemExit(
    "tile_and_label.py DEVRE DIŞI (Faz 0, 2026-08-01).\n"
    "Sebep: Anizotropik piksel (5.69 m x 10.00 m) ve gemi boyu filtresi olmadan\n"
    "       çalışıyor; ürettiği etiketlerin %70'i dejenere (kısa kenar < 1.5 px).\n"
    "Yerine: Faz 3'te geoport/dataset.py gelecek.\n"
    "Ayrıntı: TECHNICAL_PLAN.md"
)

import glob
import os

import cv2
import geopandas as gpd
import numpy as np
import rasterio
from rasterio.windows import Window
from shapely.geometry import box

SAR_DIR = "data/sentinel1/normalized"
OBB_DIR = "data/ground_truth_obb"
OUTPUT_DIR = "data/yolo_dataset"

TILE_SIZE = 512
OVERLAP = 128
MIN_OVERLAP_RATIO = 0.3
VAL_SCENE_COUNT = 2
BLANK_STD_THRESHOLD = 1.0
NEGATIVE_KEEP_RATIO = 0.20  # Keep 20% of background tiles (~200 out of 1000)
PROGRESS_EVERY = 100  # her 100 pencerede bir ekrana ilerleme yaz

os.makedirs(os.path.join(OUTPUT_DIR, "images", "train"), exist_ok=True)
os.makedirs(os.path.join(OUTPUT_DIR, "images", "val"), exist_ok=True)
os.makedirs(os.path.join(OUTPUT_DIR, "labels", "train"), exist_ok=True)
os.makedirs(os.path.join(OUTPUT_DIR, "labels", "val"), exist_ok=True)


def polygon_to_yolo_obb_format(poly, width, height, transform):
    coords = list(poly.exterior.coords)[:4]
    if len(coords) < 4:
        return None

    pixel_coords = [(~transform * (lon, lat)) for lon, lat in coords]

    normalized_line = []
    for px, py in pixel_coords:
        nx = np.clip(px / width, 0.0, 1.0)
        ny = np.clip(py / height, 0.0, 1.0)
        normalized_line.extend([nx, ny])

    # After clipping to the tile, a heavily-cut ship can collapse to a
    # near-zero-area quad — drop those instead of writing a degenerate box.
    xs, ys = normalized_line[0::2], normalized_line[1::2]
    area = 0.5 * abs(sum(xs[i] * ys[(i + 1) % 4] - xs[(i + 1) % 4] * ys[i] for i in range(4)))
    if area < 1e-6:
        return None

    return "0 " + " ".join(f"{val:.6f}" for val in normalized_line)


def ships_for_tile(gdf, sindex, tile_box, min_overlap_ratio=MIN_OVERLAP_RATIO):
    """
    Ships intersecting this tile keep their ORIGINAL oriented rectangle
    (correct heading/angle). Re-fitting a new rectangle to the clipped
    shape would bias the angle toward the tile's axis-aligned cut edge,
    which is worse for training than letting the normalization step
    above clip out-of-bounds corners to [0, 1].
    """
    possible_idx = list(sindex.query(tile_box))
    if not possible_idx:
        return gdf.iloc[0:0]

    candidates = gdf.iloc[possible_idx]
    candidates = candidates[candidates.geometry.intersects(tile_box)]
    if candidates.empty:
        return candidates.iloc[0:0]

    kept = []
    for _, row in candidates.iterrows():
        clean_geom = row.geometry
        if clean_geom.area < 1e-12:
            continue

        clipped = clean_geom.intersection(tile_box)
        if clipped.is_empty:
            continue

        overlap_ratio = clipped.area / clean_geom.area
        if overlap_ratio < min_overlap_ratio:
            continue

        new_row = row.copy()
        new_row.geometry = clean_geom  # keep original angle, not re-fit
        kept.append(new_row)

    if not kept:
        return candidates.iloc[0:0]
    return gpd.GeoDataFrame(kept, crs=candidates.crs)


def process_scene(tif_path: str, obb_path: str, split: str):
    print(f"Processing scene -> {os.path.basename(tif_path)} [{split}]")

    gdf = gpd.read_file(obb_path)
    if gdf.empty:
        print("  Uyarı: Bu sahnede hiç OBB gemi verisi bulunamadı.")
        return

    with rasterio.open(tif_path) as src:
        img_w, img_h = src.width, src.height
        transform = src.transform

        if gdf.crs != src.crs:
            gdf = gdf.to_crs(src.crs)
        sindex = gdf.sindex

        step = TILE_SIZE - OVERLAP
        tile_count, skipped_blank = 0, 0

        y_offsets = list(range(0, img_h, step))
        x_offsets = list(range(0, img_w, step))
        total_windows = len(y_offsets) * len(x_offsets)
        windows_done = 0

        for y in y_offsets:
            for x in x_offsets:
                windows_done += 1
                if windows_done % PROGRESS_EVERY == 0:
                    print(f"    {windows_done}/{total_windows} pencere tarandı "
                          f"({tile_count} tile kaydedildi, {skipped_blank} boş atlandı)")

                window = Window(x, y, TILE_SIZE, TILE_SIZE)
                tile_img = src.read(1, window=window, boundless=True, fill_value=0)

                win_transform = rasterio.windows.transform(window, transform)
                tile_bounds = rasterio.windows.bounds(window, transform)
                tile_box = box(*tile_bounds)

                tile_ships = ships_for_tile(gdf, sindex, tile_box)

                if tile_ships.empty and tile_img.std() < BLANK_STD_THRESHOLD:
                    skipped_blank += 1
                    continue

                tile_img_bgr = cv2.cvtColor(tile_img, cv2.COLOR_GRAY2BGR)

                scene_name = os.path.splitext(os.path.basename(tif_path))[0]
                tile_name = f"{scene_name}_x{x}_y{y}"

                img_out_path = os.path.join(OUTPUT_DIR, "images", split, f"{tile_name}.png")
                lbl_out_path = os.path.join(OUTPUT_DIR, "labels", split, f"{tile_name}.txt")

                yolo_lines = []
                for _, row in tile_ships.iterrows():
                    line = polygon_to_yolo_obb_format(row.geometry, TILE_SIZE, TILE_SIZE, win_transform)
                    if line:
                        yolo_lines.append(line)

                # Filter negatives (tiles without ships) using the ratio, but ALWAYS KEEP positive tiles
                if not yolo_lines:
                    # For validation set, maybe keep all or keep ratio? Let's just apply to train set, or both.
                    # Since split can be 'val' or 'train', let's apply to both for consistent distribution
                    if np.random.rand() > NEGATIVE_KEEP_RATIO:
                        continue

                cv2.imwrite(img_out_path, tile_img_bgr)
                with open(lbl_out_path, "w") as f:
                    if yolo_lines:
                        f.write("\n".join(yolo_lines) + "\n")

                tile_count += 1

        print(f"  Tamamlandı: {tile_count} tile kaydedildi, {skipped_blank} boş karo atlandı.")


if __name__ == "__main__":
    tif_files = sorted(glob.glob(os.path.join(SAR_DIR, "*_normalized.tif")))
    print(f"Bulunan normalize SAR sahne sayısı: {len(tif_files)}")

    for idx, tif_path in enumerate(tif_files):
        basename = os.path.basename(tif_path)
        parts = basename.split("_")
        date_tag = None
        for p in parts:
            if "T" in p and len(p) == 15 and p.startswith("20"):
                t_parts = p.split("T")
                date_tag = f"{t_parts[0]}_{t_parts[1]}"
                break

        obb_path = os.path.join(OBB_DIR, f"matched_ships_{date_tag}.geojson")
        if not os.path.exists(obb_path):
            print(f"  HATA: {basename} için OBB dosyası bulunamadı!")
            continue

        split = "val" if idx < VAL_SCENE_COUNT else "train"
        process_scene(tif_path, obb_path, split)

    print("\nTüm Tiling ve YOLO-OBB etiketleme süreci başarıyla tamamlandı!")

