"""
TEŞHİS: AIS gemisi -> en yakın SAR tespiti mesafe dağılımı.

Eşik UYGULAMAZ. Ham mesafeleri ölçer ve üç hipotezi birbirinden ayırır:

  H1  Tepe 300-700 m'de toplanmış      -> azimut kayması / geokodlama ofseti
                                          (düzeltilebilir, model çalışıyor)
  H2  Dağınık, km'lerce, rastgele      -> koordinat dönüşüm zinciri hatalı
  H3  Çoğu gemide yakın tespit yok     -> model göremiyor (domain gap)

Yardımcı ayrım: mesafe vs gemi uzunluğu. Sadece küçük gemiler kaçıyorsa H3 kesinleşir.

Hiçbir dosyayı değiştirmez, sadece okur.
"""

import json
import os
import re
import sys
from collections import defaultdict

import geopandas as gpd
import numpy as np
import rasterio
from pyproj import Transformer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DETECTIONS = "_deprecated_20260801/data_hybrid_results/hybrid_detections.json"
SCENE_DIR = "data/sentinel1/normalized"
AIS_DIR = "data/ground_truth"
OUT_DIR = "reports/diagnostics"

TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32632", always_xy=True)


def parse_tile(name):
    m = re.search(r"^(.+_normalized)_x(\d+)_y(\d+)(?:\.png)?$", name)
    t = re.search(r"(\d{8}T\d{6})", name)
    if not m or not t:
        return None
    return m.group(1), t.group(1), int(m.group(2)), int(m.group(3))


def collect_scene_detections():
    with open(DETECTIONS) as f:
        raw = json.load(f)

    scenes = defaultdict(lambda: {"time": None, "dets": []})
    for tile_name, dets in raw.items():
        parsed = parse_tile(tile_name)
        if not parsed:
            continue
        base, stamp, x_off, y_off = parsed
        scenes[base]["time"] = stamp
        for d in dets:
            scenes[base]["dets"].append(
                (x_off + d["cx"], y_off + d["cy"], d.get("type", "?"), d.get("conf"))
            )
    return scenes


def analyse_scene(base, info):
    tif = os.path.join(SCENE_DIR, f"{base}.tif")
    ais_path = os.path.join(AIS_DIR,
                            f"matched_ships_{info['time'][:8]}_{info['time'][9:]}.geojson")
    if not os.path.exists(tif) or not os.path.exists(ais_path):
        print(f"  atlandi (dosya yok): {base[-40:]}")
        return None

    with rasterio.open(tif) as src:
        px = np.array([[d[0], d[1]] for d in info["dets"]])
        lon, lat = rasterio.transform.xy(src.transform, px[:, 1], px[:, 0])
        det_lon, det_lat = np.array(lon), np.array(lat)
        det_type = np.array([d[2] for d in info["dets"]])

        ais = gpd.read_file(ais_path)
        ais_lon = ais.geometry.x.values
        ais_lat = ais.geometry.y.values

        # Geçerli veri kontrolü: AIS noktası nodata bölgesindeyse uydu oraya
        # bakmamıştır; "tespit yok" demek yanıltıcı olur.
        rows, cols = rasterio.transform.rowcol(src.transform, ais_lon, ais_lat)
        rows, cols = np.array(rows), np.array(cols)
        inside = ((rows >= 0) & (rows < src.height) &
                  (cols >= 0) & (cols < src.width))
        valid = np.zeros(len(ais), dtype=bool)
        if inside.any():
            vals = np.array(list(src.sample(
                [(x, y) for x, y in zip(ais_lon[inside], ais_lat[inside])], indexes=1
            ))).ravel()
            valid[inside] = vals > 0

    dx, dy = TO_UTM.transform(det_lon, det_lat)
    ax, ay = TO_UTM.transform(ais_lon, ais_lat)

    det_xy = np.column_stack([dx, dy])
    ais_xy = np.column_stack([ax, ay])

    def nearest(mask_det):
        sub = det_xy[mask_det]
        if len(sub) == 0:
            return np.full(len(ais_xy), np.nan)
        d = np.linalg.norm(ais_xy[:, None, :] - sub[None, :, :], axis=2)
        return d.min(axis=1)

    lengths = ais.get("Length")
    lengths = lengths.values if lengths is not None else np.full(len(ais), np.nan)

    return {
        "scene": base,
        "time": info["time"],
        "n_det": len(det_xy),
        "n_yolo": int((det_type == "YOLO").sum()),
        "n_cfar": int((det_type == "CFAR").sum()),
        "valid": valid,
        "d_all": nearest(np.ones(len(det_xy), dtype=bool)),
        "d_yolo": nearest(det_type == "YOLO"),
        "d_cfar": nearest(det_type == "CFAR"),
        "length": lengths.astype(float),
    }


