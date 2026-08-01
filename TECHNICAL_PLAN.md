# GeoPort-AI — Teknik Düzeltme ve Yeniden Yapılandırma Planı

> Hazırlanma tarihi: 2026-08-01
> Kapsam: Storebælt (Danimarka) Sentinel-1 SAR + AIS karanlık gemi tespit hattı
> Durum: Onay bekliyor — **henüz kod değiştirilmedi**

---

## 0. Bu doküman neden var

Şu anki hat çalışıyor gibi görünüyor ama ürettiği sayılar doğru değil. Tek tek hata
düzeltmek işe yaramıyor, çünkü hatalar bağımsız değil — biri diğerini besliyor.
Bu plan, zinciri **baştan sona ve doğru sırayla** çözmek için yazıldı.

Her fazın sonunda **ölçülebilir bir doğrulama kapısı** var. Kapı geçilmeden bir
sonraki faza geçilmez. Amaç budur: bir daha "düzelttim, başka yer bozuldu" olmasın.

---

## 1. Kabul kriterleri (projenin "bitti" tanımı)

| Kriter | Şu an | Hedef |
|---|---|---|
| Model kendi verimizle eğitilmiş | ❌ harici veri seti | ✅ Storebælt karoları |
| OBB eğitimi gerçekten öğreniyor | ❌ loss = 0 | ✅ loss düşüyor, mAP50 > 0.5 |
| Dejenere etiket oranı | 70% | **< 5%** |
| CFAR yanlış alarm / karo | 13.3 | **< 0.5** |
| Eşleşen gemilerin ort. mesafesi | 1355 m | **< 150 m** |
| Aynı gemi çift sayımı | var (11'de 3 çift) | **0** |
| Sahne kapsamı dışı AIS "ghost" sayılıyor | ❌ evet | ✅ hayır (hariç tutulur) |
| Hat tek komutla baştan sona çalışıyor | ❌ | ✅ |

---

## 2. Kök neden zinciri

```
┌─ AIS bbox sahnenin %5.5'ini kapsıyor ───┐
├─ Piksel kare değil (5.69 m × 10.00 m) ──┼──▶ Etiketlerin %70'i dejenere
└─ Gemi boyu filtresi yok (%52'si <20 m) ─┘         │
                                                    ▼
                                    YOLO-OBB eğitimi loss=0 → hiç öğrenmedi
                                                    │
                                                    ▼
                        Üretimde harici veri setiyle eğitilmiş HBB modeli kullanılıyor
                                                    │
                                                    ▼
                        115 AIS gemisine karşılık 17 tespit (%5 recall)
                        CFAR MAX_CLUSTER=30 px büyük gemileri reddediyor → 28.688 gürültü
                                                    │
                                                    ▼
                        2 km eşikle "eşleşme" uyduruluyor (ort. 1355 m)
                        Karo örtüşmesi tekilleştirilmiyor → aynı gemi 2 kez dark vessel
```

**Kritik gözlem:** `CFAR_MAX_CLUSTER_SIZE = 30 px` ayarı, 244 m × 42 m'lik bir gemiyi
(~180 piksellik parlak küme) **reddediyor**. Yani CFAR yapısal olarak tam da tespit
etmek istediğimiz büyük gemilere kör; geriye sadece tek piksellik benek gürültüsü
kalıyor. 28.688 tespitin gürültü olmasının sebebi bu.

---

## 3. Hedef mimari

Şu anki en büyük mimari sorun: **aynı mantığın 3 kopyası, farklı sabitlerle.**
CFAR parametreleri hem `config.py` hem `cfar_detector.py` içinde ve **değerleri farklı**.
`detect_ships.py` ile `detect_ships_obb.py` %80 aynı. Bu yüzden bir düzeltme
her yere yansımıyor — "bir hatayı düzeltince başkası çıkıyor" hissinin teknik sebebi bu.

Çözüm: **iş mantığı tek bir pakette, çalıştırılabilir scriptler ince kabuk.**

```
geoport-ai/
├── config.py                 ← TEK parametre kaynağı (AOI, CRS, eşikler)
├── geoport/                  ← YENİ: ortak kütüphane
│   ├── aoi.py                   AOI tanımı, sahne footprint kesişimi, geçerli veri maskesi
│   ├── raster.py                raster açma, pencere, piksel↔coğrafi dönüşüm
│   ├── ais.py                   AIS okuma, temizleme, zaman enterpolasyonu, boy filtresi
│   ├── obb.py                   AIS kaydı → OBB poligonu (compute_ship_obb'nin yerine)
│   ├── detect/
│   │   ├── cfar.py              CFAR dedektörü (tek implementasyon)
│   │   ├── yolo.py              YOLO/YOLO-OBB sarmalayıcı (HBB+OBB tek yerde)
│   │   └── fusion.py            karo→sahne birleştirme + global NMS
│   ├── match.py                 gated Hungarian eşleştirme
│   └── schema.py                çıktı GeoJSON şeması (tek format)
├── 01_data_collection/       ← ince kabuk (argüman ayrıştır → geoport'u çağır)
├── 02_preprocessing/
├── 03_training/
├── 04_inference/
├── 05_analysis/
└── dashboard/
```

Numaralı klasör yapısı kalıyor — okunabilir ve hattın sırasını anlatıyor.
Sadece içleri boşalıp mantık `geoport/`'a taşınıyor.

---

## 4. Fazlar

### FAZ 0 — Zemini sabitle

**Amaç:** Bir daha aynı hataya düşmeyecek şekilde tekrarlanabilirliği geri kazanmak.
Kod mantığı değişmez, sadece eksikler tamamlanır ve yanıltıcı çıktılar arşivlenir.

**Yapılacaklar**

1. **Eski çıktıları arşivle.** `data/dark_vessel_results/`, `data/hybrid_results/`,
   `data/yolo_dataset/`, `runs/` → `_deprecated_20260801/` altına taşı.
   *Gerekçe:* `dark_vessel_report.json` şu an eski koddan kalma (`total_yolo` anahtarı
   var, kod `total_sar_detections` yazıyor) ve `verify_dark_vessel_results.py` bu eski
   raporu "doğruluyor". Yanlış güven veriyor.
2. **`compute_ship_obb.py`'yi yeniden yaz** → `geoport/obb.py`.
   *Gerekçe:* `data/ground_truth_obb/` çıktıları var ama üretici kod silinmiş.
   Ölçtüm, poligonlar metrik olarak **doğru** (cos(lat) düzeltmesi yapılmış,
   kenarlar tam 20.0 m / 4.0 m) — mantığı bu referanstan yeniden kurabiliriz.
3. **`requirements.txt`'i tamamla:** `rasterio`, `shapely`, `scipy`, `ultralytics`,
   `torch`, `fastapi`, `uvicorn`, `tqdm`, `matplotlib` eksik. Sürümleri sabitle.
4. **`.gitignore`:** `runs/`, `*.pt`, `data/` ekle; takipli ağırlıkları
   `git rm --cached` ile çıkar. (Şu an yüzlerce MB `.pt` git'te.)
5. **`runs/detect/runs/detect/...` iç içe klasörlerini** temizle.
6. **`config.py`'yi tek kaynak yap:** `cfar_detector.py:36-42`'deki kopya
   sabitleri sil, `config`'ten import et.

**Doğrulama kapısı**
- `pip install -r requirements.txt` temiz bir venv'de sorunsuz geçer
- `python -c "import geoport.obb"` çalışır
- `geoport/obb.py` mevcut `ground_truth_obb` dosyalarını **birebir** yeniden üretir
  (kenar uzunlukları ±0.1 m tolerans)
- `git status` içinde `.pt` dosyası yok

**Risk:** Düşük. Mantık değişmiyor.

---

### FAZ 1 — Geometri temeli ⭐ *en kritik faz*

**Amaç:** Kare pikselli, projekte edilmiş, AOI'ye kırpılmış raster. Bundan sonraki
her şey (etiket, CFAR penceresi, piksel mesafeleri, NMS) buna dayanıyor.

**Sorunun teyidi**

SNAP graph'ı (`data/sentinel1/myGraph.xml`) şunu yapmış:
```xml
<pixelSpacingInMeter>10.0</pixelSpacingInMeter>
<pixelSpacingInDegree>8.983152841195215E-5</pixelSpacingInDegree>
<mapProjection>WGS84</mapProjection>     ← sorun burada
```
10 m'yi dereceye çevirirken enlem düzeltmesi yok. Sonuç 55°N'de:
- X: 8.983e-5° × 111320 × cos(55.3°) = **5.69 m/px**
- Y: 8.983e-5° × 111320 = **10.00 m/px**
- Anizotropi: **1.757×**

**Yapılacaklar**

1. **AOI'yi tek kaynak yap.** `config.py`'de tek bir tanım:
   ```
   AOI_BBOX_WGS84 = (10.50, 55.00, 11.30, 55.60)   # AIS indirme bbox'ı ile aynı
   TARGET_CRS     = "EPSG:32632"                    # UTM Zone 32N
   TARGET_RES_M   = 10.0
   ```
   *Gerekçe:* Şu an üç farklı bbox var (`download_ais.py` 10.5–11.3 /
   `config.STOREBAELT_BBOX` 10.0–12.0 / gerçek sahne 8.66–13.21). `config`'inki
   AIS'inkinden geniş olduğu için AIS kapsamı dışındaki her tespit otomatik
   "dark vessel" oluyordu. Tek bbox → bu sınıf hata tamamen ortadan kalkar.

2. **Yeniden projekte et + kırp.**

   > **Faz 0'da ortaya çıktı:** `gdalwarp` CLI bu makinede **kurulu değil**
   > (PATH'te de, venv'de de yok). Ama `rasterio.warp` var ve **aynı GDAL 3.10.3
   > motorunu** kullanıyor. Dolayısıyla warp Python içinden yapılacak — algoritma
   > birebir aynı, üstelik alt süreç/PATH bağımlılığı yok ve pencere pencere
   > çalışabildiğimiz için bellek kontrol altında.

   > **Bellek kısıtı:** Kaynak bant 50707 × 21278 × float32 = **4.32 GB**.
   > Tek seferde belleğe alınamaz. `WarpedVRT` + pencereli okuma/yazma
   > kullanılacak, `reproject()`'e tüm diziyi vermeyeceğiz.

   Parametreler: `dst_crs=EPSG:32632`, `resolution=(10, 10)`,
   `resampling=bilinear`, hedef sınırlar AOI'nin UTM karşılığı,
   `dst_nodata=0`, `compress=LZW`, `tiled=True`.

   Boyut: 50707×21278 → **~5100 × 6700 px** (sahne başına).

   Girdi olarak `Sigma0_VV.img` / `Sigma0_VH.img` (float32) kullanılacak,
   `_normalized.tif` (uint8) değil — bkz. E3.

3. **Sahne footprint'ini çıkar** → `geoport/aoi.py`.
   *Kritik:* 10 sahnenin **sadece 4'ü** AOI'yi tam kapsıyor:

   | Sahne | AOI kapsama | Eksik kısım |
   |---|---|---|
   | 20260504 | ✅ TAM | — |
   | 20260609 | ✅ TAM | — |
   | 20260515 | ✅ TAM | — |
   | 20260522 | ✅ TAM | — |
   | 20260604 | ⚠️ KISMİ | lon < 10.70 yok |
   | 20260501 | ⚠️ KISMİ | lat > 55.57 yok |
   | 20260508 | ⚠️ KISMİ | lat > 55.53 yok |
   | 20260601 | ⚠️ KISMİ | lat > 55.53 yok |
   | 20260529 | ⚠️ KISMİ | lon < 10.91 yok (AOI'nin yarısı) |
   | 20260518 | ⚠️ KISMİ | lon < 10.92 yok (AOI'nin yarısı) |

   Sahne kapsamadığı bir bölgedeki AIS gemisi **"ghost signal" sayılamaz** —
   orada uydu bakmıyor ki. Şu an sayılıyor. `geoport/aoi.py` her sahne için
   *geçerli veri footprint'i* (nodata=0 maskesinden türetilen gerçek kapsama
   poligonu) üretecek ve hem etiketleme hem değerlendirme bunu kullanacak.

4. **Kara maskelerini yeni CRS'te yeniden üret** (`generate_landmask.py`).

**Doğrulama kapısı**
- Her `_utm.tif` için `abs(transform.a) == 10.0` ve `abs(transform.e) == 10.0`
- CRS == EPSG:32632
- AOI içindeki bilinen bir geminin (AIS'ten) piksel konumu, SAR'daki parlak
  noktayla **< 3 piksel** hizalı (görsel + sayısal kontrol)
- Sahne başına karo penceresi: 7448 → **~252** (29× azalma)

**Risk:** Orta. `gdalwarp` ikinci bir yeniden örnekleme demek — nokta hedefler
hafifçe yumuşar. Gemi tespiti için kabul edilebilir; alternatifi (SNAP'ten yeniden
üretim) saatler sürerdi. `-r bilinear` yerine `-r near` de test edilecek
(nokta hedefleri korur, kenarları sertleştirir).

---

### FAZ 2 — Ground truth'u dürüstleştir

**Amaç:** Model'e ve değerlendirmeye, gerçekten tespit edilebilir gemileri vermek.

**Sorunun teyidi**

1308 AIS kaydında:
- **%52'si 20 m'den kısa**, %75'i SOG=0 (marina/liman içi duran tekneler)
- Sentinel-1 GRDH efektif çözünürlük ~20 m → 11 m'lik tekne **fiziken görünmez**
- AIS zaman hizalaması: medyan 25.5 s, %90'lık dilim 112 s, en kötü 591 s.
  12 knot'ta 112 s = **690 m**, 591 s = **3.6 km** konum hatası.

**Yapılacaklar**

1. **Boy filtresi: `MIN_SHIP_LENGTH_M = 30`** (senin kararın).
   1308 → **390 kayıt** (%30). En küçük gemi 10 m kare pikselde 3×1 px — YOLO için
   sınırda ama öğrenilebilir. `length_m` yoksa (`Length` alanı boş) kaydı **at**,
   varsayma.

2. **Zaman enterpolasyonu** → `geoport/ais.py`.
   Şu anki `match_ais_sar.py` sadece "SAR anına en yakın kaydı" seçiyor.
   Yeni mantık, her MMSI için:
   - SAR anını **kuşatan** iki AIS kaydı varsa → aralarında **lineer enterpolasyon**
   - Sadece tek taraf varsa → SOG/COG ile **ölü hesap** (dead reckoning)
   - En yakın kayıt > 300 s uzaktaysa → **kaydı at** (güvenilmez)

   Bu, %90'lık dilimdeki 690 m'lik hatayı < 100 m'ye indirir ve
   Faz 6'daki 300 m eşiğini savunulabilir kılar.

3. **AOI + footprint kırpması:** AIS noktaları hem AOI'ye hem **o sahnenin geçerli
   veri footprint'ine** kırpılacak. Kapsam dışı gemiler ground truth'a girmez.

4. **`geoport/obb.py`:** filtrelenmiş AIS kaydından `length_m`, `width_m`,
   `Heading` (yoksa `COG`) ile **UTM'de** OBB poligonu üret
   (`obb_polygon_projected`). Metre biriminde çalıştığımız için cos(lat)
   yaklaşımına gerek yok — daha basit ve bozulmasız.

   > **DÜZELTME (Faz 0):** Planın ilk halinde "AIS anten ofseti (A/B/C/D)
   > kullanılmıyor, eklenmeli" yazıyordu. **Bu iddia yanlıştı.** Tersine
   > mühendislik gösterdi ki silinmiş `compute_ship_obb.py` bunu **zaten doğru
   > yapıyormuş**: poligon merkezi ile AIS noktası arasındaki sapma ortalama
   > 13.4 m, en fazla 86 m; 244 m'lik gemide beklenen `A − L/2 = 84 m` ile
   > birebir uyuşuyor. `geoport/obb.py` bu doğru davranışı korudu.
   > Faz 2'de yapılacak tek değişiklik, üretimi WGS84 yerine UTM'de yapmak.

**Doğrulama kapısı**
- Ground truth kayıt sayısı ~390 (± sahne kapsamına göre)
- `length_m >= 30` olmayan kayıt yok
- Zaman hatası > 300 s olan kayıt yok
- Footprint dışı kayıt yok
- Rastgele 20 gemi görsel kontrolde SAR'daki parlak hedefe oturuyor

**Risk:** Düşük. Ölçülebilir ve tersine çevrilebilir.

---

### FAZ 3 — Veri setini sıfırdan üret

**Amaç:** Öğrenilebilir etiketler, dürüst train/val ayrımı.

**Yapılacaklar**

1. **Sadece AOI + footprint içinde karola.** (Faz 1 sayesinde zaten 29× az pencere.)
2. **Kırpma mantığını düzelt.** `tile_and_label.py:38-44` şu an köşeleri [0,1]'e
   clip ediyor; `MIN_OVERLAP_RATIO=0.3` ile geminin %70'i karo dışındayken
   dikdörtgen tamamen deforme oluyor. Yeni kural:
   - Örtüşme ≥ **0.8** → orijinal açıyı koru, etiketi yaz
   - Örtüşme < 0.8 → etiketi **at** (karo örtüşmesi zaten geminin tam halini
     komşu karoda yakalıyor)
3. **Negatif örnekleme:** `NEGATIVE_KEEP_RATIO`'yu sabit rastgele orandan çıkar;
   pozitif:negatif oranını hedefle (örn. 1:3) ve **deterministik seed** kullan.
4. **Split:** sahne bazlı, 8 train / 2 val. Val'de hem TAM hem KISMİ kapsamalı
   sahne olsun. Şu anki %44'lük val oranı anormal.
5. **`data.yaml`'ı üret** (şu an dosya yok — OBB eğitiminin sıfır loss vermesinin
   doğrudan sebebi).

**Doğrulama kapısı**
- Dejenere etiket (kısa kenar < 1.5 px) oranı: **< %5** (şu an %70)
- Etiketli karo oranı: **> %25** (şu an %6)
- `data/yolo_dataset/data.yaml` var ve yolları doğru
- Rastgele 20 karo, etiketleri üstüne çizilmiş halde görsel kontrolden geçer
- 10 sahnenin **10'u da** işlenmiş (şu an 6, biri yarıda kesilmiş: `20260508` = 49 karo)

**Risk:** Düşük.

---

### FAZ 4 — Dedektörleri kalibre et

**Amaç:** İki dedektör de gerçekten çalışsın.

#### 4a. CFAR

**Sorunun teyidi:** 2151 karoda 28.688 tespit = **karo başına 13.3**.
PFA=1e-7'de 512×512 karoda beklenen: **0.026**. 500× sapma.

Sebepler ve düzeltmeleri:

| Sorun | Şu an | Düzeltme |
|---|---|---|
| Büyük gemiler reddediliyor | `MAX_CLUSTER_SIZE=30` px | **400** px (244 m gemi ≈ 180 px) |
| Tek piksel gürültü kabul ediliyor | `MIN_CLUSTER_SIZE=1` | **3** px (30 m gemi ≈ 3 px) |
| Gauss varsayımı geçersiz | `erfinv` tabanlı eşik | Gamma/K-dağılımı CA-CFAR |
| 8-bit render üzerinde çalışıyor | `uint8` PNG | **dB veya lineer sigma0** float |
| Sabit eşikler sahne-bağımlı | `MIN_BRIGHTNESS=120` | dB cinsinden mutlak eşik |
| Anizotropik pencere | 5.69×10 m piksel | Faz 1 sonrası kare (çözüldü) |
| O(N) bileşen döngüsü | `(labeled == i)` her bileşende tam dizi | `ndimage.find_objects` + `center_of_mass` |

**Ek araştırma kalemi:** SNAP graph'ı `Speckle-Filter` uyguluyor. Benek filtresi
tam da CFAR'ın aradığı **nokta hedefleri bastırır**. Filtresiz bir sahne üretip
CFAR performansını karşılaştıracağız. Muhtemel sonuç: tespit kolu için filtresiz,
görselleştirme için filtreli sürüm.

#### 4b. YOLO-OBB

1. `yolov8n-obb.pt`'den başla, **yeni veri setiyle** eğit.
2. `train_yolo.py`'ye kontroller ekle: `device` otomatik (şu an `device=0` sabit,
   GPU yoksa çöker), `data.yaml` varlık kontrolü, epoch 0'dan sonra loss > 0
   assertion'ı.
3. Augmentasyon: `degrees=180` doğru (gemi yönü keyfi), `mosaic=0.0` küçük
   hedeflerde doğru karar. `scale`'i düşük tut (0.15).
4. `config.DEFAULT_YOLO_MODEL_PATH`'i yeni OBB modeline çevir —
   **harici veri setiyle eğitilmiş `geoport_ship_v5_final`'ı bırak.**

**Doğrulama kapısı**
- CFAR: karo başına yanlış alarm **< 0.5**; bilinen büyük gemilerde recall > %80
- YOLO-OBB: `results.csv`'de loss **sıfır değil ve düşüyor**; val mAP50 > 0.5
- İki dedektör de aynı sahnede, aynı bilinen gemide tetikleniyor

**Risk:** Orta-yüksek. CFAR istatistik modelini değiştirmek deneme gerektirir.
Bu yüzden PFA taraması yapıp ROC eğrisi çıkaracağız, tek değer tahmin etmeyeceğiz.

---

### FAZ 5 — Füzyon + sahne düzeyi tekilleştirme

**Amaç:** Aynı gemi bir kez sayılsın.

**Sorunun teyidi** (kendi raporundan, 11 dark vessel'ın 3 çifti kopya):
```
x20736_y4224 px 445  → mutlak 21181  ┐ aynı gemi
x21120_y4224 px  61  → mutlak 21181  ┘  lon 10.561326 / 10.561324
```

**Yapılacaklar**

1. **`detect_ships.py` + `detect_ships_obb.py` → tek `geoport/detect/`.**
   %80 kopya kod ortadan kalkar.
2. **Karo → sahne koordinatı** dönüşümü tespit anında yapılsın (şu an
   `dark_vessel_detector.py`'a kadar erteleniyor).
3. **Sahne düzeyinde global NMS:** karo örtüşme bölgesindeki mükerrer tespitleri
   birleştir. OBB için rotated-IoU, CFAR için mesafe eşiği (< 20 m).
4. **Tek çıktı şeması** (`geoport/schema.py`): HBB ve OBB aynı formatı üretsin.
   Şu an `detect_ships_obb.py` `"YOLO-OBB"` tipi ve `hybrid_detections_obb.json`
   yazıyor, `dark_vessel_detector.py` ise `"YOLO"` tipini ve
   `hybrid_detections.json`'ı okuyor — **iki dosya arası hiçbir bağlantı yok.**
5. `detect_ships_obb.py:58` sınır kontrolü eksikliği (IndexError riski) düzelir.

**Doğrulama kapısı**
- Sentetik test: aynı gemiyi 2 örtüşen karoya koy → çıktıda **1** tespit
- Örtüşme bölgesindeki tespit sayısı, örtüşmesiz taramaya göre **± %5** içinde
- Bir tespitin `scene_x`, `scene_y`, `lon`, `lat` alanları tutarlı

**Risk:** Düşük. Test edilebilir, izole.

---

### FAZ 6 — Karanlık gemi eşleştirmesi

**Amaç:** "Dark vessel" iddiası savunulabilir olsun.

**Sorunun teyidi:** `"matched_avg_distance_m": 1355.6` — eşleşen gemilerin AIS'e
ortalama uzaklığı 1.35 km. 10 m çözünürlüklü sensörde bu eşleşme değil, tesadüf.

**Yapılacaklar**

1. **`MATCH_DISTANCE_M`: 2000 → 300 m.** Faz 2'deki zaman enterpolasyonu artık
   bunu mümkün kılıyor. (Enterpolasyon olmadan 300 m savunulamazdı — asıl sebep
   bu, sıralamanın önemi burada.)
2. **Gated Hungarian:** `dark_vessel_detector.py:146` şu an sınırsız maliyet
   matrisinde global optimum arıyor, eşiği *sonradan* uyguluyor. Doğru gemiler
   yanlış çiftlere kilitlenip eşleşme kaybedilebiliyor.
   Düzeltme: eşik üstü maliyetlere `BIG_M` ata veya dummy sütunlarla dikdörtgen
   atama kur.
3. **Footprint kapısı:** Sahnenin geçerli veri alanı dışındaki AIS gemisi
   **ghost sayılmaz**, "kapsam dışı" olarak ayrı raporlanır.
4. **Kara maskesi performansı:** `dark_vessel_detector.py:292` global Natural
   Earth `unary_union`'ında tek tek `contains()` çağırıyor — STRtree yok,
   `unary_union` deprecated. → `shapely.STRtree` + `union_all()`.
5. **`bbox` liste sütunu** GeoJSON'a yazılamıyor → `schema.py`'de düz alanlara aç.
6. **Dark vessel'a ek kanıt zorunluluğu:** bir tespitin "dark vessel" ilan
   edilebilmesi için asgari güven + asgari boy + karadan asgari mesafe
   koşullarını sağlaması gerekecek. Şu anki 11 dark vessel'ın `nearest_ais_m`
   değerleri 2.4–8.7 km — 115 gemilik yoğun bir boğazda bu kadar izole olmaları,
   bunların gerçek gemi değil **kıyı yansıması / rüzgâr türbini / iz (wake)
   artefaktı** olduğuna işaret ediyor.

**Doğrulama kapısı**
- Eşleşen gemilerin ortalama mesafesi **< 150 m**
- `matched + ghost + kapsam_dışı == toplam_AIS` (kimlik denklemi)
- Her dark vessel için görsel karo çıktısı üretiliyor (manuel doğrulanabilir)
- `verify_dark_vessel_results.py` gerçek invariant'ları kontrol ediyor,
  eski raporu değil

**Risk:** Orta. Dark vessel sayısı muhtemelen **düşecek** — bu iyi haber, çünkü
şu anki sayı şişirilmiş.

---

### FAZ 7 — Değerlendirme ve dashboard

**Yapılacaklar**

1. **Dürüst metrik raporu:** precision / recall / F1, hem CFAR hem YOLO hem füzyon
   için ayrı; gemi boyu sınıfına göre kırılım (30–50 m / 50–100 m / 100+ m).
2. **`verify_*` scriptini gerçek invariant'lara bağla** (yukarıdaki kimlik denklemi,
   CRS kontrolü, tekillik kontrolü).
3. **Dashboard'u yeni şemaya göre güncelle**; "kapsam dışı" katmanını ekle.
   `dashboard/static/index.html`'in varlığı kontrol edilecek (`app.py:21` dosya
   varlık kontrolü yapmadan `FileResponse` döndürüyor).
4. **Tek komutlu hat:** `python run_pipeline.py --from 1 --to 7`.

---

## 4.5. İkinci inceleme bulguları (2026-08-01, bağımsız gözden geçirme)

Bağımsız bir ikinci inceleme yapıldı. Ana teşhis **doğrulandı**. Ortaya çıkan
ek noktalar ve bu plana etkileri:

### E1. `DARK_VESSEL_MIN_CONF = 0.05` sadece düşük değil — **tamamen etkisiz**

`config.py:27`'deki eşik `dark_vessel_detector.py:273`'te uygulanıyor. Ama
ölçtüm: mevcut 871 YOLO tespitinin **%100'ü zaten conf ≥ 0.25**.

```
conf >= 0.05 : 871 (100%)
conf >= 0.25 : 871 (100%)   ← ultralytics'in gizli varsayılanı
conf >= 0.40 : 353 ( 41%)
conf >= 0.50 : 173 ( 20%)
```

Sebep: `yolo_model(img_rgb)` çağrısı ultralytics'in **varsayılan `conf=0.25`**
eşiğini uyguluyor ve bu değer kodun hiçbir yerinde yazmıyor. Yani hattın gerçek
karar eşiği, hiç kimsenin görmediği örtük bir varsayılan; `config.py`'deki 0.05
ise ölü kod.

**Aksiyon (Faz 4b + Faz 6):** Tespit eşiği `predict(conf=...)`'e **açıkça**
verilecek ve `config.py`'de tek yerde tanımlanacak. Dark vessel ilan eşiği
ayrı ve daha yüksek olacak (`DARK_VESSEL_MIN_CONF = 0.40` başlangıç değeri,
Faz 4'teki PR eğrisiyle kalibre edilecek).

> Ders: "parametre düşük" demek yetmiyor — parametrenin **gerçekten etkili olup
> olmadığını** ölçmek gerekiyor. Bu tip gizli varsayılanları Faz 4'te tarayacağız.

### E2. Val split'i tesadüfe bırakılmış

`tile_and_label.py:22` `VAL_SCENE_COUNT=2` + `sorted(glob(...))` → val seti
**dosya adına göre sıralı ilk 2 sahne**. Plan Faz 3'te "val'de hem TAM hem KISMİ
kapsamalı sahne olsun" diyordu ama mekanizma bunu garanti etmiyor.

**Aksiyon (Faz 3):** Val sahneleri `config.py`'de **açık liste** olarak
tanımlanacak, indeksle değil:
```
VAL_SCENES = ["...20260504T053257...",   # TAM kapsama
              "...20260518T052345..."]   # KISMİ kapsama
```

### E3. SNAP float kaynağı duruyor — Faz 1'in girdisi değişiyor ⭐

`data/sentinel1/sentinel1_processed/*.data/` klasörleri **10 sahne için de mevcut**:

```
Sigma0_VV.img   float32, lineer sigma0, 50707×21278
Sigma0_VH.img   float32, lineer sigma0   ← şu an hiç kullanılmıyor
```

Bu, planı **daha iyi** hale getiriyor. Orijinal Faz 1 tasarımı `_normalized.tif`
(uint8) dosyalarını warp edecekti — yani zaten kuantalanmış veriyi ikinci kez
yeniden örnekleyecektik. Artık gerek yok:

```
ESKİ:  .img float → uint8 tif (derece) → warp → uint8 tif (UTM)
                    ↑ bilgi kaybı        ↑ ikinci kayıp

YENİ:  .img float → warp → float32 tif (UTM, dB)  ──┬─→ CFAR (float, kalibre)
                                                     └─→ uint8 render → YOLO
```

**Aksiyon (Faz 1):** `gdalwarp` girdisi `Sigma0_VV.img` olacak, `_normalized.tif`
değil. Normalizasyon (uint8 render) warp'tan **sonra** yapılacak.
Bu ayrıca Faz 4a'daki "CFAR'ı dB/sigma0 üzerinde çalıştır" maddesini
uygulanabilir kılıyor — aksi halde float veri elimizde olmayacaktı.

### E4. VH polarizasyonu hiç kullanılmamış — araştırma kalemi

`normalize_sar.py:25` sadece `*_VV.img` arıyor. Ama her sahnede `Sigma0_VH.img`
de var.

Çapraz polarizasyonda (VH) deniz yüzeyi geri saçılımı VV'ye göre çok daha zayıf,
gemiler ise çoklu yansıma sayesinde güçlü sinyal vermeye devam eder → **gemi/deniz
kontrastı genelde VH'de daha yüksektir.** Buna karşılık VH'nin mutlak SNR'ı düşük,
sakin denizde gürültü tabanına yaklaşabilir.

**Aksiyon (Faz 4a):** Kesin iddia yok — **ölçeceğiz.** Aynı sahnede VV, VH ve
VV/VH oranı için CFAR ROC eğrisi çıkarılacak, kazanan kullanılacak. Faz 1 zaten
her iki bandı da warp edecek şekilde kurulacak (ek maliyet ihmal edilebilir).

### E5. Küçük ama gerçek hatalar (fazlara dağıtıldı)

| Bulgu | Faz |
|---|---|
| `dashboard/app.py:21` — `FileResponse` dosya varlık kontrolü yapmıyor | Faz 7 |
| `train_yolo.py:18` — `device=0` sabit, GPU yoksa çöker | Faz 4b |
| `tile_and_label.py:19-23` — `TILE_SIZE`/`OVERLAP`/`BLANK_STD_THRESHOLD` config'ten import edilmiyor | Faz 0 |
| `compute_ship_obb.py` silinmiş, çıktısı referans alınıyor | Faz 0 *(zaten planda)* |

---

## 5. Parametre değişiklik tablosu

| Parametre | Şu an | Yeni | Gerekçe |
|---|---|---|---|
| CRS | EPSG:4326 | **EPSG:32632** | kare piksel, metrik ölçüm |
| Piksel boyutu | 5.69 × 10.00 m | **10 × 10 m** | 1.757× anizotropi giderilir |
| AOI | 3 farklı bbox | **tek: 10.50–11.30 / 55.00–55.60** | sistematik sahte dark vessel kaynağı |
| `MIN_SHIP_LENGTH_M` | (yok) | **30** | S1 GRDH ~20 m çözünürlük sınırı |
| AIS zaman hizalama | en yakın kayıt | **enterpolasyon + ölü hesap** | %90 dilim 112 s → 690 m hata |
| AIS max zaman farkı | 600 s | **300 s** | güvenilmez kayıtları at |
| `MATCH_DISTANCE_M` | 2000 | **300** | ort. eşleşme 1355 m → gerçek eşleşme değil |
| `CFAR_MIN_CLUSTER_SIZE` | 1 | **3** | tek piksel gürültü elenir |
| `CFAR_MAX_CLUSTER_SIZE` | 30 | **400** | 244 m gemi ≈ 180 px, şu an reddediliyor |
| CFAR girdisi | uint8 PNG | **dB / lineer sigma0** | radyometrik bilgi kaybı |
| `MIN_OVERLAP_RATIO` | 0.3 | **0.8** | kırpılmış OBB deformasyonu |
| Karo örtüşmesi | 128 px | 128 px + **global NMS** | çift sayım |
| val oranı | %44 | **%20** (2/10 sahne) | anormal split |
| val seçimi | sıralı ilk 2 (tesadüf) | **açık sahne listesi** | TAM+KISMİ kapsama garantisi (E2) |
| YOLO predict eşiği | örtük 0.25 (yazılı değil) | **açık, config'te** | gizli varsayılan (E1) |
| `DARK_VESSEL_MIN_CONF` | 0.05 (etkisiz) | **0.40** (kalibre edilecek) | ölü kod → gerçek karar eşiği (E1) |
| Warp girdisi | `_normalized.tif` (uint8) | **`Sigma0_*.img`** (float32) | çift kuantalama önlenir (E3) |
| Polarizasyon | sadece VV | **VV + VH ölçülüp seçilecek** | VH'de gemi/deniz kontrastı (E4) |

---

## 6. Yapmayacaklarımız (ve nedeni)

- **SNAP'e dönüp yeniden üretmek:** 10 sahne için saatler sürer. `gdalwarp`
  ikinci bir yeniden örnekleme getiriyor ama gemi tespiti için etkisi ihmal
  edilebilir. *(Faz 4'te benek filtresi araştırması bu kararı yeniden açabilir.)*
- **Her şeyi tek seferde refactor etmek:** Fazlar sırayla, her biri kendi
  doğrulama kapısıyla. Zincirleme hataların sebebi tam olarak buydu.
- **Veri toplamayı genişletmek:** Önce mevcut 10 sahneyi doğru işleyelim.
  AIS penceresini/sahne sayısını artırmak, hatalı hattı daha pahalı hale getirir.

---

## 7. Sıradaki adım

Faz 0'ın onayı bekleniyor. Onaylanırsa:
1. Eski çıktıları `_deprecated_20260801/`'e arşivle
2. `geoport/` paket iskeletini kur
3. `geoport/obb.py`'yi yaz ve mevcut çıktılarla birebir doğrula
4. `requirements.txt` + `.gitignore` + `config.py` tekilleştirmesi

Faz 0 tamamen geri alınabilir ve hiçbir algoritma mantığını değiştirmez —
güvenli başlangıç noktası.
