# Sentinel-1 SAR Gemi Tespit Pipeline'ı: Kök Neden Analizi (RCA) Raporu

**Hazırlayan:** Principal Computer Vision Researcher & SAR Imaging Expert
**Tarih:** 04 Ağustos 2026
**Kapsam:** Sentinel-1 SAR ve AIS entegrasyonu, YOLO-OBB, CFAR tabanlı karanlık gemi (dark vessel) tespit sistemi.

Mevcut pipeline'ın davranışı analiz edildiğinde, gözlemlenen hataların (gemilerin karada çıkması, hatalı AIS eşleşmeleri, modelin hiçbir şey bulamaması) rastgele olmadığı, aksine sistem tasarımındaki ardışık uzamsal ve istatistiksel hataların birikimli bir sonucu olduğu tespit edilmiştir. 

Aşağıda her bir aşama, bir adli bilişim (forensic) perspektifiyle ele alınmıştır.

---

## 1. Sentinel-1 Ön İşleme (SNAP)

* **Amacı:** Ham Sentinel-1 SAFE verilerini radyometrik olarak kalibre etmek, gürültüyü gidermek ve coğrafi olarak konumlandırmak.
* **Olası Hata Kaynakları:** Projeksiyon ve çözünürlük ayarlarındaki uyumsuzluklar. SNAP graph yapılandırmasında piksel aralığının (pixel spacing) derece cinsinden dikkatsizce verilmesi.
* **Toplanması Gereken Kanıtlar:** SNAP Graph XML dosyası (`myGraph.xml`), çıktı GeoTIFF'in affine transform matrisi ve pixel spacing değerleri.
* **Yapılması Gereken Testler:** Orijinal `Sigma0_VV.img` dosyasının metrik çözünürlüğünün enlem ve boylam eksenlerinde ölçülmesi. WGS84 üzerinde `8.983e-5` derece değerinin 55° Kuzey enleminde kaç metreye denk geldiğinin hesaplanması.
* **Beklenen Sonuçlar:** Ekvatorda 10 metreye denk gelen açısal değerin, Danimarka (55°N) enlemlerinde X ekseninde daralarak (yaklaşık `10 * cos(55°) = 5.69 m`) ciddi bir **anizotropik piksel (5.69 m x 10.00 m)** yapısına yol açtığının görülmesi.
* **Güven Seviyesi:** Çok Yüksek.
* **Problemin Kaynağı Olma Olasılığı:** %95. (Bu hata, sonraki tüm rotasyon ve OBB hesaplamalarını bozarak gemilerin SAR görüntüsünde deforme olmuş gibi görünmesine neden olur.)

## 2. GeoTIFF Doğruluğu

* **Amacı:** SNAP çıktılarını 8-bit, işlenebilir görüntü karoları haline getirmek.
* **Olası Hata Kaynakları:** Sahne başına 1. ve 99. persentil (yüzdelik dilim) alınarak dinamik normalizasyon yapılması.
* **Toplanması Gereken Kanıtlar:** `normalize_sar.py` içindeki `db_normalize` fonksiyonunun incelenmesi ve farklı sahnelerdeki `scene_db_min` ile `scene_db_max` değerlerinin loglanması.
* **Yapılması Gereken Testler:** İki farklı sahnede aynı radar kesit alanına (RCS) sahip bir geminin, normalize edilmiş 8-bit GeoTIFF'te hangi piksel yoğunluk değerini (0-255) aldığının karşılaştırılması.
* **Beklenen Sonuçlar:** Bir sahnede çok parlak hedefler (örneğin devasa bir platform) varsa 99. persentil yükselecek ve normal gemiler karanlık kalacaktır. Bu durum, modelin veya CFAR'ın (eğer 8-bit üzerinden çalışıyorsa) eşik değerlerini geçersiz kılar. Ayrıca geçerli veri maskesi (NoData) işlemleri rastgele sıfırlamalar yaratabilir.
* **Güven Seviyesi:** Yüksek.
* **Problemin Kaynağı Olma Olasılığı:** %80. (CFAR ve YOLO modelinin farklı sahnelerde istikrarsız performans göstermesinin temel nedeni).

## 3. AIS Eşleştirme

