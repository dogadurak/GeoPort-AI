"""
Matches processed Sentinel-1 SAR scenes (.dim files) with AIS ship
positions from the combined dataset, within a time tolerance window
around each scene's acquisition time. Outputs one GeoJSON per scene
for visual cross-checking in QGIS.
"""

raise SystemExit(
    "match_ais_sar.py DEVRE DIŞI (Faz 0, 2026-08-01).\n"
    "Sebep: Zaman enterpolasyonu yok (sadece 'en yakın kayıt'); ölçüm: %90 dilim\n"
    "       112 s = 12 knot'ta 690 m konum hatası. Gemi boyu filtresi de yok.\n"
    "Yerine: Faz 2'de geoport/ais.py (enterpolasyon + ölü hesap + 30 m filtresi).\n"
    "Ayrıntı: TECHNICAL_PLAN.md"
)

import glob
import os
from datetime import datetime, timedelta

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

SAR_DIR = "data/sentinel1/sentinel1_processed"
AIS_COMBINED_PATH = "data/storebaelt_combined_dedup.csv"  # single source of truth, no duplication
OUTPUT_DIR = "data/ground_truth"
TOLERANCE_MINUTES = 10

TIME_COLUMN = "Timestamp"
LAT_COLUMN = "Latitude"
LON_COLUMN = "Longitude"
MMSI_COLUMN = "MMSI"

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

    # MMSI'nin ondalıklı sayıya dönmesini engellemek için string olarak okuyoruz
    for i, chunk in enumerate(pd.read_csv(AIS_COMBINED_PATH, chunksize=1_000_000, dtype={MMSI_COLUMN: str})):
        
        # 1. GERÇEK GEMİ FİLTRESİ
        if 'Type of mobile' in chunk.columns:
            chunk = chunk[chunk['Type of mobile'].isin(['Class A', 'Class B'])]

        # 2. KOORDİNAT VERİ TİPİ ZORLAMASI (Güvenlik Kalkanı)
        chunk[LAT_COLUMN] = pd.to_numeric(chunk[LAT_COLUMN], errors="coerce")
        chunk[LON_COLUMN] = pd.to_numeric(chunk[LON_COLUMN], errors="coerce")
        chunk = chunk.dropna(subset=[LAT_COLUMN, LON_COLUMN])

        # 3. DÜNYA SINIRLARI FİLTRESİ (-90/90 ve -180/180)
        chunk = chunk[chunk[LAT_COLUMN].between(-90.0, 90.0)]
        chunk = chunk[chunk[LON_COLUMN].between(-180.0, 180.0)]

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
        
        # TEKİLLEŞTİRME VE ZAMAN FİLTRESİ (MÜKERRER MMSI ÇÖZÜMÜ)
        matched['time_diff'] = (matched[TIME_COLUMN] - w['sar_time']).abs()
        # En yakın zamanı bulup tekilleştiriyoruz
        matched = matched.sort_values('time_diff').drop_duplicates(subset=MMSI_COLUMN, keep='first')
        matched = matched.drop(columns=['time_diff'])

        geometry = [Point(xy) for xy in zip(matched[LON_COLUMN], matched[LAT_COLUMN])]
        gdf = gpd.GeoDataFrame(matched, geometry=geometry, crs="EPSG:4326")

        output_filename = f"matched_ships_{w['sar_time'].strftime('%Y%m%d_%H%M%S')}.geojson"
        output_path = os.path.join(OUTPUT_DIR, output_filename)
        gdf.to_file(output_path, driver="GeoJSON")
        
        print(f"{w['sar_file']}: {len(matched)} UNIQUE ships matched -> {output_filename}")

    print("\nDone.")
    