"""
GeoPort-AI — ortak kütüphane.

Tüm iş mantığı burada yaşar. `01_data_collection/` .. `05_analysis/` altındaki
scriptler yalnızca ince kabuktur: argüman ayrıştırır, buradaki fonksiyonları çağırır.

Neden: 2026-08-01 incelemesinde aynı mantığın birden çok kopyası, farklı sabitlerle
bulundu (CFAR parametreleri iki dosyada farklı; detect_ships.py ile
detect_ships_obb.py %80 aynı). Tek kopya = bir düzeltme her yere yansır.
"""

__version__ = "0.1.0"