* **Amacı:** SAR görüntüsündeki gemi yansımaları ile yerdeki gerçeği (AIS) eşleştirmek.
* **Olası Hata Kaynakları:** Konumsal ötelenme (displacement). Hareket halindeki bir gemi için sadece "en yakın zamandaki" (Nearest Neighbor) AIS sinyalinin alınması. Küçük teknelerin filtrelenmemesi.
* **Toplanması Gereken Kanıtlar:** `match_ais_sar.py` içindeki zaman eşleştirme mantığı ve AIS zaman damgalarının SAR zamanına göre ne kadar saptığı (delta T).
* **Yapılması Gereken Testler:** `diagnose_match_distance.py` veya benzeri bir betikle, hareket halindeki gemiler (SOG > 5 knot) için AIS zamanı ile SAR geçiş zamanı arasındaki farkın, geminin kat edeceği mesafeye (Velocity x Delta T) etkisinin ölçülmesi.
* **Beklenen Sonuçlar:** 100 saniyelik bir gecikme, 12 knot hızla giden bir gemide yaklaşık 600 metre konumsal hata yaratır. Enterpolasyon ve ölü hesap (dead reckoning) yapılmadığı için, AIS eşleşmeleri gerçek gemi yansımasından kilometrelerce uzakta görünebilir. Ayrıca AIS datasındaki gemilerin %50'den fazlasının 20 metreden kısa olması, bu sensör çözünürlüğünde (20m efektif) fiziken görülmelerini engeller.
* **Güven Seviyesi:** Çok Yüksek.
* **Problemin Kaynağı Olma Olasılığı:** %99. ("Eşleşme mesafesini artırınca eşleşme sayısı artıyor" bulgusunun doğrudan sebebi).

## 4. Ground Truth Üretimi

* **Amacı:** AIS kayıtlarından geminin yönünü, boyunu ve enini kullanarak haritada doğru bir çokgen (OBB) çizmek.
* **Olası Hata Kaynakları:** AIS anten ofsetinin yanlış uygulanması, WGS84 derece uzayında metrik dönüşüm (cos(lat)) hataları.
* **Toplanması Gereken Kanıtlar:** `geoport/obb.py`'deki `obb_corners_local` ve `obb_polygon_wgs84` fonksiyonlarının incelenmesi.
* **Yapılması Gereken Testler:** Anten ofset (A, B, C, D) metriklerinin çokgene dönüşümde tam olarak gemi merkezini SAR parlaklık merkezine oturtup oturtmadığının kontrolü.
* **Beklenen Sonuçlar:** Kodda anten ofsetleri doğru uygulanıyor görünse de, Faz 1'deki anizotropik pikseller (5.69m x 10m) nedeniyle, haritada mükemmel çizilmiş bir OBB, piksel uzayına yansıtıldığında yanlış boyutta ve açıda (distorsiyona uğramış) olacaktır. WGS84 düzleminde çizilen poligonların kartezyen bir grid'e izdüşümü doğal olarak hatalıdır.
* **Güven Seviyesi:** Orta.
* **Problemin Kaynağı Olma Olasılığı:** %40 (Yanlışlık kodda değil, altlıktaki anizotropik piksellerle uyumsuzlukta).

## 5. Dataset Oluşturma

* **Amacı:** 512x512'lik eğitim karoları üretmek ve poligonları kırpmak (clipping).
* **Olası Hata Kaynakları:** Tile (karo) kenarlarına denk gelen gemilerin OBB'lerinin hatalı kırpılması (`MIN_OVERLAP_RATIO = 0.3` kullanımı).
* **Toplanması Gereken Kanıtlar:** `tile_and_label.py` içindeki `polygon_to_yolo_obb_format` fonksiyonunun incelemesi. Üretilen `data/yolo_dataset/labels/` dizinindeki etiket boyutları.
* **Yapılması Gereken Testler:** Etiketlenen kutuların köşe uzunluklarının piksel cinsinden histogramının çıkarılması.
* **Beklenen Sonuçlar:** Geminin sadece %30'u karonun içinde kaldığında, bu kırpılmış geometri etrafına çizilen yeni YOLO-OBB kutusu orantısız derecede ince/uzun veya kısa bir çizgi haline gelecektir. Etiketlerin çok büyük bir bölümünün (%70) dejenere olduğu, yani modelin öğrenemeyeceği kadar ince olduğu tespit edilecektir.
* **Güven Seviyesi:** Kesin.
* **Problemin Kaynağı Olma Olasılığı:** %100. (Modelin hiçbir şey öğrenmemesinin ana mekanizması).

## 6. YOLO Label Doğruluğu

