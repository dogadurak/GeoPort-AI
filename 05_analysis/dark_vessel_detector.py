"""
GeoPort-AI: Module 4 — Dark Vessel Detection Engine (Optimized & Verified)
========================================================================
Converts pixel coordinates of YOLO & CFAR hybrid detections into WGS84 geographic
coordinates, reprojects if necessary, and cross-matches satellite detections
against AIS ground truth using the Hungarian Algorithm (linear_sum_assignment).

Outputs:
  - dark_vessels.geojson: Vessels detected in SAR but missing AIS signal
  - matched_vessels.geojson: Ships confirmed by both SAR and AIS
  - ghost_signals.geojson: AIS positions broadcasting without SAR detection
  - dark_vessel_report.json: Execution statistics and summary report

DURUM (Faz 0, 2026-08-01)
-------------------------
Bu dosya bilinçli olarak BARİYERLENMEDİ; yeni config şemasına taşındı çünkü
Faz 6'da eşleşme oranını eski koşuyla karşılaştırmak için lazım olacak.
Referans taban (arşivlenen eski koşu): 6 eşleşme / 115 AIS = %5.2.

Ama HENÜZ ÇALIŞMAZ — girdileri yok:
  - config.DETECTION_DIR/hybrid_detections.json  -> Faz 5 üretecek
  - config.SAR_UTM_DIR/*.tif                     -> Faz 1 üretecek
Şu an çalıştırılırsa "dosya bulunamadı" ile durur; bu beklenen davranıştır.

BİLİNEN HATALAR (Faz 6'da düzeltilecek, bu taşımada DOKUNULMADI):
  - Karo örtüşmesi tekilleştirilmiyor: aynı gemi 2 kez dark vessel sayılıyor
    (eski koşuda 11 dark vessel'ın 3 çifti kopyaydı).
  - Hungarian ataması gating'siz: eşik sonradan uygulanıyor, doğru eşleşmeler
    yanlış çiftlere kilitlenebiliyor.
  - Sahne footprint'i kontrol edilmiyor: uydunun bakmadığı bölgedeki AIS
    gemileri "ghost signal" sayılıyor.
  - land_polygon.contains() STRtree'siz, tek tek çağrılıyor (yavaş).
  - 'bbox' liste sütunu GeoJSON'a yazılamıyor.
Ayrıntı: TECHNICAL_PLAN.md Faz 6
"""

import json
import math
import os
import re
from collections import defaultdict

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.warp import transform as rasterio_transform
from scipy.optimize import linear_sum_assignment
from shapely.geometry import Point

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