def report(results):
    os.makedirs(OUT_DIR, exist_ok=True)

    valid = np.concatenate([r["valid"] for r in results])
    d_all = np.concatenate([r["d_all"] for r in results])[valid]
    d_yolo = np.concatenate([r["d_yolo"] for r in results])[valid]
    d_cfar = np.concatenate([r["d_cfar"] for r in results])[valid]
    length = np.concatenate([r["length"] for r in results])[valid]

    total_ais = sum(len(r["valid"]) for r in results)

    print("=" * 68)
    print("AIS -> EN YAKIN SAR TESPITI MESAFE DAGILIMI  (esik uygulanmadi)")
    print("=" * 68)
    for r in results:
        print(f"  {r['time']}: {r['n_det']:6d} tespit "
              f"(YOLO {r['n_yolo']}, CFAR {r['n_cfar']}) | "
              f"AIS {len(r['valid'])}, gecerli veri icinde {int(r['valid'].sum())}")
    print()
    print(f"Toplam AIS kaydi          : {total_ais}")
    print(f"Gecerli SAR verisi icinde : {int(valid.sum())}  "
          f"(nodata bolgesindekiler haric tutuldu)")
    print()

    def dist_table(name, d):
        finite = d[np.isfinite(d)]
        if len(finite) == 0:
            print(f"  {name}: tespit yok")
            return
        qs = [10, 25, 50, 75, 90, 95]
        line = "  ".join(f"%{q}={np.percentile(finite, q):.0f}m" for q in qs)
        print(f"  {name:<12} {line}")

    print("Yuzdelikler:")
    dist_table("TUM", d_all)
    dist_table("YOLO", d_yolo)
    dist_table("CFAR", d_cfar)
    print()

    print("Histogram (TUM tespitler, en yakin mesafe):")
    edges = [0, 50, 100, 200, 300, 500, 700, 1000, 2000, 5000, 1e9]
    labels = ["0-50", "50-100", "100-200", "200-300", "300-500",
              "500-700", "700-1k", "1k-2k", "2k-5k", ">5k"]
    finite = d_all[np.isfinite(d_all)]
    counts, _ = np.histogram(finite, bins=edges)
    for lab, c in zip(labels, counts):
        pct = 100 * c / max(len(finite), 1)
        bar = "#" * int(pct / 2)
        print(f"  {lab:>8} m : {c:4d}  {pct:5.1f}%  {bar}")
    print()

    print("Mesafe vs gemi uzunlugu (YOLO tespitlerine):")
    bands = [(0, 20), (20, 30), (30, 50), (50, 100), (100, 1e9)]
    for lo, hi in bands:
        m = np.isfinite(length) & (length >= lo) & (length < hi) & np.isfinite(d_yolo)
        if m.sum() == 0:
            continue
        sub = d_yolo[m]
        close = 100 * (sub < 300).mean()
        print(f"  L {lo:>3.0f}-{hi if hi < 1e8 else 999:>3.0f} m : n={m.sum():4d}  "
              f"medyan={np.median(sub):7.0f} m   <300m orani=%{close:.0f}")
    print()

    close_all = 100 * (d_all[np.isfinite(d_all)] < 300).mean()
    close_yolo = 100 * (d_yolo[np.isfinite(d_yolo)] < 300).mean()
    print("=" * 68)
    print(f"300 m icinde tespiti olan AIS gemisi: TUM=%{close_all:.1f}  "
          f"YOLO=%{close_yolo:.1f}")
    print("=" * 68)

    np.savez(os.path.join(OUT_DIR, "match_distances.npz"),
             d_all=d_all, d_yolo=d_yolo, d_cfar=d_cfar, length=length)
    print(f"\nHam mesafeler kaydedildi: {OUT_DIR}/match_distances.npz")


if __name__ == "__main__":
    scenes = collect_scene_detections()
    print(f"Sahne sayisi: {len(scenes)}\n")
    results = [r for r in (analyse_scene(b, i) for b, i in scenes.items()) if r]
    if results:
        report(results)