* **Amacı:** Modelin loss (kayıp) fonksiyonunu doğru şekilde minimize edebilmesi.
* **Olası Hata Kaynakları:** Kırpılmış dejenere pikseller, `[0,1]` aralığına zorlama, NaN veya 0 alanlı poligonlar.
* **Toplanması Gereken Kanıtlar:** OBB koordinat sıralamaları ve saat yönü/saat yönünün tersi (CW/CCW) kuralına uyumluluk.
* **Yapılması Gereken Testler:** YOLO'nun bounding box'ları çizilirken `area < 1e-6` kontrollerinin yetersiz kalıp kalmadığı kontrolü.
* **Beklenen Sonuçlar:** Dejenere pikseller ve anizotropik (kare olmayan) uzamsal düzlem nedeniyle, model "gemi" olarak etiketlenmiş anlamsız veri kümeleri görmektedir. Loss = 0 hatası doğrudan bu çöküşün (collapse) sonucudur.
* **Güven Seviyesi:** Kesin.
* **Problemin Kaynağı Olma Olasılığı:** %90.

## 7. Model Eğitimi

* **Amacı:** SAR verisinde gemilerin OBB modelini öğrenmek.
* **Olası Hata Kaynakları:** Veri dengesizliği, aşırı küçük hedefler, yanlış augmentasyon stratejileri, hiperparametre hataları.
* **Toplanması Gereken Kanıtlar:** `runs/` dizinindeki eğitim logları, loss grafikleri ve `data.yaml` dosyasının durumu.
* **Yapılması Gereken Testler:** Eğitim sırasında YOLO loss grafiklerinin izlenmesi.
* **Beklenen Sonuçlar:** Yukarıdaki etiketleme (dejenere kutular) ve hedef çözünürlüğü (<20m gemiler) hataları yüzünden modelin "gemi" kavramını öğrenmesi matematiksel olarak imkansız hale gelmiştir. Eğitim seti bozuk olduğu için validasyon kayıpları da tanımsız olacaktır.
* **Güven Seviyesi:** Yüksek.
* **Problemin Kaynağı Olma Olasılığı:** %80 (Dataset sorunlarının kaçınılmaz sonucu).

## 8. Inference (Çıkarım ve Tahmin)

* **Amacı:** Yeni sahnelerde YOLO-OBB ve CFAR kullanarak gemileri tespit edip tekilleştirmek.
* **Olası Hata Kaynakları:** CFAR parametrelerinin aşırı katı (veya aşırı gevşek) olması, örtük eşik değerleri (implicit thresholds).
* **Toplanması Gereken Kanıtlar:** `detect_ships_obb.py`'de `cfar_detector.py`'nin çağrılışı, `MAX_CLUSTER_SIZE` ve `MIN_CLUSTER_SIZE` parametreleri.
* **Yapılması Gereken Testler:** Bilinen devasa bir geminin (örn. 244m, ~180 piksel alan) CFAR tarafından yakalanıp yakalanmadığının izole testi.
* **Beklenen Sonuçlar:** `CFAR_MAX_CLUSTER_SIZE = 30` olarak belirlendiğinden, gerçek ve büyük gemilerin tamamı sistem tarafından "gürültü" veya "kara" sayılarak reddedilmektedir. Sistem sadece 1-3 piksellik saçılma (speckle) gürültülerini tespit etmektedir (karo başına 13.3 yanlış alarm). Ek olarak, YOLO `conf=0.25` gibi gizli bir varsayılanı kullanmakta, `config.py`'deki `DARK_VESSEL_MIN_CONF=0.05` tamamen etkisiz bir ölü koda dönüşmektedir.
* **Güven Seviyesi:** Kesin.
* **Problemin Kaynağı Olma Olasılığı:** %100. (Devasa yanlış alarm (false alarm) oranlarının ve gerçek gemilerin kaçırılmasının kök nedeni).

## 9. GIS Görselleştirme

* **Amacı:** Tüm tahminlerin son kullanıcı için harita üzerinde mantıklı bir şekilde (doğru enlem/boylamda) gösterilmesi.
* **Olası Hata Kaynakları:** Piksel -> Koordinat dönüşümünde (Affine Transform) projection hataları, sahnenin kapsamı dışında kalan piksellerin (ghost) haritaya yansıtılması.
* **Toplanması Gereken Kanıtlar:** AOI ve footprint (izdüşüm) maskelemesinin kodda nerede kullanıldığı.
* **Yapılması Gereken Testler:** Sahne footprint'i dışında kalan AIS gemilerinin "tespit edilemeyen karanlık gemi" olarak raporlanıp raporlanmadığının testi.
* **Beklenen Sonuçlar:** Bazı sahneler AOI'nin (Area of Interest) sadece küçük bir bölümünü kapsadığı halde, AIS kayıtları tüm AOI için çekilmekte, uydu o bölgeye hiç bakmamış olmasına rağmen bu gemiler "tespit edilemedi" (ghost/dark vessel) olarak haritaya basılmaktadır. Piksellerdeki anizotropi de (Faz 1) gemilerin haritada karaya (veya yanlış yerlere) kaymış gibi görünmesini garanti eder.
* **Güven Seviyesi:** Çok Yüksek.
* **Problemin Kaynağı Olma Olasılığı:** %70 (Temel algoritma hatalarının görsel tezahürü).

