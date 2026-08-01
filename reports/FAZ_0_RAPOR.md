# Faz 0 Raporu — Zemini Sabitle

**Tarih:** 2026-08-01
**Durum:** ✅ Tamamlandı, tüm doğrulama kapıları geçti
**Kapsam:** Tekrarlanabilirliği geri kazanmak. Hiçbir algoritma mantığı değiştirilmedi.

---

## 1. Doğrulama kapıları

| # | Kapı | Sonuç |
|---|---|---|
| 1 | Tüm modül import'ları çalışıyor | ✅ PASS (torch CUDA: True) |
| 2 | `geoport/obb.py` referans çıktıyı birebir üretiyor | ✅ **1308/1308 poligon, sapma 0.0000 m** |
| 3 | Git'te binary yok | ✅ 23 takipli dosya, **0 binary** (önce 145) |
| 4 | Kaynak veri korundu, eski çıktılar arşivlendi | ✅ |
| 5 | Eski scriptler sessizce yanlış çalışmıyor | ✅ 12/12 script güvenli duruyor |

---

## 2. Yapılanlar

### 2.1 Arşivleme
Şu klasörler `_deprecated_20260801/` altına **taşındı** (silinmedi — teşhis kanıtı):

| Klasör | Dosya | Sebep |
|---|---|---|
| `runs/` | 109 | OBB eğitimlerinde loss=0/mAP=0; HBB modeli harici veri setiyle eğitilmiş |
| `data/yolo_dataset/` | 9594 | Etiketlerin %70'i dejenere |
| `data/hybrid_results/` | 2 | Karo başına 13.3 yanlış alarm; OBB kolunda 0 tespit |
| `data/dark_vessel_results/` | 4 | Eski koddan kalma rapor; 11 dark vessel'ın 3 çifti kopya |
| `data/cfar_*` | 10 | Kalibre edilmemiş CFAR çıktısı |

Korunanlar: `data/sentinel1/` (kaynak + SNAP float), `data/ground_truth*`,
`data/land_mask/`, AIS CSV'leri, `data/combined_sar/`.

### 2.2 `config.py` → tek parametre kaynağı
- Eskiden CFAR parametreleri hem `config.py` hem `cfar_detector.py`'de **farklı değerlerle** vardı.
- Yeni yapı fazlara göre bölümlenmiş, her parametrenin yanında dayandığı ölçüm yazılı.
- **Import sırasındaki `os.makedirs` yan etkisi kaldırıldı** → artık açık `ensure_dirs()` çağrısı.
- Eski isimler (`STOREBAELT_BBOX`, `SAR_NORMALIZED_DIR`, `DEFAULT_YOLO_MODEL_PATH` …)
  bilinçli olarak **kaldırıldı**, böylece eski kod sessizce değil gürültülü çöküyor.

### 2.3 `geoport/` paketi + `obb.py`
Silinmiş `compute_ship_obb.py` tersine mühendislikle çözüldü ve yeniden yazıldı.
Çözülen mantık:
- Yön: `Heading` → yoksa `COG` → yoksa `0.0` (veride 65 / 19 / 31 dağılımı)
- Merkez ötelemesi: `along = A − L/2`, `across = D − W/2`

### 2.4 Bağımlılıklar ve git
- `requirements.txt`: 7 paketten **20 sabitlenmiş sürüme** çıktı
  (eksikti: rasterio, shapely, scipy, ultralytics, torch, fastapi, uvicorn, tqdm, pyproj, pyogrio, matplotlib).
- `.gitignore`: `data/`, `runs/`, `*.pt`, raster/geojson uzantıları, `venv/`, `_deprecated_*/`.
- Git index yeniden kuruldu: **145 binary → 0**.
- ⚠️ **Commit atılmadı** — senin kararın. Değişiklikler staged durumda.

---

## 3. Faz 0 sırasında bulunan hatalar

### 🔴 H-1: Config kullanmayan scriptler sessizce çalışıyordu

Eski scriptleri "gürültülü çöküyor mu" diye test ederken `tile_and_label.py`
**çökmedi, çalışmaya başladı** ve 238 dosyalık bozuk bir veri seti üretmeye
koyuldu. Sebep: o dosya `config`'i hiç import etmiyor, kendi sabitlerini
tanımlıyor — dolayısıyla config'ten isim kaldırmak onu durdurmuyor.

**Etki:** Bu, planın "eski kod artık çalışmaz" varsayımını çürüttü. Tespit
edilmeseydi, ileriki bir fazda yanlışlıkla çalıştırılan bir script bozuk veriyi
sessizce geri getirebilirdi.

**Çözüm:** 9 scripte, dosyanın başına açık `SystemExit` bariyeri kondu. Her biri
**neden** kapatıldığını ve **hangi fazda** neyle değişeceğini söylüyor.
Doğrulandı: 12/12 script artık güvenli duruyor.