# Setup directories
os.makedirs(config.DARK_VESSEL_RESULTS_DIR, exist_ok=True)


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Calculates geodesic distance between two lat/lon pairs in meters using Haversine formula."""
    R = 6_371_000.0  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * R * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def parse_tile_name(tile_name: str):
    """
    Extracts scene base name, SAR timestamp string, and pixel offsets from tile file name.
    Example: ..._20260504T053257_..._normalized_x10368_y10752.png
    """
    match = re.search(r'_x(\d+)_y(\d+)(?:\.png)?$', tile_name)
    if not match:
        return None, None, None, None
    x_offset = int(match.group(1))
    y_offset = int(match.group(2))

    time_match = re.search(r'(\d{8}T\d{6})', tile_name)
    sar_datetime_str = time_match.group(1) if time_match else None

    norm_suffix_match = re.search(r'^(.+_normalized)_x\d+_y\d+(?:\.png)?$', tile_name)
    scene_base = norm_suffix_match.group(1) if norm_suffix_match else None

    return scene_base, sar_datetime_str, x_offset, y_offset


def pixel_to_lonlat(x_offset: int, y_offset: int, cx: float, cy: float, src_raster) -> tuple:
    """
    Converts tile pixel coordinate (cx, cy) to WGS84 geographic (lon, lat) degrees.
    Safely reprojects if the source GeoTIFF CRS is projected (e.g. UTM meters).
    """
    abs_x = x_offset + cx
    abs_y = y_offset + cy

    gt = src_raster.transform
    x_coords, y_coords = gt * (abs_x, abs_y)

    crs = src_raster.crs
    if crs and crs.to_string().upper() != "EPSG:4326":
        # Reproject from local raster CRS to WGS84 (EPSG:4326)
        lons, lats = rasterio_transform(crs, "EPSG:4326", [x_coords], [y_coords])
        return lons[0], lats[0]
    
    return x_coords, y_coords


def find_geotiff(scene_base: str) -> str:
    """Finds normalized GeoTIFF corresponding to scene base name."""
    tif_path = os.path.join(config.SAR_UTM_DIR, f"{scene_base}.tif")
    if os.path.exists(tif_path):
        return tif_path
    tif_path2 = os.path.join(config.SAR_UTM_DIR, f"{scene_base}.tiff")
    if os.path.exists(tif_path2):
        return tif_path2
    return None


def find_ais_geojson(sar_datetime_str: str) -> str:
    """Finds matched AIS ground truth GeoJSON for given SAR acquisition timestamp."""
    if sar_datetime_str is None:
        return None
    date_part = sar_datetime_str[:8]
    time_part = sar_datetime_str[9:]
    filename = f"matched_ships_{date_part}_{time_part}.geojson"
    path = os.path.join(config.AIS_GROUND_TRUTH_DIR, filename)
    return path if os.path.exists(path) else None


def hungarian_matching(sar_detections: list, ais_points: list, max_distance_m: float) -> tuple:
    """
    Globally optimal 1-to-1 matching between SAR detections and AIS ship signals using Hungarian Algorithm.
    
    Returns:
        (matched_records, dark_vessels, ghost_signals)
    """
    n_sar = len(sar_detections)
    n_ais = len(ais_points)

    if n_sar == 0:
        ghosts = [
            {
                **ais,
                "status": "GHOST SIGNAL (AIS broadcast, no SAR detection)"
            }
            for ais in ais_points
        ]
        return [], [], ghosts

    if n_ais == 0:
        darks = [
            {
                **sar,
                "status": "DARK VESSEL (No AIS ground truth available)"
            }
            for sar in sar_detections
        ]
        return [], darks, []

    # Build Distance Cost Matrix (N_SAR x N_AIS)
    cost_matrix = np.zeros((n_sar, n_ais), dtype=np.float64)
    for i, sar in enumerate(sar_detections):
        for j, ais in enumerate(ais_points):
            cost_matrix[i, j] = haversine_m(sar["lon"], sar["lat"], ais["lon"], ais["lat"])

    # Hungarian / Munkres Optimal Assignment
    row_ind, col_ind = linear_sum_assignment(cost_matrix)

    matched_sar_indices = set()
    matched_ais_indices = set()

    matched_records = []
    dark_vessels = []

    for r, c in zip(row_ind, col_ind):
        dist = cost_matrix[r, c]
        if dist <= max_distance_m:
            matched_sar_indices.add(r)
            matched_ais_indices.add(c)

            sar = sar_detections[r]
            ais = ais_points[c]

            match_info = {
                **sar,
                "status": "MATCHED",
                "ais_mmsi": ais.get("mmsi"),
                "ais_name": ais.get("name"),
                "ais_ship_type": ais.get("ship_type"),
                "ais_sog": ais.get("sog"),
                "ais_cog": ais.get("cog"),
                "ais_nav_status": ais.get("nav_status"),
                "distance_m": round(dist, 1),
            }
            matched_records.append(match_info)

    # Unmatched SAR detections -> Dark Vessels
    for i, sar in enumerate(sar_detections):
        if i not in matched_sar_indices:
            # Find distance to nearest AIS for diagnostic info
            nearest_dist = float(cost_matrix[i, :].min()) if n_ais > 0 else None
            dark_info = {
                **sar,
                "status": "DARK VESSEL",
                "nearest_ais_m": round(nearest_dist, 1) if nearest_dist is not None else None,
            }
            dark_vessels.append(dark_info)

    # Unmatched AIS signals -> Ghost Signals
    ghost_signals = []
    for j, ais in enumerate(ais_points):
        if j not in matched_ais_indices:
            nearest_sar_dist = float(cost_matrix[:, j].min()) if n_sar > 0 else None
            ghost_info = {
                **ais,
                "status": "GHOST SIGNAL (AIS broadcast, no SAR detection)",
                "nearest_sar_m": round(nearest_sar_dist, 1) if nearest_sar_dist is not None else None,
            }
            ghost_signals.append(ghost_info)

    return matched_records, dark_vessels, ghost_signals


def run_dark_vessel_detection():
    """Main execution pipeline for Module 4."""
    print("=" * 60)
    print("MODULE 4: DARK VESSEL DETECTION ENGINE (HUNGARIAN OPTIMIZED)")
    print("=" * 60)

    hybrid_results_path = os.path.join(config.DETECTION_DIR, "hybrid_detections.json")
    if not os.path.exists(hybrid_results_path):
        print(f"Error: Hybrid detections file not found at {hybrid_results_path}")
        return

    with open(hybrid_results_path) as f:
        hybrid_results = json.load(f)

    print(f"Loaded tiles: {len(hybrid_results)}")

    # Load Physical Landmask for shoreline filtering
    land_polygon = None
    landmask_shape = os.path.join(config.LAND_MASK_DIR, "ne_10m_land.shp")
    if os.path.exists(landmask_shape):
        try:
            land_gdf = gpd.read_file(landmask_shape)
            land_polygon = land_gdf.geometry.unary_union
            print("Landmask successfully loaded.")
        except Exception as e:
            print(f"Warning: Failed to parse landmask shapefile ({e})")

    # Group detections by parent scene
    scene_detections = defaultdict(list)
    skipped = 0

    for tile_name, detections in hybrid_results.items():
        scene_base, sar_dt, x_off, y_off = parse_tile_name(tile_name)
        if scene_base is None:
            skipped += 1
            continue

        for det in detections:
            det["_tile"] = tile_name
            det["_x_offset"] = x_off
            det["_y_offset"] = y_off
            det["_sar_datetime"] = sar_dt
            scene_detections[scene_base].append(det)

    print(f"Total scenes: {len(scene_detections)}")
    if skipped > 0:
        print(f"Skipped tiles: {skipped}")

    all_dark_vessels = []
    all_matched = []
    all_ghosts = []
    scene_reports = []

    for scene_base, detections in scene_detections.items():
        sar_dt = detections[0]["_sar_datetime"]
        print(f"\n--- Scene: {scene_base[-50:]} ---")
        print(f"  SAR acquisition time: {sar_dt}")

        tif_path = find_geotiff(scene_base)
        if tif_path is None:
            print(f"  ⚠ GeoTIFF not found, skipping scene.")
            continue

        with rasterio.open(tif_path) as src_raster:
            geo_detections = []
            for det in detections:
                det_type = det.get("type", "UNKNOWN")
                conf = det.get("conf", 1.0 if det_type == "CFAR" else 0.0)

                # Confidence thresholding for YOLO
                if det_type == "YOLO" and conf < config.DARK_VESSEL_MIN_CONF:
                    continue

                # Area thresholding for CFAR
                if det_type == "CFAR":
                    area = det.get("area_px", 1)
                    if area < config.CFAR_MIN_CLUSTER_PX or area > config.CFAR_MAX_CLUSTER_PX:
                        continue

                lon, lat = pixel_to_lonlat(
                    det["_x_offset"], det["_y_offset"],
                    det["cx"], det["cy"], src_raster
                )

                # Valid coordinate sanity check
                if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
                    continue

                # Land filter (skip targets located on land)
                if land_polygon is not None and land_polygon.contains(Point(lon, lat)):
                    continue

                # Geographic Bounding Box Filter
                # Artık AOI ile AIS indirme bbox'ı aynı (config tek kaynak).
                # Eskiden config bbox'ı (10-12°) AIS'inkinden (10.5-11.3°) genişti;
                # arada kalan her tespit otomatik "dark vessel" oluyordu.
                min_lon, min_lat, max_lon, max_lat = config.AOI_BBOX_WGS84
                if not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat):
                    continue

                geo_detections.append({
                    "lon": lon,
                    "lat": lat,
                    "type": det_type,
                    "conf": conf,
                    "tile": det["_tile"],
                    "bbox": det.get("bbox"),
                    "area_px": det.get("area_px"),
                })

        print(f"  Valid geographic SAR detections: {len(geo_detections)} (YOLO & CFAR)")

        # Load AIS Ground Truth
        ais_path = find_ais_geojson(sar_dt)
        if ais_path is None:
            print(f"  ⚠ AIS GeoJSON ground truth not found ({sar_dt})")
            for gd in geo_detections:
                gd["status"] = "DARK VESSEL (No AIS ground truth file)"
                all_dark_vessels.append(gd)
            continue

        ais_gdf = gpd.read_file(ais_path)
        ais_points = []
        for _, row in ais_gdf.iterrows():
            ais_points.append({
                "lon": row.geometry.x,
                "lat": row.geometry.y,
                "mmsi": str(row.get("MMSI", "unknown")),
                "name": str(row.get("Name", "")),
                "ship_type": str(row.get("Ship type", row.get("Type of mobile", ""))),
                "sog": float(row.get("SOG", 0.0)) if row.get("SOG") is not None else None,
                "cog": float(row.get("COG", 0.0)) if row.get("COG") is not None else None,
                "nav_status": str(row.get("Navigational status", "")),
            })

        print(f"  AIS ship records: {len(ais_points)}")

        # Perform Hungarian Matching
        matched, darks, ghosts = hungarian_matching(
            geo_detections, ais_points, config.MATCH_DISTANCE_M
        )

        all_matched.extend(matched)
        all_dark_vessels.extend(darks)
        all_ghosts.extend(ghosts)

        print(f"  [RESULT] Matched: {len(matched)} | Dark Vessels: {len(darks)} | Ghost Signals: {len(ghosts)}")

        scene_reports.append({
            "scene": scene_base[-60:],
            "sar_time": sar_dt,
            "total_sar_detections": len(geo_detections),
            "total_ais": len(ais_points),
            "matched": len(matched),
            "dark_vessels": len(darks),
            "ghost_signals": len(ghosts),
        })

    # Save Outputs
    print("\n" + "=" * 60)
    print("FINAL SUMMARY")
    print("=" * 60)
    print(f"Total Matched Vessels:  {len(all_matched)}")
    print(f"Total Dark Vessels:     {len(all_dark_vessels)}")
    print(f"Total Ghost Signals:    {len(all_ghosts)}")

    out_dir = config.DARK_VESSEL_RESULTS_DIR

    if all_dark_vessels:
        dark_gdf = gpd.GeoDataFrame(
            all_dark_vessels,
            geometry=[Point(d["lon"], d["lat"]) for d in all_dark_vessels],
            crs="EPSG:4326"
        )
        dark_gdf.to_file(os.path.join(out_dir, "dark_vessels.geojson"), driver="GeoJSON")
        print("  -> Saved dark_vessels.geojson")

    if all_matched:
        matched_gdf = gpd.GeoDataFrame(
            all_matched,
            geometry=[Point(d["lon"], d["lat"]) for d in all_matched],
            crs="EPSG:4326"
        )
        matched_gdf.to_file(os.path.join(out_dir, "matched_vessels.geojson"), driver="GeoJSON")
        print("  -> Saved matched_vessels.geojson")

    if all_ghosts:
        ghost_gdf = gpd.GeoDataFrame(
            all_ghosts,
            geometry=[Point(d["lon"], d["lat"]) for d in all_ghosts],
            crs="EPSG:4326"
        )
        ghost_gdf.to_file(os.path.join(out_dir, "ghost_signals.geojson"), driver="GeoJSON")
        print("  -> Saved ghost_signals.geojson")

    report = {
        "summary": {
            "total_matched": len(all_matched),
            "total_dark_vessels": len(all_dark_vessels),
            "total_ghost_signals": len(all_ghosts),
            "match_threshold_m": config.MATCH_DISTANCE_M,
        },
        "scenes": scene_reports,
        "matched_avg_distance_m": round(
            np.mean([m["distance_m"] for m in all_matched]), 1
        ) if all_matched else None,
    }
    with open(os.path.join(out_dir, "dark_vessel_report.json"), "w") as f:
        json.dump(report, f, indent=2, default=str)
    print("  -> Saved dark_vessel_report.json")

    print("\nMODULE 4 EXECUTION COMPLETE.")


if __name__ == "__main__":
    run_dark_vessel_detection()