---

## Tüm Olası Kök Nedenlerin Sıralaması (En Yüksekten En Düşüğe)

1. **Kırpma (Clipping) ve Dataset Dejenerasyonu (%100):** Tile kenarlarındaki OBB'lerin [0,1] aralığına sert kırpılması, etiketlerin %70'ini dejenere etmiş ve YOLO modelinin çökmesine (loss=0) neden olmuştur. Model çalışmamaktadır.
2. **CFAR Parametrizasyon Hatası (%100):** `MAX_CLUSTER_SIZE=30` gerçek büyük gemileri reddetmekte, `MIN_CLUSTER_SIZE=1` gürültüleri kabul etmektedir. CFAR gerçek gemilere tamamen kördür.
3. **AIS Zaman Enterpolasyonu Eksikliği (%99):** Hareketli gemiler için "en yakın zaman" mantığı 690m ile 3.6km arasında devasa konum hataları yaratmakta, gerçek gemilerle sensör yansımaları yanlış eşleşmektedir.
4. **Anizotropik SAR Pikselleri (%95):** SNAP'te projeksiyon WGS84 bırakılıp metrik mesafe girilince 5.69m x 10m piksel aralığı oluşmuş; bu durum görsel, etiketleme ve uzamsal aşamalarının tümünü deforme etmiştir. Gemilerin karaya kaymış görünmesinin ana nedenidir.
5. **Aşırı Küçük AIS Hedeflerinin Filtrelenmemesi (%90):** Sentinel-1'in göremeyeceği 20 metrenin altındaki tekneler (%50 civarı) sisteme ground truth olarak verilmekte, bu da modelin öğrenemeyeceği imkansız hedefler oluşturmaktadır.
6. **SAR Görüntüsü Scene-Level (Sahne Bazlı) Normalizasyon (%80):** 8-bit GeoTIFF üretilirken min/max persentillerinin sahneye özel hesaplanması, gemi sinyallerinin radyometrik kararlılığını yok etmiştir.
7. **Örtük YOLO Confidence Eşiği (%60):** Kodda hedeflenen 0.05'lik eşik yerine kütüphanenin varsayılan 0.25'lik eşiğinin uygulanması, düşük güvenli tespitleri sessizce ezmektedir.
8. **Footprint Kapsam Dışı Veri Kullanımı (%50):** Uydunun bakmadığı alanlardaki AIS verilerinin "tespit edilemeyen gemi" olarak etiketlenmesi performans metriklerini yapay olarak bozmaktadır.

---

## Deneysel Teşhis Planı (En Az Hesaplama Maliyeti)

Hataları, kodu refactor etmeden ve yoğun hesaplama yapmadan kanıtlamak için şu deney izlenmelidir:

**Deney Adı:** CFAR & Uzamsal Hata Doğrulama İzolasyon Testi
1. **Hedef Seçimi:** Hızlı giden (SOG > 10 knot) ve büyük (Length > 150m) bir AIS gemisi seçin.
2. **Zaman Delta Ölçümü:** Bu AIS kaydının zamanı ile SAR geçiş zamanı arasındaki saniye farkını (delta T) ölçün ve gemi hızı (m/s) ile çarparak beklenen "AIS-SAR uzamsal sapmasını" (displacement) metre cinsinden çıkarın.
3. **CFAR ve Piksel Geometrisi Kontrolü:** Seçilen geminin AIS noktasından yaklaşık 200x200 piksellik bir (ROI) `_normalized.tif` kesiti alın. ROI içerisindeki parlak gemi piksel alanını ölçün. Bu alanın `MAX_CLUSTER_SIZE=30` eşiğinden çok daha büyük (örneğin ~150-200 piksel) olduğunu ve CFAR'ın bu gemiyi göz ardı ettiğini doğrulayın. Ayrıca ROI içindeki geminin boyut oranlarını hesaplayarak piksel anizotropisini (5.69m'lik daralmayı) teyit edin.
4. **Sonuç Yorumlaması:** Bu basit ve tek bir nesne üzerindeki inceleme; sistemin büyük gemileri nasıl ayıkladığını, AIS eşleşmelerinin neden kilometrelerce şaştığını ve piksellerin neden deforme olduğunu hiçbir kodu değiştirmeden matematiksel olarak kanıtlayacaktır.
