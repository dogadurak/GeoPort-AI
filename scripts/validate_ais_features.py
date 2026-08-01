"""
PIVOT ÖNCESİ FİZİBİLİTE: AIS verisi önerilen dört özelliği taşıyor mu?

İnşaya başlamadan önce her özelliğin gerçekten sinyal taşıdığını ölçer.
Örnek olarak 3 günlük dilim kullanır (tüm veri 17M kayıt, 3.2 GB).

  F1  Bekleme/tıkanıklık : duran gemiler nerede? Liman rıhtımı mı, demirleme mi?
  F2  AIS boşluk/anomali : sinyal kesintileri ne sıklıkta, ne kadar uzun?
  F3  CPA/TCPA risk      : birbirine yaklaşan gemi çifti var mı, ne kadar?
  F4  Karbon             : hesap için gereken alanlar dolu mu?

Hiçbir dosyayı değiştirmez.
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CSV = "data/storebaelt_combined_dedup.csv"
DAYS = ("01/05/2026", "02/05/2026", "03/05/2026")
NM = 1852.0


def load():
    # Dosyaya gore "Timestamp" ya da "# Timestamp" olabiliyor.
    header = pd.read_csv(CSV, nrows=0).columns
    want = {"Timestamp", "MMSI", "Latitude", "Longitude", "SOG", "COG",
            "Ship type", "Length", "Navigational status"}
    cols = [c for c in header if c.strip().lstrip("# ") in want]

    chunks = []
    for ch in pd.read_csv(CSV, usecols=cols, chunksize=1_000_000, low_memory=False):
        ch.columns = [c.strip().lstrip("# ") for c in ch.columns]
        m = ch["Timestamp"].str.slice(0, 10).isin(DAYS)
        if m.any():
            chunks.append(ch[m])
    d = pd.concat(chunks, ignore_index=True)
    d["t"] = pd.to_datetime(d["Timestamp"], format="%d/%m/%Y %H:%M:%S", errors="coerce")
    for c in ("Latitude", "Longitude", "SOG", "Length"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    return d.dropna(subset=["t", "Latitude", "Longitude"]).sort_values("t")


def f1_waiting(d):
    print("=" * 66)
    print("F1 — BEKLEME / TIKANIKLIK")
    print("=" * 66)
    st = d[(d.SOG.notna()) & (d.SOG < 0.5)]
    print(f"Duran kayit: {len(st)}  ({100*len(st)/len(d):.0f}%)  "
          f"benzersiz gemi: {st.MMSI.nunique()}")

    # 0.01 derece (~1 km) izgarada yogunluk -> duraklar nerede kumelenmis?
    g = st.groupby([(st.Latitude * 100).round(), (st.Longitude * 100).round()])
    top = g.size().nlargest(8)
    print("\nEn yogun durma noktalari (~1 km izgara):")
    for (la, lo), n in top.items():
        sub = st[((st.Latitude * 100).round() == la) & ((st.Longitude * 100).round() == lo)]
        moored = 100 * sub["Navigational status"].eq("Moored").mean()
        print(f"  {la/100:.2f}N {lo/100:.2f}E : {n:6d} kayit, "
              f"{sub.MMSI.nunique():3d} gemi, Moored=%{moored:.0f}")
    print("\n  -> Moored orani yuksekse liman rihtimi (beklenen),")
    print("     dusukse gercek demirleme/bekleme (ilginc olan).")


def f2_gaps(d):
    print()
    print("=" * 66)
    print("F2 — AIS BOSLUK / ANOMALI")
    print("=" * 66)
    d = d.sort_values(["MMSI", "t"])
    dt = d.groupby("MMSI")["t"].diff().dt.total_seconds()
    moving = d.SOG > 2

    for lo, hi, lab in [(300, 900, "5-15 dk"), (900, 3600, "15-60 dk"),
                        (3600, 1e9, "> 1 saat")]:
        m = (dt >= lo) & (dt < hi) & moving
        print(f"  Seyir halindeyken {lab:>9} sessizlik : {int(m.sum()):5d} olay, "
              f"{d.loc[m, 'MMSI'].nunique():4d} gemi")

    # Fiziksel olarak imkansiz siçrama: iki kayit arasi hiz
    lat = np.radians(d.Latitude.values)
    dlat = np.radians(d.Latitude.diff().values)
    dlon = np.radians(d.Longitude.diff().values)
    dist = 6371000 * np.sqrt(dlat**2 + (np.cos(lat) * dlon)**2)
    same = d.MMSI.eq(d.MMSI.shift()).values
    spd = np.where(same & (dt.values > 0), dist / np.maximum(dt.values, 1) * 1.94384, np.nan)
    imp = spd > 40
    print(f"\n  Imkansiz hiz (>40 kn) : {int(np.nansum(imp))} olay, "
          f"{d.loc[imp, 'MMSI'].nunique() if imp.any() else 0} gemi")
    print("  -> Bu olaylar konum sicramasi / MMSI cakismasi / spoofing adayi.")


def f3_encounters(d):
    print()
    print("=" * 66)
    print("F3 — KARSILASMA / CPA RISKI")
    print("=" * 66)
    from scipy.spatial import cKDTree

    # 60 saniyelik dilimlere yuvarla, her dilimde yakin ciftleri say
    d = d[d.Length >= 30].copy()
    d["bin"] = d.t.dt.floor("60s")
    snap = d.groupby(["bin", "MMSI"]).agg(
        lat=("Latitude", "first"), lon=("Longitude", "first"),
        sog=("SOG", "first")).reset_index()

    lat0 = snap.lat.mean()
    mx = 111320 * np.cos(np.radians(lat0))
    counts = {0.25: 0, 0.5: 0, 1.0: 0}
    n_bins = 0
    pairs_quarter = set()

    for b, grp in snap.groupby("bin"):
        if len(grp) < 2:
            continue
        n_bins += 1
        xy = np.column_stack([grp.lon.values * mx, grp.lat.values * 111320])
        tree = cKDTree(xy)
        for thr in counts:
            pr = tree.query_pairs(thr * NM)
            counts[thr] += len(pr)
            if thr == 0.25:
                ids = grp.MMSI.values
                for i, j in pr:
                    pairs_quarter.add(tuple(sorted((ids[i], ids[j]))))

    print(f"Incelenen 60 sn'lik zaman dilimi : {n_bins}")
    print(f"Dilim basina ortalama gemi (L>=30m): {len(snap)/max(n_bins,1):.1f}")
    for thr in sorted(counts):
        print(f"  < {thr:.2f} NM ({thr*NM:4.0f} m) yakinlasan cift : {counts[thr]:6d}")
    print(f"\n  0.25 NM icine giren BENZERSIZ gemi cifti: {len(pairs_quarter)}")
    print("  -> Bu sayi anlamliysa CPA/TCPA analizi gercek risk haritasi uretir.")


def f4_carbon(d):
    print()
    print("=" * 66)
    print("F4 — KARBON HESABI ICIN VERI YETERLILIGI")
    print("=" * 66)
    need = {"SOG": d.SOG, "Length": d.Length, "Ship type": d["Ship type"]}
    for k, v in need.items():
        print(f"  {k:<12} dolu oran: %{100*v.notna().mean():.0f}")
    big = d[d.Length >= 30]
    print(f"\n  L>=30m gemi sayisi : {big.MMSI.nunique()}")
    print(f"  Tip bilinen        : %{100*big['Ship type'].ne('Undefined').mean():.0f}")
    print("  -> IMO yontemi tip + boy + hiz ister. Draught da varsa yuk durumu eklenir.")
    print(f"  Draught alani veride: {'VAR' if 'Draught' in d.columns else 'bu ornekte okunmadi'}")


if __name__ == "__main__":
    print(f"Ornek dilim: {', '.join(DAYS)}\n")
    d = load()
    print(f"Yuklenen kayit: {len(d)}  gemi: {d.MMSI.nunique()}\n")
    f1_waiting(d)
    f2_gaps(d)
    f3_encounters(d)
    f4_carbon(d)
