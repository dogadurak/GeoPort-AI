"""
Converts preprocessed Sentinel-1 Sigma0 bands (linear scale, from SNAP)
into normalized 8-bit GeoTIFFs (dB scale, 0-255), ready for tiling.
Processes block-by-block to avoid loading the entire (multi-GB) scene
into memory at once.
"""

raise SystemExit(
    "normalize_sar.py DEVRE DIŞI (Faz 0, 2026-08-01).\n"
    "Sebep: Sahne başına 1-99 persentil normalizasyonu yapıyor; '255' her sahnede\n"
    "       farklı bir dB'ye karşılık geldiği için sabit eşikler anlamsızlaşıyor.\n"
    "       Ayrıca sadece VV bandını okuyor ve float bilgiyi uint8'e düşürüyor.\n"
    "Yerine: Faz 1'de geoport/raster.py (UTM warp + float32 dB) gelecek.\n"
    "Ayrıntı: TECHNICAL_PLAN.md"
)

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
        # Geçici olarak devre dışı bırakıldı (Tüm sahneleri yeni logicle tekrar hesaplamak için)
        # print(f"{scene_name}: Zaten normalize edilmiş, atlanıyor.")
        # return
        pass

    print(f"{scene_name}: calculating global 1st and 99th percentiles (block-based sampling)...")
    with rasterio.open(band_path) as src:
        sample_blocks = []
        for row_off in range(0, src.height, BLOCK_SIZE):
            for col_off in range(0, src.width, BLOCK_SIZE):
                win_h = min(BLOCK_SIZE, src.height - row_off)
                win_w = min(BLOCK_SIZE, src.width - col_off)
                window = Window(col_off, row_off, win_w, win_h)
                
                block = src.read(1, window=window, out_dtype=np.float32)
                valid = block[block > 1e-5]
                
                if valid.size > 0:
                    valid = np.nan_to_num(valid, nan=1e-6, posinf=1e-6, neginf=1e-6)
                    np.clip(valid, 1e-6, None, out=valid)
                    valid_db = 10 * np.log10(valid)
                    
                    if valid_db.size > 10000:
                        valid_db = np.random.choice(valid_db, 10000, replace=False)
                    sample_blocks.append(valid_db)
                    
        if len(sample_blocks) > 0:
            all_valid_db = np.concatenate(sample_blocks)
            scene_db_min = float(np.percentile(all_valid_db, 1))
            scene_db_max = float(np.percentile(all_valid_db, 99))
            if scene_db_max - scene_db_min < 0.1:
                scene_db_min, scene_db_max = DB_MIN, DB_MAX
        else:
            scene_db_min, scene_db_max = DB_MIN, DB_MAX
            
        print(f"  Calculated scene range: {scene_db_min:.2f} dB to {scene_db_max:.2f} dB")

    print(f"{scene_name}: processing in {BLOCK_SIZE}x{BLOCK_SIZE} blocks...")
    with rasterio.open(band_path) as src:
        profile = src.profile
        profile.update(
            driver="GTiff",
            dtype=rasterio.uint8,
            count=1,
            nodata=0,
            tiled=True,
            blockxsize=512,
            blockysize=512,
            compress="lzw",
            predictor=2,
        )

        with rasterio.open(output_path, "w", **profile) as dst:
            for row_off in range(0, src.height, BLOCK_SIZE):
                for col_off in range(0, src.width, BLOCK_SIZE):
                    win_h = min(BLOCK_SIZE, src.height - row_off)
                    win_w = min(BLOCK_SIZE, src.width - col_off)
                    window = Window(col_off, row_off, win_w, win_h)

                    block = src.read(
                        1,
                        window=window,
                        out_dtype=np.float32
                    )
                    
                    # Matematiksel kalkan: NaN ve Inf değerleri temizle
                    block = np.nan_to_num(
                        block,
                        nan=1e-6,
                        posinf=1e-6,
                        neginf=1e-6
                    )
                    
                    np.clip(block, 1e-6, None, out=block)
                    db = 10 * np.log10(block)
                    np.clip(db, scene_db_min, scene_db_max, out=db)
                    
                    # Geçerli veriyi 1-255 arasına sıkıştırıyoruz. (0 maske için rezerve edildi)
                    normalized = (1 + (db - scene_db_min) / (scene_db_max - scene_db_min) * 254).astype(np.uint8)
                    
                    # Orijinal raster'ın maskesini okuyoruz
                    src_mask = src.read_masks(1, window=window)
                    
                    # Sadece GERÇEKTEN veri olmayan yerleri tam 0 yapıyoruz
                    normalized[src_mask == 0] = 0

                    dst.write(normalized, 1, window=window)

    print(f"{scene_name}: saved -> {output_path}")


if __name__ == "__main__":
    data_dirs = glob.glob(os.path.join(INPUT_DIR, "*.data"))
    print(f"Found {len(data_dirs)} processed scene(s).")

    for data_dir in data_dirs:
        db_normalize(data_dir)

    print("\nNormalization complete.")

    