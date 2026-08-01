# GeoPort AI

**Storebælt (Danimarka) boğazında Sentinel-1 SAR ve AIS verilerini birleştirerek
deniz trafiği analizi ve karanlık gemi (dark vessel) tespiti.**

> **Durum: duraklatıldı (2026-08-02).** SAR hattında kök neden analizi tamamlandı
> ve nedeni bulundu. Proje, AIS tabanlı analiz eksenine kaydırılıyor —
> gerekçe ve yol haritası: [`PLAN_V2.md`](PLAN_V2.md)

---

## Bu depo neyi anlatıyor

Kurulmuş bir hat vardı: Sentinel-1 SAR sahnelerinden YOLO-OBB ve CFAR ile gemi
tespiti, AIS ile eşleştirme, eşleşmeyenleri "karanlık gemi" olarak raporlama.

Hat çalışıyordu. **Ürettiği sayılar doğru değildi.**

Bu depo, o sayıların neden yanlış olduğunun bulunma sürecidir. Sonuç tek bir
yapılandırma satırında bitiyor — ama oraya varmak sekiz ayrı ölçüm gerektirdi.

---

## Kök neden

```xml
<!-- data/sentinel1/myGraph.xml — SNAP Terrain-Correction -->
<nodataValueAtSea>true</nodataValueAtSea>
```

SNAP'in Range-Doppler Terrain Correction adımı, yükseklik modelini (SRTM)
kullanarak **deniz piksellerini "veri yok" olarak siler**. Bu SNAP'in varsayılan
davranışıdır ve kara uygulamaları için mantıklıdır.

Gemi tespiti projesinde ise **aranan her şeyi silmek** anlamına gelir.

![Ayak izi](reports/diagnostics/footprint_20260504.png)

*Beyaz = geçerli veri, siyah = veri yok, kırmızı kutu = ilgi alanı (AOI).
Beyaz bölgeler Danimarka'nın kara parçalarıdır — Fyn, Sjælland, Jylland.
Denizin tamamı silinmiş.*

### Hata neden fark edilmedi

`02_preprocessing/normalize_sar.py` maskeyi aşağı taşıyamadı. Kaynak ENVI `.img`
dosyasında nodata etiketi olmadığı için `src.read_masks()` her pikseli "geçerli"
döndürdü, dolayısıyla nodata sıfırlama satırı hiç çalışmadı:

```python
src_mask = src.read_masks(1, window=window)   # her zaman 255 döndü
normalized[src_mask == 0] = 0                 # hiç tetiklenmedi
```

Sonuç: uydunun hiç görüntülemediği deniz, çıktıda `0` (veri yok) yerine `1`
(çok karanlık su) oldu. Hattaki hiçbir adım denizin eksik olduğunu anlayamadı.

---

## Ölçümler

Her iddia koddan bağımsız olarak ölçüldü. Scriptler [`scripts/`](scripts/) altında.

| Ölçüm | Sonuç |
|---|---|
| AOI'nin gerçek veriyle kapsanması (10 sahne) | **hiçbiri %40'ı geçmiyor**, biri %0 |
| Hiç görüntülenmiş AIS gemisi | **460 / 1308 = %35** |
| Görüntülenmiş gemilerde YOLO'nun <300 m tespiti | **%0** (100 m+ gemilerde bile) |
| Eşleşen gemilerin AIS'e ortalama uzaklığı | 1355 m |

Son satır tek başına bir uyarıydı: 10 m çözünürlüklü bir sensörde 1,3 km'lik
"eşleşme" eşleşme değildir.

### Belirti ile neden ayrımı

Kök neden bulunmadan önce ölçülen sorunların bir kısmı gerçek, bir kısmı
bu tek nedenin aşağı akış belirtisiydi. Ayrımı yapmak önemliydi:

| Bulgu | Sınıf |
|---|---|
| CFAR karo başına 13,3 yanlış alarm | belirti — yalnızca kara üzerinde çalışıyordu |
| Eşleşme mesafesi 1355 m | belirti — en yakın "tespit" hep en yakın kıyıydı |
| %5 recall | belirti — denizde veri yoktu |
| Etiketlerin %70'i dejenere (kısa kenar < 1,5 px) | **bağımsız** — AIS'in %52'si 20 m altı gemi |
| `CFAR_MAX_CLUSTER_SIZE = 30 px` | **bağımsız** — 244 m'lik gemi ~180 px küme üretir, filtre onu reddediyordu |
| Anizotropik piksel (5,69 m × 10,00 m) | **bağımsız** — SNAP 10 m'yi dereceye çevirirken enlem düzeltmesi yapmamış |
| Üretim modeli harici veri setiyle eğitilmiş | **bağımsız** — `mAP50 = 0.888` bu projenin verisine ait değil |
| Tüm YOLO-OBB eğitimlerinde `loss = 0`, `mAP = 0` | **bağımsız** — dataloader hiç etiket görmedi |

