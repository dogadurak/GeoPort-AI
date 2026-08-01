"""
GeoPort-AI — Merkezi Konfigürasyon
==================================
Projedeki **tek** parametre kaynağı. Hiçbir modül kendi sabitini tanımlamaz;
hepsi buradan import eder.

Neden böyle: 2026-08-01 incelemesinde CFAR parametrelerinin hem bu dosyada hem
`cfar_detector.py` içinde **farklı değerlerle** tanımlı olduğu görüldü. Bu yüzden
bir düzeltme her yere yansımıyor, "bir hatayı düzeltince başkası çıkıyor"
döngüsü oluşuyordu. Tek kaynak ilkesi bunu kökten bitirir.

Her parametrenin yanında hangi fazda aktifleştiği ve dayandığı ölçüm yazılıdır.
Ayrıntılar: TECHNICAL_PLAN.md
"""

import os

# ============================================================================
# Yollar
# ============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

# --- Kaynak veri (Faz 1 girdisi) ---
SAR_SAFE_DIR = os.path.join(DATA_DIR, "sentinel1")
SAR_SNAP_DIR = os.path.join(DATA_DIR, "sentinel1", "sentinel1_processed")

# --- Faz 1 çıktıları: UTM'ye projekte edilmiş, AOI'ye kırpılmış ---
SAR_UTM_DIR = os.path.join(DATA_DIR, "sentinel1", "utm")          # float32 dB
SAR_RENDER_DIR = os.path.join(DATA_DIR, "sentinel1", "render")    # uint8 (YOLO için)
FOOTPRINT_DIR = os.path.join(DATA_DIR, "footprints")              # geçerli veri poligonları
LAND_MASK_DIR = os.path.join(DATA_DIR, "land_mask")

# --- Faz 2 çıktıları: temizlenmiş ground truth ---
AIS_COMBINED_PATH = os.path.join(DATA_DIR, "storebaelt_combined_dedup.csv")
AIS_GROUND_TRUTH_DIR = os.path.join(DATA_DIR, "ground_truth")
AIS_OBB_DIR = os.path.join(DATA_DIR, "ground_truth_obb")

# --- Faz 3 çıktısı ---
YOLO_DATASET_DIR = os.path.join(DATA_DIR, "yolo_dataset")

# --- Faz 4-6 çıktıları ---
DETECTION_DIR = os.path.join(DATA_DIR, "detections")
DARK_VESSEL_RESULTS_DIR = os.path.join(DATA_DIR, "dark_vessel_results")

# ============================================================================
# Coğrafi çerçeve  [Faz 1]
# ============================================================================
# TEK AOI TANIMI. Eskiden üç ayrı bbox vardı ve birbirini tutmuyordu:
#   download_ais.py     : 10.5-11.3 / 55.0-55.6
#   config.STOREBAELT   : 10.0-12.0 / 55.0-56.0   <- AIS'ten genişti
#   gerçek SAR sahnesi  :  8.7-13.2 / 54.0-55.9
# config bbox'ı AIS'ten geniş olduğu için, AIS kapsamı dışında bulunan HER
# tespit otomatik "dark vessel" oluyordu — sistematik sahte pozitif kaynağı.
AOI_MIN_LON, AOI_MIN_LAT = 10.50, 55.00
AOI_MAX_LON, AOI_MAX_LAT = 11.30, 55.60
AOI_BBOX_WGS84 = (AOI_MIN_LON, AOI_MIN_LAT, AOI_MAX_LON, AOI_MAX_LAT)

# SNAP çıktısı 10 m/px'i dereceye çevirirken enlem düzeltmesi yapmamıştı:
#   55°N'de X = 5.69 m/px, Y = 10.00 m/px  ->  1.757x anizotropi
# Bu, CFAR penceresini elips yapıyor ve tüm piksel-mesafe eşiklerini bozuyordu.
TARGET_CRS = "EPSG:32632"     # UTM Zone 32N — Danimarka için doğru zon
TARGET_RES_M = 10.0           # kare piksel
SOURCE_CRS = "EPSG:4326"

