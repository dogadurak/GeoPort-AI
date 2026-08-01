"""
Faz 0 doğrulama kapısı: `geoport/obb.py`, silinmiş `compute_ship_obb.py`'nin
ürettiği `data/ground_truth_obb/` çıktılarını birebir yeniden üretebiliyor mu?

Geçme ölçütü: her poligon için Hausdorff mesafesi < 0.1 m.

Hausdorff kullanılıyor çünkü köşe sıralaması farklı olabilir; bu ölçüt
sıralamadan bağımsız olarak iki şeklin gerçekten çakışıp çakışmadığını söyler.
"""

import glob
import math
import os
import sys

import geopandas as gpd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from geoport.obb import build_obb_geometry

TOLERANCE_M = 0.1


def hausdorff_m(poly_a, poly_b, lat: float) -> float:
    """İki poligon arasındaki Hausdorff mesafesini metre cinsinden verir."""
    m_per_deg_lon = 111320.0 * math.cos(math.radians(lat))

    def to_m(poly):
        return np.array([(x * m_per_deg_lon, y * 111320.0)
                         for x, y in poly.exterior.coords[:-1]])

    a, b = to_m(poly_a), to_m(poly_b)
    dist = np.linalg.norm(a[:, None, :] - b[None, :, :], axis=2)
    return max(dist.min(axis=1).max(), dist.min(axis=0).max())


def main() -> int:
    files = sorted(glob.glob(os.path.join(config.AIS_OBB_DIR, "*.geojson")))
    if not files:
        print(f"HATA: {config.AIS_OBB_DIR} içinde referans dosya yok.")
        return 1

    total = 0
    failures = []
    skipped = 0
    worst = 0.0
    worst_where = ""

    for path in files:
        gdf = gpd.read_file(path)
        for idx, row in gdf.iterrows():
            reference = row.geometry
            if reference is None or reference.is_empty:
                skipped += 1
                continue

            rebuilt = build_obb_geometry(row, use_antenna_offset=True)
            if rebuilt is None:
                failures.append((os.path.basename(path), idx, "üretilemedi"))
                continue

            total += 1
            deviation = hausdorff_m(reference, rebuilt, reference.centroid.y)
            if deviation > worst:
                worst, worst_where = deviation, f"{os.path.basename(path)}[{idx}]"
            if deviation > TOLERANCE_M:
                failures.append((os.path.basename(path), idx, f"{deviation:.3f} m"))

    print(f"Karşılaştırılan poligon : {total}")
    print(f"Boş geometri (atlandı)  : {skipped}")
    print(f"En büyük sapma          : {worst:.4f} m  ({worst_where})")
    print(f"Tolerans                : {TOLERANCE_M} m")
    print()

    if failures:
        print(f"[FAIL] {len(failures)} poligon toleransı aştı. İlk 10:")
        for name, idx, detail in failures[:10]:
            print(f"  {name}[{idx}]: {detail}")
        return 1

    print("[PASS] geoport/obb.py referans çıktıyı birebir yeniden üretiyor.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