---

## Yapılan iş

### Faz 0 — zemin sabitleme *(tamamlandı)*

Algoritma mantığına dokunmadan tekrarlanabilirliği geri kazandırma.

- **`config.py` tek parametre kaynağı oldu.** CFAR parametreleri daha önce hem
  `config.py` hem `cfar_detector.py` içinde **farklı değerlerle** tanımlıydı —
  "bir hatayı düzeltince başkası çıkıyor" döngüsünün teknik sebebi buydu.
- **`geoport/obb.py`** — silinmiş `compute_ship_obb.py` tersine mühendislikle
  çözülüp yeniden yazıldı. Doğrulama: **1308/1308 poligon, Hausdorff sapması
  0,0000 m** ([`scripts/verify_obb_reproduction.py`](scripts/verify_obb_reproduction.py)).
- **Güvenilmez çıktılar arşivlendi**, silinmedi — teşhis kanıtı olarak duruyorlar.
- **9 scripte açık bariyer kondu.** Sebep: `config`'i import etmeyen scriptler,
  config'ten isim kaldırılınca durmuyor, sessizce eski sabitlerle çalışmaya
  devam ediyordu. Her bariyer neden kapatıldığını ve hangi fazda neyle
  değişeceğini söylüyor.
- **Git hijyeni:** 145 takipli binary → 0.

Ayrıntı: [`reports/FAZ_0_RAPOR.md`](reports/FAZ_0_RAPOR.md)

### Teşhis araçları

| Script | Ne yapar |
|---|---|
| [`diagnose_match_distance.py`](scripts/diagnose_match_distance.py) | AIS → en yakın SAR tespiti mesafe dağılımı (eşik uygulamadan) |
| [`diagnose_ship_visibility.py`](scripts/diagnose_ship_visibility.py) | Gemi görüntüde var mı, ofset sistematik mi |
| [`dump_ship_chips.py`](scripts/dump_ship_chips.py) | En büyük gemilerin görüntü kesitleri — gözle doğrulama |
| [`validate_ais_features.py`](scripts/validate_ais_features.py) | AIS veri setinin hangi analizleri taşıdığı |
| [`verify_obb_reproduction.py`](scripts/verify_obb_reproduction.py) | Faz 0 doğrulama kapısı |

---

## Neden burada duruldu

SAR hattının düzeltilmesi teknik olarak **bir XML satırı**: `nodataValueAtSea`
değerini `false` yapıp SNAP'i yeniden çalıştırmak. Ham `.SAFE.zip` dosyaları
duruyor, yeniden indirme gerekmiyor.

Ama sonrasında belirsizlik var: deniz verisi geldiğinde modelin gemileri bulup
bulamayacağı test edilmedi — **edilemedi**, çünkü bakılacak deniz yoktu.

Buna karşılık elde **bugün çalışan** bir veri kaynağı var:

| | |
|---|---|
| AIS kaydı | 17.142.606 |
| Benzersiz gemi | 3.290 (1.424 tanesi ≥30 m) |
| Süre | 45 gün (2026-05-01 → 06-15) |
| Çözünürlük | **saniyelik** |

Bu yüzden proje AIS eksenine kaydırıldı. SAR **iptal edilmedi, ertelendi** —
`PLAN_V2.md` içinde P7 olarak duruyor ve `geoport/obb.py` onun için hazır.

---

## Sonraki adım

[`PLAN_V2.md`](PLAN_V2.md) — tek bir yörünge motoru üzerine kurulu dört analiz
katmanı: karşılaşma riski (CPA/TCPA), AIS boşluk/anomali tespiti,
bekleme/tıkanıklık, karbon salımı.

Fizibilite ölçüldü, iki metodolojik tuzak tespit edildi ve plana yazıldı:

- **"İmkânsız hız" spoofing değil, alıcı gürültüsü.** 3 günde 262 geminin
  262'sinde çıkıyor — yani sinyal değil, taban gürültü.
- **Karşılaşma sayıları rıhtımdaki gemilerle şişiyor.** 62.801 yakınlaşma anı,
  ama yalnızca 221 benzersiz çift.

---

## Devam rehberi — bu hatalara bir daha düşmemek için

Aşağıdakilerin hepsi bu projede **gerçekten yaşandı ve ölçüldü**. Genel tavsiye değil.

### Sıfırdan doğru sıra

Bu projenin en pahalı dersi şuydu: **hatalar bağımsız değildi.** Zincirin ortasındaki
halkalar düzeltildi, çünkü baştaki halka görünmüyordu. Doğru sıra şu — her adımın
kapısı geçilmeden sonrakine geçilmez:

| # | Adım | Geçmeden önce doğrula |
|---|---|---|
| 0 | **Veriye bak.** Kod yazmadan önce ham görüntüyü aç, birkaç kareyi gözle incele | Deniz var mı? Kara var mı? Beklediğin şey görünüyor mu? |
| 1 | **Geometri.** Projeksiyon, piksel boyutu, AOI | `transform.a == transform.e` (kare piksel)? AOI tek yerde mi tanımlı? |
| 2 | **Kapsama.** Her sahnenin geçerli veri ayak izi | AOI'nin yüzde kaçı gerçekten görüntülenmiş? |
| 3 | **Ground truth.** Zaman hizalama, boy filtresi, ayak izi kırpması | Etiketler sensörün çözebileceği boyutta mı? |
| 4 | **Veri seti.** Karolama, etiket üretimi | Dejenere etiket oranı %5'in altında mı? |
| 5 | **Dedektör.** CFAR kalibrasyonu, model eğitimi | Loss gerçekten düşüyor mu? Yanlış alarm oranı beklenen mertebede mi? |
| 6 | **Füzyon.** Karo→sahne, global tekilleştirme | Aynı gemi bir kez mi sayılıyor? |
| 7 | **Eşleştirme.** Gating'li atama, dürüst eşik | Ortalama eşleşme mesafesi sensör çözünürlüğüyle uyumlu mu? |

**Adım 0 atlanırsa geri kalan her şey boşa gider.** Bu projede tam olarak bu oldu:
altı adım kuruldu, sonra deniz olmadığı anlaşıldı.

### Tuzak kataloğu

#### Uzaktan algılama / SAR

| Tuzak | Nasıl fark edilir | Çözüm |
|---|---|---|
| **SNAP denizi siliyor** (`nodataValueAtSea=true`) | Ayak izi görselinde sadece kara beyaz çıkar | Ayarı `false` yap. Kontrol: açık denizde `sigma0 > 0` mı? |
| **ENVI nodata taşınmıyor** | `read_masks()` her zaman 255 döner, maske hiç tetiklenmez | ENVI/`.img` okurken maskeye güvenme, **doğrudan `data == 0` kontrolü** yap |
| **Anizotropik piksel** | SNAP `pixelSpacingInDegree` üretmiş; enlem düzeltmesi yok | Coğrafi CRS yerine **metrik projeksiyon** (burada UTM 32N). Kontrol: `abs(transform.a) == abs(transform.e)` |
| **Hedef sensör çözünürlüğünün altında** | Etiketlerin kısa kenarı 1-2 piksel çıkar | Fiziksel alt sınır belirle. S1 GRDH ~20 m → **≥30 m gemi**. Ölçüldü: filtre olmadan etiketlerin %70'i dejenere |
| **Boyut filtresi ters çalışıyor** | Büyük hedefler hiç tespit edilmiyor | Eşiği **fizikten türet**: 244 m × 42 m gemi @10 m ≈ 180 piksel. `MAX=30` onu reddediyordu |
| **Sahne bbox'ı ≠ sahne kapsamı** | S1 sahnesi paralelkenardır, bbox dikdörtgen | Her sahne için **geçerli veri footprint'i** çıkar. Kapsam dışı ground truth "kaçırıldı" sayılmaz |

#### Model eğitimi

