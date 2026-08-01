"""
GeoPort-AI: Physical Land Mask Generator
========================================
Downloads physical land mass geometries and generates binary land/sea raster masks
matching the spatial extent and resolution of each Sentinel-1 GeoTIFF scene.
Applies morphological coastline dilation to suppress near-shore radar clutter.

DURUM (Faz 0, 2026-08-01)
-------------------------
Yeni config şemasına taşındı (SAR_NORMALIZED_DIR -> SAR_UTM_DIR). Bariyerlenmedi
çünkü Faz 1'de doğrudan lazım: UTM rasterlarına uyan kara maskeleri üretecek.

Henüz çalışmaz — config.SAR_UTM_DIR'i Faz 1 dolduracak.

Faz 1'de gözden geçirilecek:
  - dilation_kernel_size=7 piksel: eski anizotropik gridde (5.69 m x 10 m) yer
    düzleminde elips bir tampon üretiyordu. UTM'ye geçince 7 px = her yönde
    70 m olacak; bu değerin doğru tampon olup olmadığı ölçülecek.
  - gpd.clip() + rasterize her sahne için global Natural Earth katmanını
    yeniden projekte ediyor; AOI'ye bir kez kırpmak yeterli.
"""

import os
import glob
import cv2
import numpy as np
import geopandas as gpd
from shapely.geometry import box
import rasterio
from rasterio.features import rasterize
from tqdm import tqdm
import warnings

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

warnings.filterwarnings("ignore")


def download_land_geometries():
    """
    Downloads physical land polygons from Natural Earth (1:10m) or checks local cache.
    """
    local_path = os.path.join(config.LAND_MASK_DIR, "ne_10m_land.shp")
    if os.path.exists(local_path):
        print(f"Loading local physical land polygon: {local_path}")
        return gpd.read_file(local_path)

    print("Downloading Natural Earth 1:10m physical land polygons...")
    url = "zip+https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_land.zip"
    try:
        land_gdf = gpd.read_file(url)
        # Save local copy for offline execution
        land_gdf.to_file(local_path)
        print(f"Success: {len(land_gdf)} global land polygons loaded and saved locally.")
        return land_gdf
    except Exception as e:
        print(f"Error downloading land geometries: {e}")
        return None


def process_tif(tif_path: str, global_land_gdf: gpd.GeoDataFrame, dilation_kernel_size: int = 7):
    """
    Creates a binary land mask GeoTIFF for a single SAR image.
    Land = 1, Sea = 0. Applies morphological dilation for coastal safety buffer.
    """
    out_mask_path = tif_path.replace(".tif", "_landmask.tif").replace(".tiff", "_landmask.tif")

    with rasterio.open(tif_path) as src:
        bounds = src.bounds
        crs = src.crs
        transform = src.transform
        width, height = src.width, src.height
        
        # Reproject global land to match TIFF CRS
        land_gdf = global_land_gdf.to_crs(crs)
        
        # Bounding box of the TIFF scene
        bbox = box(bounds.left, bounds.bottom, bounds.right, bounds.top)
        clipped_land = land_gdf.clip(bbox)
        
        if not clipped_land.is_empty.all() and len(clipped_land) > 0:
            shapes = ((geom, 1) for geom in clipped_land.geometry)
            land_mask = rasterize(
                shapes=shapes,
                out_shape=(height, width),
                transform=transform,
                fill=0,
                dtype='uint8'
            )
            
            # Morphological dilation: expand shoreline mask by 3-5 pixels to eliminate coastal reflections
            if dilation_kernel_size > 0:
                kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilation_kernel_size, dilation_kernel_size))
                land_mask = cv2.dilate(land_mask, kernel)
        else:
            land_mask = np.zeros((height, width), dtype='uint8')
            
        profile = src.profile.copy()
        profile.update({
            'count': 1,
            'dtype': 'uint8',
            'compress': 'lzw',
            'nodata': None
        })
        
        with rasterio.open(out_mask_path, 'w', **profile) as dst:
            dst.write(land_mask, 1)


def main():
    sar_dir = config.SAR_UTM_DIR
    tif_files = glob.glob(os.path.join(sar_dir, "*.tif")) + glob.glob(os.path.join(sar_dir, "*.tiff"))
    tif_files = [f for f in tif_files if not f.endswith("_landmask.tif")]
    
    if not tif_files:
        print(f"No TIFF files found in {sar_dir}.")
        return
        
    print(f"Processing land masks for {len(tif_files)} SAR scene(s)...")
    
    global_land_gdf = download_land_geometries()
    if global_land_gdf is None:
        return
        
    for tif_path in tqdm(tif_files, desc="Generating Land Masks"):
        process_tif(tif_path, global_land_gdf)
        
    print("\nAll land masks generated successfully!")


if __name__ == "__main__":
    main()
