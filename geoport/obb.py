"""
AIS kaydından yönlü sınırlayıcı kutu (OBB) üretimi.

Silinmiş `compute_ship_obb.py`'nin yerini alır. Mevcut `data/ground_truth_obb/`
çıktıları tersine mühendislikle çözüldü ve bu modül onları **birebir** yeniden
üretecek şekilde yazıldı (bkz. `scripts/verify_obb_reproduction.py`).

Geometri
--------
AIS anteni gemi merkezinde değildir. ITU-R M.1371'e göre:

        A = burundan antene           C = iskeleden antene
        B = antenden kıça            D = antenden sancağa
        Length = A + B                Width = C + D

                    burun
                     ▲  fwd
              ┌──────┼──────┐
              │      │      │
    iskele ───┤   ●──┼──────┤─── sancak      ● = AIS anteni
       (C)    │  ×   │      │      (D)       × = gemi merkezi
              └──────┼──────┘
                     ▼
                     kıç

Merkez, antenden şu kadar ötelenmiştir:
    eksen boyunca (buruna doğru)  : A - Length/2
    eksene dik (sancağa doğru)    : D - Width/2

244 m'lik bir gemide bu ofset 84 m'ye ulaşır — ihmal edilemez.

Yön
---
`Heading` varsa o kullanılır, yoksa `COG`, o da yoksa 0.0.
(Mevcut veride 115 kaydın 65'inde Heading, 19'unda COG, 31'inde 0.0 vardı.)
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from shapely.geometry import Polygon

# WGS84 derece <-> metre dönüşümü için kullanılan yarıçap sabiti.
# Mevcut ground_truth_obb çıktıları bu değerle üretilmiş; birebir tekrar
# üretebilmek için aynısı korunuyor.
_M_PER_DEG_LAT = 111320.0


def ship_orientation(heading, cog) -> float:
    """
    Gemi yönünü derece cinsinden döndürür (0 = kuzey, saat yönünde artar).

    Öncelik: Heading > COG > 0.0
    """
    for value in (heading, cog):
        if value is None:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isnan(numeric):
            return numeric
    return 0.0


def center_offset_m(length_m: float, width_m: float,
                    a=None, b=None, c=None, d=None) -> tuple[float, float]:
    """
    AIS anteninden gemi merkezine olan ötelemeyi metre cinsinden döndürür.

    Returns:
        (along_m, across_m) — sırasıyla buruna ve sancağa doğru pozitif.
        A/B/C/D yoksa (0.0, 0.0) döner (anten merkezde varsayılır).
    """
    along = 0.0
    across = 0.0

    if a is not None and not pd.isna(a):
        along = float(a) - length_m / 2.0
    if d is not None and not pd.isna(d):
        across = float(d) - width_m / 2.0

    return along, across


def obb_corners_local(length_m: float, width_m: float, heading_deg: float,
                      along_m: float = 0.0, across_m: float = 0.0) -> np.ndarray:
    """
    OBB köşelerini, AIS anteni orijin kabul edilen yerel bir metrik düzlemde
    (x = doğu, y = kuzey) hesaplar.

    Returns:
        (4, 2) dizi — köşeler saat yönünde: sancak-burun, sancak-kıç,
        iskele-kıç, iskele-burun.
    """
    heading_rad = math.radians(heading_deg)

    # İleri birim vektörü: pusula açısı kuzeyden saat yönünde ölçülür.
    fwd = np.array([math.sin(heading_rad), math.cos(heading_rad)])
    # Sancak = ileri vektörünün saat yönünde 90° döndürülmüşü.
    stb = np.array([math.cos(heading_rad), -math.sin(heading_rad)])

    center = along_m * fwd + across_m * stb

    half_l = length_m / 2.0
    half_w = width_m / 2.0

    return np.array([
        center + half_l * fwd + half_w * stb,   # sancak-burun
        center - half_l * fwd + half_w * stb,   # sancak-kıç
        center - half_l * fwd - half_w * stb,   # iskele-kıç
        center + half_l * fwd - half_w * stb,   # iskele-burun
    ])


def obb_polygon_wgs84(lon: float, lat: float, length_m: float, width_m: float,
                      heading_deg: float, along_m: float = 0.0,
                      across_m: float = 0.0) -> Polygon:
    """
    OBB'yi doğrudan WGS84 derece uzayında üretir.

    Not: Bu, `data/ground_truth_obb/` çıktılarıyla uyumluluk için korunuyor.
    Faz 1 sonrası hat UTM'de çalışacağı için yeni kod `obb_polygon_projected`
    kullanmalı — orada cos(lat) yaklaşımına hiç gerek yok.
    """
    corners = obb_corners_local(length_m, width_m, heading_deg, along_m, across_m)

    m_per_deg_lon = _M_PER_DEG_LAT * math.cos(math.radians(lat))
    if abs(m_per_deg_lon) < 1e-9:
        raise ValueError(f"Kutuplara çok yakın enlem, dönüşüm tanımsız: {lat}")

    ring = [(lon + dx / m_per_deg_lon, lat + dy / _M_PER_DEG_LAT)
            for dx, dy in corners]
    return Polygon(ring)


def obb_polygon_projected(x: float, y: float, length_m: float, width_m: float,
                          heading_deg: float, along_m: float = 0.0,
                          across_m: float = 0.0) -> Polygon:
    """
    OBB'yi metrik bir projeksiyonda (örn. EPSG:32632) üretir.

    Faz 1'den sonra tercih edilen yol: birim zaten metre olduğu için
    enlem düzeltmesi gerekmez, bozulma yoktur.
    """
    corners = obb_corners_local(length_m, width_m, heading_deg, along_m, across_m)
    return Polygon([(x + dx, y + dy) for dx, dy in corners])


def build_obb_geometry(row, lon: float = None, lat: float = None,
                       use_antenna_offset: bool = True,
                       projected: bool = False) -> Polygon | None:
    """
    Tek bir AIS kaydından OBB poligonu üretir.

    Args:
        row: `Length`/`length_m`, `Width`/`width_m`, `Heading`, `COG`,
             `A`, `B`, `C`, `D` alanlarını taşıyan satır (dict veya Series).
        lon, lat: Konum. Verilmezse `row`'daki `Longitude`/`Latitude` kullanılır.
                  `projected=True` iken bunlar projekte edilmiş x/y'dir.
        use_antenna_offset: A/B/C/D ile merkez düzeltmesi uygulansın mı.
        projected: True ise metrik projeksiyonda üretir.

    Returns:
        Polygon, ya da geçersiz/eksik boyut varsa None.
    """
    length_m = _first_numeric(row, "length_m", "Length")
    width_m = _first_numeric(row, "width_m", "Width")

    if length_m is None or width_m is None:
        return None
    if length_m <= 0 or width_m <= 0:
        return None

    heading_deg = ship_orientation(_get(row, "Heading"), _get(row, "COG"))

    if use_antenna_offset:
        along_m, across_m = center_offset_m(
            length_m, width_m,
            _get(row, "A"), _get(row, "B"), _get(row, "C"), _get(row, "D"),
        )
    else:
        along_m, across_m = 0.0, 0.0

    if lon is None:
        lon = _first_numeric(row, "Longitude", "x")
    if lat is None:
        lat = _first_numeric(row, "Latitude", "y")
    if lon is None or lat is None:
        return None

    builder = obb_polygon_projected if projected else obb_polygon_wgs84
    return builder(lon, lat, length_m, width_m, heading_deg, along_m, across_m)


# --------------------------------------------------------------------------
# Yardımcılar
# --------------------------------------------------------------------------
def _get(row, key):
    """dict ve pandas.Series için ortak, güvenli alan erişimi."""
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return None
    return None if value is None or (np.isscalar(value) and pd.isna(value)) else value


def _first_numeric(row, *keys):
    """Verilen anahtarlardan ilk geçerli sayısal değeri döndürür."""
    for key in keys:
        value = _get(row, key)
        if value is None:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isnan(numeric):
            return numeric
    return None