| Tuzak | Nasıl fark edilir | Çözüm |
|---|---|---|
| **Model başka veri setiyle eğitilmiş** | `runs/*/args.yaml` içindeki `data:` yolu projenin verisini göstermiyor | Üretim modelinin `args.yaml`'ını **her zaman** kontrol et. `mAP=0.888` başka bir veri setine aitse hiçbir şey ifade etmez |
| **Eğitim hiç öğrenmemiş** | `results.csv`'de tüm loss'lar tam **0** | Eğitim sonrası otomatik kontrol: `epoch 1` sonrası `loss > 0` değilse **durdur ve hata ver**. Sessizce 50 epoch koşturma |
| **Gizli varsayılan eşik** | Kodun hiçbir yerinde yazmayan bir değer kararları belirliyor | Ultralytics `predict()` varsayılan `conf=0.25` uygular. **Açıkça** ver: `predict(conf=config.YOLO_PREDICT_CONF)`. Ölçüldü: `DARK_VESSEL_MIN_CONF=0.05` tamamen ölü koddu |
| **Etiketsiz bölge negatif sanılıyor** | AOI dışı karolarda gerçek gemiler "arka plan" olarak etiketleniyor | Sadece ground truth kapsamındaki alanı karola |

#### Eşleştirme ve füzyon

| Tuzak | Nasıl fark edilir | Çözüm |
|---|---|---|
| **Eşik gerçek eşleşme uyduruyor** | Ortalama eşleşme mesafesi sensör çözünürlüğünün 100 katı | 10 m sensörde 1355 m "eşleşme" değildir. Eşiği **veriden savun**: zaman enterpolasyonu yapıldıysa 300 m savunulabilir, yapılmadıysa değil |
| **Karo örtüşmesi çift sayım** | Aynı lon/lat iki farklı karodan iki kayıt | Karo koordinatını **sahne koordinatına** taşı, sonra global NMS uygula |
| **Gating'siz Hungarian** | Doğru çiftler yanlış eşleşmelere kilitleniyor | Eşik üstü maliyetlere `BIG_M` ata ya da dummy sütun kullan |
| **AIS zaman kayması** | Medyan iyi görünür, kuyruk öldürür | Ölçüldü: medyan 25 s ama %10'luk dilim 112 s = 12 knot'ta **690 m**. Kuşatan iki kayıt arasında **enterpolasyon** yap, tek kayda güvenme |

#### AIS analizi *(P1–P5 için geçerli)*

| Tuzak | Nasıl fark edilir | Çözüm |
|---|---|---|
| **Alıcı gürültüsü spoofing sanılıyor** | "İmkânsız hız" neredeyse **her** gemide çıkıyor | Ölçüldü: 3 günde 262 geminin 262'sinde. Sebep: aynı saniyede farklı istasyonlardan ~50 m fark → 97 knot. Anomali saymadan önce **gürültü modelini kur** |
| **Duran gemiler karşılaşma sayısını şişiriyor** | Yakınlaşma "anı" çok, benzersiz çift az | Ölçüldü: 62.801 an ama 221 çift → rıhtımda yan yana duranlar. CPA analizinde **sadece seyir halindekileri** al |
| **Sabit nesneler gemi sanılıyor** | Tek MMSI'de binlerce kayıt, hiç hareket yok | Ölçüldü: bir MMSI 3 günde 27.011 kayıt, sıfır hareket → şamandıra/platform. Ayrı sınıfa al |
| **Rıhtım "bekleme" sayılıyor** | Bekleme süreleri absürt uzun çıkar | `Moored` bayrağı + kıyıya mesafe ile rıhtım/demirleme ayrımı yap |

#### Yazılım mimarisi

| Tuzak | Nasıl fark edilir | Çözüm |
|---|---|---|
| **Aynı sabit birden çok dosyada** | Bir düzeltme her yere yansımıyor | Bu projede CFAR parametreleri iki dosyada **farklı değerlerle** vardı. `config.py` tek kaynak; başka yerde sabit tanımlama |
| **Config'i import etmeyen script** | Config değişir, script eski sabitlerle sessizce çalışmaya devam eder | Her fazda `scripts/` altındaki denetimi çalıştır: hangi dosya `config` kullanıyor, hangi isim eksik |
| **Doğrulama scripti boşuna geçiyor** | Girdi yokken `exit 0` veriyor | "Dosya yoksa geç" **yanlış**. Girdi eksikse **başarısız ol** |
| **Import sırasında yan etki** | `import config` klasör yaratıyor | Yan etkiyi açık fonksiyona taşı (`ensure_dirs()`) |
| **Bilinmeyen scripti çalıştırarak test etmek** | Test, veri üretir veya ağdan indirir | Bu seansta yaşandı: `--help` sanıp çalıştırılan script 238 dosya üretti, bir diğeri 248 MB indirmeye başladı. **Önce statik oku**, sonra çalıştır |

