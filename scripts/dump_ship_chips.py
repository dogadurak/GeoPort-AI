"""
TEŞHİS 3: Gözle bak.

En büyük AIS gemilerinin etrafından görüntü kesiti çıkarır ve AIS konumunu
artı işaretiyle işaretler. Hiçbir istatistik, hiçbir varsayım — sadece
"gemi orada mı?" sorusunun doğrudan cevabı.

Anizotropik piksel (X=5.69 m, Y=10.0 m) görsel olarak düzeltilir ki
gemiler gerçek en/boy oranıyla görünsün.
"""

import os
import sys

import cv2
import geopandas as gpd
import numpy as np
import rasterio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCENE = ("data/sentinel1/normalized/"
         "S1A_IW_GRDH_1SDV_20260504T053257_20260504T053322_064363_081AC8_1826"
         "_Orb_tnr_Cal_Spk_TC_normalized.tif")
AIS = "data/ground_truth/matched_ships_20260504_053257.geojson"
OUT = "reports/diagnostics"

MX, MY = 5.69, 10.00
HALF_M = 2000            # kesit yarı genişliği (metre)
N_SHIPS = 6


def main():
    os.makedirs(OUT, exist_ok=True)
    ais = gpd.read_file(AIS)
    ais["L"] = ais["Length"].astype(float)
    biggest = ais.nlargest(N_SHIPS, "L")

    rx, ry = int(HALF_M / MX), int(HALF_M / MY)
    panels = []

    with rasterio.open(SCENE) as src:
        for _, row in biggest.iterrows():
            r, c = rasterio.transform.rowcol(src.transform,
                                             row.geometry.x, row.geometry.y)
            r0, c0 = max(0, r - ry), max(0, c - rx)
            win = rasterio.windows.Window(c0, r0,
                                          min(2 * rx, src.width - c0),
                                          min(2 * ry, src.height - r0))
            block = src.read(1, window=win)
            if block.size == 0:
                continue

            # Anizotropiyi düzelt: X ekseni 5.69 m/px, Y 10 m/px.
            # X'i 0.569 ile ölçekleyince piksel yer düzleminde kare olur.
            h, w = block.shape
            block = cv2.resize(block, (int(w * MX / MY), h),
                               interpolation=cv2.INTER_AREA)

            img = cv2.cvtColor(block, cv2.COLOR_GRAY2BGR)
            cx = int((c - c0) * MX / MY)
            cy = int(r - r0)

            # AIS konumu: kırmızı artı + halka
            cv2.drawMarker(img, (cx, cy), (0, 0, 255), cv2.MARKER_CROSS, 40, 2)
            cv2.circle(img, (cx, cy), 25, (0, 0, 255), 1)
            label = f"MMSI {row['MMSI']}  L={row.L:.0f}m  SOG={row.get('SOG', 0):.1f}kn"
            cv2.putText(img, label, (6, 18), cv2.FONT_HERSHEY_SIMPLEX,
                        0.45, (0, 255, 255), 1)
            cv2.putText(img, "kirmizi + = AIS konumu", (6, h - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
            panels.append(img)

    if not panels:
        print("Kesit üretilemedi.")
        return

    hgt = min(p.shape[0] for p in panels)
    wid = min(p.shape[1] for p in panels)
    panels = [p[:hgt, :wid] for p in panels]
    grid = np.vstack([np.hstack(panels[i:i + 3]) for i in range(0, len(panels), 3)
                      if len(panels[i:i + 3]) == 3])

    path = os.path.join(OUT, "ship_chips.png")
    cv2.imwrite(path, grid)
    print(f"Kaydedildi: {path}  ({grid.shape[1]}x{grid.shape[0]})")
    print(f"Her kesit ~{2 * HALF_M} m x {2 * HALF_M} m")


if __name__ == "__main__":
    main()