# Hangi polarizasyon kullanılacak. Faz 4a'da VV / VH / oran karşılaştırılıp
# ROC eğrisine göre seçilecek; şimdilik ikisi de warp ediliyor.
POLARIZATIONS = ("VV", "VH")
PRIMARY_POLARIZATION = "VV"

# dB dönüşümü için taban (lineer sigma0 = 0 olan pikseller için)
SIGMA0_FLOOR = 1e-6

# ============================================================================
# Gemi filtreleme  [Faz 2]
# ============================================================================
# Sentinel-1 GRDH efektif çözünürlük ~20 m. AIS'teki 1308 kaydın %52'si 20 m'den
# kısa, %75'i SOG=0 (marina/liman içi duran tekneler). Bunlar fiziken tespit
# edilemez; etiket olarak verilince modele gürültü öğretiliyordu (etiketlerin
# %70'i dejenere: kısa kenar < 1.5 px).
MIN_SHIP_LENGTH_M = 30.0      # 1308 kayıt -> 390 kayıt (%30)

# AIS zaman hizalama. Ölçüm: medyan 25.5 s, %90 dilim 112 s, en kötü 591 s.
# 12 knot'ta 112 s = 690 m, 591 s = 3.6 km konum hatası.
AIS_MAX_TIME_DIFF_S = 300.0   # bundan uzak kaydı at (güvenilmez)
AIS_SEARCH_WINDOW_S = 600.0   # enterpolasyon için aday arama penceresi
AIS_INTERPOLATE = True        # kuşatan iki kayıt arasında lineer enterpolasyon
AIS_DEAD_RECKON = True        # tek taraf varsa SOG/COG ile ölü hesap

# AIS anten konumu gemi merkezi değildir. A/B/C/D alanları (baş/kıç/sancak/
# iskele mesafeleri) veride mevcut; poligon bunlarla merkezlenir.
# 200 m'lik bir gemide 50 m'ye varan kaymayı düzeltir.
AIS_USE_ANTENNA_OFFSET = True

# ============================================================================
# Karolama  [Faz 3]
# ============================================================================
TILE_SIZE = 512
TILE_OVERLAP = 128
TILE_STEP = TILE_SIZE - TILE_OVERLAP

# Karo dışına taşan gemi. Eskiden 0.3 idi ve köşeler [0,1]'e clip ediliyordu —
# geminin %70'i dışarıdayken dikdörtgen tamamen deforme oluyordu.
# 0.8 ile: yeterince içerideyse etiketle, değilse at (komşu karo zaten yakalıyor).
MIN_OVERLAP_RATIO = 0.8

BLANK_STD_THRESHOLD = 1.0     # bu değerin altındaki karo boş sayılır
NEGATIVE_RATIO = 3.0          # pozitif başına kaç negatif karo (deterministik)
RANDOM_SEED = 42              # tekrarlanabilirlik

# Val sahneleri AÇIK liste ile seçilir, sıralı indeksle değil.
# Eskiden sorted(glob())[:2] idi — hangi sahnenin val'e düştüğü tesadüfe kalmıştı.
# Biri AOI'yi TAM kapsıyor, biri KISMİ: her iki durumu da değerlendirebilelim.
VAL_SCENES = (
    "20260504T053257",   # AOI TAM kapsama
    "20260518T052345",   # AOI KISMİ kapsama (lon < 10.92 yok)
)

# ============================================================================
# CFAR dedektörü  [Faz 4a]
# ============================================================================
# Ölçüm: 2151 karoda 28.688 tespit = karo başına 13.3 yanlış alarm.
# PFA=1e-7'de 512x512 karoda beklenen: 0.026. 500x sapma.
CFAR_GUARD_RADIUS = 2         # piksel (artık 10 m kare -> gerçekten dairesel)
CFAR_BG_RADIUS = 15
CFAR_PFA = 1e-7

# YAPISAL HATA DÜZELTMESİ: eski MAX=30 px, 244 m x 42 m'lik gerçek bir gemiyi
# (~180 px küme) REDDEDİYORDU. Yani filtre tam ters çalışıyordu — aradığımızı
# atıp gürültüyü alıyordu. 28.688 tespitin gürültü olmasının asıl sebebi buydu.
CFAR_MIN_CLUSTER_PX = 3       # 30 m gemi @ 10 m/px ~ 3 px  (eski: 1 = tek piksel gürültü)
CFAR_MAX_CLUSTER_PX = 400     # 400 m x 60 m süper tanker ~ 240 px  (eski: 30)

