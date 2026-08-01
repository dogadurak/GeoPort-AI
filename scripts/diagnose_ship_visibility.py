"""
TEŞHİS 2: Gemi görüntüde GERÇEKTEN var mı, ve neredeyse orada mı?

Birinci teşhis "AIS gemisinin yakınında tespit yok" dedi. Ama bu üç farklı
sebepten olabilir. Bu script hangisi olduğunu kesinleştirir:

  Test A — AIS konumunun etrafında parlak hedef ARIYOR.
           Gemi görünüyorsa: nerede görünüyor, AIS'ten ne kadar uzakta?
           Ofset vektörleri tek bir yöne kümeleniyorsa -> sistematik geokodlama
           kayması (DÜZELTİLEBİLİR). Rastgele dağılıyorsa -> gemi orada yok.

  Test B — AIS konumundaki parlaklığı rastgele deniz noktalarıyla kıyaslıyor.
           Fark yoksa gemi görüntüde hiç yok demektir.

Kontrast, gemi boyuna göre ayrıştırılıyor: büyük gemiler görünüp küçükler
görünmüyorsa çözünürlük sınırı; büyükler de görünmüyorsa geokodlama/veri sorunu.

Hiçbir dosyayı değiştirmez.
"""

import os
import sys

import geopandas as gpd
import numpy as np
import rasterio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCENE = ("data/sentinel1/normalized/"
         "S1A_IW_GRDH_1SDV_20260504T053257_20260504T053322_064363_081AC8_1826"
         "_Orb_tnr_Cal_Spk_TC_normalized.tif")
AIS = "data/ground_truth/matched_ships_20260504_053257.geojson"

# Arama penceresi: hipotez edilen ~1.5 km kaymayı kapsayacak kadar geniş.
# Piksel anizotropik (X=5.69 m, Y=10.0 m), o yüzden yarıçaplar farklı.
RX, RY = 270, 150          # piksel  -> ~1540 m dogu-bati, ~1500 m kuzey-guney
MX, MY = 5.69, 10.00       # metre / piksel
RNG = np.random.default_rng(42)


def sample_window(src, row, col):
    r0, r1 = max(0, row - RY), min(src.height, row + RY + 1)
    c0, c1 = max(0, col - RX), min(src.width, col + RX + 1)
    if r1 <= r0 or c1 <= c0:
        return None, None, None
    win = rasterio.windows.Window(c0, r0, c1 - c0, r1 - r0)
    return src.read(1, window=win), r0, c0


def main():
    with rasterio.open(SCENE) as src:
        ais = gpd.read_file(AIS)
        rows, cols = rasterio.transform.rowcol(
            src.transform, ais.geometry.x.values, ais.geometry.y.values)
        rows, cols = np.array(rows), np.array(cols)
        lengths = ais["Length"].astype(float).values

        offsets, peaks, centres, kept_len = [], [], [], []

        for row, col, length in zip(rows, cols, lengths):
            block, r0, c0 = sample_window(src, row, col)
            if block is None or block.size == 0 or (block > 0).mean() < 0.5:
                continue

            # AIS konumundaki yerel parlaklik (3x3 tepe)
            lr, lc = row - r0, col - c0
            local = block[max(0, lr - 1):lr + 2, max(0, lc - 1):lc + 2]
            centres.append(float(local.max()) if local.size else 0.0)

            # Penceredeki en parlak nokta ve AIS'e gore ofseti
            idx = np.unravel_index(np.argmax(block), block.shape)
            peaks.append(float(block[idx]))
            offsets.append(((idx[1] + c0 - col) * MX, (idx[0] + r0 - row) * MY))
            kept_len.append(length)

        # Rastgele deniz noktalari (referans arka plan)
        bg = []
        while len(bg) < 400:
            r = RNG.integers(0, src.height)
            c = RNG.integers(0, src.width)
            block, _, _ = sample_window(src, r, c)
            if block is None or (block > 0).mean() < 0.9:
                continue
            bg.append(float(block[block > 0].mean()))

    offsets = np.array(offsets)
    peaks = np.array(peaks)
    centres = np.array(centres)
    kept_len = np.array(kept_len)
    bg = np.array(bg)

    print("=" * 68)
    print("TEST B — AIS konumunda gemi parlakligi var mi?")
    print("=" * 68)
    print(f"Incelenen AIS gemisi           : {len(centres)}")
    print(f"Rastgele deniz ortalamasi      : {bg.mean():.1f}  (std {bg.std():.1f})")
    print(f"AIS konumundaki parlaklik      : medyan {np.median(centres):.1f}")
    print(f"Pencere icindeki en parlak nokta: medyan {np.median(peaks):.1f}")
    print()
    for lo, hi in [(0, 20), (20, 30), (30, 50), (50, 100), (100, 1e9)]:
        m = (kept_len >= lo) & (kept_len < hi)
        if m.sum() == 0:
            continue
        bright = centres[m] > bg.mean() + 3 * bg.std()
        print(f"  L {lo:>3.0f}-{hi if hi < 1e8 else 999:>3.0f} m : n={m.sum():3d}  "
              f"AIS noktasinda medyan parlaklik={np.median(centres[m]):5.1f}  "
              f"belirgin hedef orani=%{100 * bright.mean():.0f}")

    print()
    print("=" * 68)
    print("TEST A — En parlak hedefin AIS'e gore ofseti (sistematik mi?)")
    print("=" * 68)
    dx, dy = offsets[:, 0], offsets[:, 1]
    dist = np.hypot(dx, dy)
    print(f"Ofset dogu-bati (dx) : medyan {np.median(dx):+8.0f} m   "
          f"ort {dx.mean():+8.0f}   std {dx.std():7.0f}")
    print(f"Ofset kuzey-guney(dy): medyan {np.median(dy):+8.0f} m   "
          f"ort {dy.mean():+8.0f}   std {dy.std():7.0f}")
    print(f"Ofset buyuklugu      : medyan {np.median(dist):8.0f} m")
    print()

    # Sistematik kayma testi: ortalama vektorun buyuklugu / dagilimin genisligi.
    # Sistematikse oran ~1'e yakin; rastgeleyse 0'a yakin.
    coherence = np.hypot(dx.mean(), dy.mean()) / (np.hypot(dx.std(), dy.std()) + 1e-9)
    print(f"Vektor tutarliligi (|ort| / std) : {coherence:.3f}")
    if coherence > 0.7:
        print("  -> SISTEMATIK KAYMA. Ofset sabit bir vektor; duzeltilebilir.")
    elif coherence > 0.3:
        print("  -> Kismi sistematik egilim var, ama gurultu baskin.")
    else:
        print("  -> RASTGELE. Sabit bir kayma YOK; en parlak nokta gemi degil,")
        print("     pencere icindeki rastgele bir parlak piksel.")

    close = 100 * (dist < 200).mean()
    print(f"\n200 m icinde parlak hedef bulunan gemi orani: %{close:.0f}")


if __name__ == "__main__":
    main()