### 🔴 H-2: `download_ais.py` sorgusuz ağ indirmesi başlatıyor

Aynı testte `download_ais.py` çalıştı ve **248 MB'lık** bir günlük AIS dosyasını
indirmeye başladı. Onay sormuyor, kaynak sınırı yok.

**Etki:** Kazara çalıştırma = gereksiz ağ/disk tüketimi. Yarım inen dosya silindi.

**Çözüm:** Bariyer kondu + `TECHNICAL_PLAN.md` Faz 2'ye "indirme adımı onay/limit
istemeli" notu.

### 🟠 H-3: "Doğrulama" scripti hiçbir şey doğrulamadan başarılı dönüyor

`verify_dark_vessel_results.py`, rapor dosyası yoksa `return` ile **exit code 0**
veriyor. Yani CI'da veya elle çalıştırıldığında "her şey yolunda" görünüyor.

**Etki:** Yanlış güven. Bu script zaten arşivlenen eski raporu "doğruluyordu".

**Çözüm:** Bariyer kondu; Faz 7'de eksik girdi = başarısızlık olacak şekilde yazılacak.

### 🟡 H-4: `gdalwarp` CLI kurulu değil

Faz 1 planı `gdalwarp` komut satırı aracına dayanıyordu; makinede yok
(PATH'te de, venv'de de).

**Çözüm:** `rasterio.warp` **aynı GDAL 3.10.3 motorunu** kullanıyor →
plan buna çevrildi. Algoritma aynı, üstelik alt süreç bağımlılığı yok.

### 🟡 H-5: Bellek kısıtı (Faz 1 için)

Kaynak bant **50707 × 21278 × float32 = 4.32 GB**. Tek seferde belleğe alınamaz.
Faz 1 `WarpedVRT` + pencereli okuma/yazma kullanacak.

---

## 4. Kendi hatalarım (şeffaflık)

İki yan etki **benim test yönteminden** kaynaklandı, koddan değil:

1. Eski scriptleri `--help` ile test ettim; `tile_and_label.py`'de argparse
   olmadığı için doğrudan main bloğu çalıştı → 238 dosya üretildi. **Silindi**,
   arşiv (9594 dosya) sağlam kaldı.
2. Aynı test `download_ais.py`'de 248 MB indirme başlattı. **Silindi.**

Her ikisi de geri alındı ve ikisi de H-1/H-2 bariyerleriyle kalıcı olarak kapatıldı.
Ders: **bilinmeyen bir scripti çalıştırarak test etme** — önce statik olarak oku.

---

## 5. Plan düzeltmeleri (TECHNICAL_PLAN.md güncellendi)

| Düzeltme | Detay |
|---|---|
| ❌→✅ AIS anten ofseti | Plan "eklenmeli" diyordu; **zaten doğru yapılıyormuş**. Ölçüm: merkez–nokta sapması ort. 13.4 m, max 86 m; 244 m'lik gemide beklenen `A−L/2 = 84 m` ile birebir. Faz 2'de tek değişiklik: WGS84 yerine UTM'de üretmek. |
| Faz 1 aracı | `gdalwarp` CLI → `rasterio.warp` |
| Faz 1 girdisi | `_normalized.tif` (uint8) → `Sigma0_*.img` (float32) — çift kuantalama önlenir |
| Faz 1 bellek | `WarpedVRT` + pencereli işleme zorunlu (4.32 GB/bant) |
| `DARK_VESSEL_MIN_CONF` | Sadece "düşük" değil, **tamamen etkisiz**: 871 tespitin %100'ü zaten conf ≥ 0.25 (ultralytics'in yazılı olmayan varsayılanı). Gerçek eşik görünmezdi. |
| Val split | Sıralı indeks → **açık sahne listesi** (`VAL_SCENES`) |

---

## 6. Faz 1'e hazırlık durumu

| Ön koşul | Durum |
|---|---|
| Kaynak float veri (`Sigma0_VV/VH.img`) | ✅ 10 sahnede de mevcut |
| Reprojeksiyon aracı | ✅ `rasterio.warp` (GDAL 3.10.3) |
| AOI tek tanım | ✅ `config.AOI_BBOX_WGS84` |
| Hedef CRS / çözünürlük | ✅ EPSG:32632 / 10 m |
| Bellek stratejisi | ✅ pencereli işleme planlandı |
| Eski kod karışmaz | ✅ 12/12 script bariyerli |

**Faz 1'de dikkat edilecek:** 10 sahnenin sadece 4'ü AOI'yi tam kapsıyor.
Her sahne için *geçerli veri footprint'i* üretilmeli — aksi halde uydunun hiç
bakmadığı bölgedeki AIS gemileri "ghost signal" sayılmaya devam eder.