# CFAR artık uint8 render üzerinde değil, kalibre edilmiş dB verisi üzerinde
# çalışır. Eski MIN_BRIGHTNESS=120 / LAND_THRESHOLD=200 sahne-bağımlıydı:
# normalize_sar.py her sahne için 1-99 persentil hesapladığı için "255" her
# sahnede farklı bir dB'ye karşılık geliyordu.
CFAR_MIN_DB = -20.0           # bu dB'nin altı gemi adayı sayılmaz
CFAR_USE_LAND_MASK = True

# ============================================================================
# YOLO  [Faz 4b]
# ============================================================================
YOLO_BASE_MODEL = "yolov8n-obb.pt"
YOLO_TRAINED_MODEL = os.path.join(BASE_DIR, "runs", "obb", "geoport_v1", "weights", "best.pt")
YOLO_EPOCHS = 100
YOLO_IMGSZ = TILE_SIZE
YOLO_BATCH = 16
YOLO_DEVICE = None            # None = otomatik (GPU varsa GPU). Eskiden device=0 sabitti.

# GİZLİ VARSAYILAN DÜZELTMESİ: ultralytics predict varsayılan conf=0.25 uygular
# ve bu değer kodun hiçbir yerinde yazmıyordu. Ölçüm: mevcut 871 YOLO tespitinin
# %100'ü zaten conf >= 0.25 — yani DARK_VESSEL_MIN_CONF=0.05 tamamen ölü koddu.
# Hattın gerçek karar eşiği kimsenin görmediği örtük bir varsayılandı.
YOLO_PREDICT_CONF = 0.25      # artık AÇIK olarak predict(conf=...)'a verilir
YOLO_PREDICT_IOU = 0.45

# ============================================================================
# Füzyon ve tekilleştirme  [Faz 5]
# ============================================================================
# Karolar 128 px örtüşüyor. Eskiden sahne düzeyinde dedup yoktu; kanıt:
# 11 dark vessel'ın 3 çifti aynı gemiydi (aynı mutlak piksel, aynı lon/lat).
FUSION_NMS_DISTANCE_M = 20.0  # bu mesafeden yakın iki tespit aynı gemidir
FUSION_NMS_IOU = 0.30         # OBB'ler için dönük IoU eşiği
CFAR_YOLO_MERGE_DISTANCE_M = 50.0   # CFAR ve YOLO aynı gemiyi gördüyse birleştir

# ============================================================================
# AIS eşleştirme ve karanlık gemi  [Faz 6]
# ============================================================================
# Eski değer 2000 m idi ve raporlanan ortalama eşleşme mesafesi 1355 m'ydi —
# 10 m çözünürlüklü bir sensörde bu eşleşme değil, tesadüf. 300 m'yi mümkün
# kılan şey Faz 2'deki zaman enterpolasyonu; o olmadan 300 m savunulamazdı.
MATCH_DISTANCE_M = 300.0
MATCH_USE_GATED_HUNGARIAN = True   # eşik üstü maliyetlere BIG_M ata

# Dark vessel ilan etme koşulları (hepsi sağlanmalı)
DARK_VESSEL_MIN_CONF = 0.40        # eski 0.05 etkisizdi (yukarı bkz.)
DARK_VESSEL_MIN_LENGTH_M = 30.0    # ground truth eşiğiyle tutarlı
DARK_VESSEL_MIN_SHORE_DIST_M = 300.0  # kıyı yansıması / iskele artefaktı filtresi

# ============================================================================
# Yardımcılar
# ============================================================================
def ensure_dirs():
    """Çıktı klasörlerini oluşturur. Import sırasında DEĞİL, açıkça çağrılır."""
    for path in (SAR_UTM_DIR, SAR_RENDER_DIR, FOOTPRINT_DIR, LAND_MASK_DIR,
                 AIS_GROUND_TRUTH_DIR, AIS_OBB_DIR, YOLO_DATASET_DIR,
                 DETECTION_DIR, DARK_VESSEL_RESULTS_DIR):
        os.makedirs(path, exist_ok=True)