### Her adımda sorulacak üç soru

1. **Bu sayı mantıklı mı?** Beklenen mertebeyi önceden hesapla, sonra ölç.
   PFA=1e-7'de 512×512 karoda beklenen yanlış alarm 0,026'dır. 13,3 görürsen
   parametreyi değil, **varsayımı** sorgula.
2. **Bu belirti mi, sebep mi?** Bir bulgu düzeltilmeden önce sor: bunun
   yukarısında başka bir şey olabilir mi? Bu projede CFAR yanlış alarmları,
   eşleşme mesafesi ve düşük recall — üçü de gerçekti ama üçü de **tek bir
   nedenin belirtisiydi**.
3. **Bunu gözle doğrulayabilir miyim?** İstatistik yanıltır, görüntü yanıltmaz.
   Ayak izi görselini çizmek, sekiz sayısal ölçümün bulamadığını tek bakışta buldu.

### Bir daha yapsam neyi farklı yapardım

- **İlk gün ham veriden bir kesit çizerdim.** Kod yazmadan önce. 10 dakikalık iş,
  haftalarca yanlış yönde inşayı önlerdi.
- **Her ara çıktıya bir "akıl sağlığı" kontrolü koyardım.** Normalizasyondan sonra:
  "geçerli piksel oranı ne?" Karolamadan sonra: "kaç karoda etiket var?"
  Eğitimden sonra: "loss düştü mü?" Üçü de yapılsaydı sorun ilk haftada çıkardı.
- **Parametreleri fizikten türetirdim, deneyerek değil.** `MAX_CLUSTER_SIZE=30`
  muhtemelen deneme yanılmayla bulunmuştu. En büyük geminin kaç piksel ettiğini
  hesaplamak bunu baştan engellerdi.
- **Metrik gördüğüm her yerde "hangi veri üzerinde?" diye sorardım.**
  `mAP=0.888` gerçekti — ama başka bir veri setinde.

## Depo yapısı

```
config.py                 tek parametre kaynağı
geoport/                  ortak kütüphane
  obb.py                  AIS kaydı → yönlü sınırlayıcı kutu
01_data_collection/       veri indirme (AIS, Sentinel-1, kara maskesi)
02_preprocessing/         normalizasyon, karolama
03_training/              YOLO eğitimi
04_inference/             CFAR + YOLO tespit
05_analysis/              AIS eşleştirme, karanlık gemi motoru
dashboard/                FastAPI + harita arayüzü
scripts/                  teşhis ve doğrulama araçları
reports/                  faz raporları ve ölçüm çıktıları
TECHNICAL_PLAN.md         SAR hattı planı (P7'ye ertelendi)
PLAN_V2.md                AIS ekseni planı (aktif)
```

`01_`–`05_` altındaki scriptlerin çoğu şu an **bilinçli olarak bariyerli** —
eski, doğrulanmamış sonuçların kazara yeniden üretilmesini engellemek için.
Her biri çalıştırıldığında neden kapatıldığını açıklar.

---

## Çalışma ilkeleri

Bu projede işe yarayan ve devam ettirilen dört ilke:

1. **Önce ölç, sonra inşa et.** Hattı haftalarca yeniden inşa etmekten bu ilke
   kurtardı — düzeltilmiş bir hattı boş denizin üzerinde çalıştıracaktık.
2. **Tek parametre kaynağı.** `config.py` dışında sabit tanımlanmaz.
3. **Her fazın sonunda ölçülebilir doğrulama kapısı.** Kapı geçilmeden ilerlenmez.
4. **Belirsizliği gizleme.** Tahmin olan şey tahmin diye sunulur.

---

## Kurulum

```bash
python -m venv venv
venv/Scripts/activate          # Linux/macOS: source venv/bin/activate
pip install -r requirements.txt
```

GPU'lu PyTorch (SAR modülü için):

```bash
pip install torch==2.5.1 torchvision==0.20.1 \
    --index-url https://download.pytorch.org/whl/cu121
```

Veri (`data/`), model ağırlıkları (`runs/`, `*.pt`) ve arşiv depoya dahil değildir.
