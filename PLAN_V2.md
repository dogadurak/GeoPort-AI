# GeoPort AI v2 — Storebælt Deniz Trafiği Zekâsı

> Tarih: 2026-08-02 · Amaç: **portföy / iş başvurusu**
> Bu doküman `TECHNICAL_PLAN.md`'nin yerini alır. SAR hattı iptal değil, **ertelendi** (P7).

---

## 0. Neden yön değişti

Önceki hat, Sentinel-1 SAR üzerinde karanlık gemi tespiti yapıyordu. Kök neden
analizi tek bir satırda bitti:

```xml
<nodataValueAtSea>true</nodataValueAtSea>   <!-- SNAP Terrain-Correction -->
```

SNAP'in varsayılan ayarı **denizi siliyor**. 10 sahnenin tamamında okyanus
`sigma0 = 0` yapılmıştı; AIS gemilerinin yalnızca **%35'i** hiç görüntülenmişti.
YOLO ve CFAR hiçbir zaman gerçek deniz verisi görmedi — başarısız oldukları
söylenemez, **test edilmediler**.

Düzeltmesi bir XML satırı, ama SNAP yeniden işleme birkaç saat sürüyor ve
sonrasında model eğitimi belirsiz. Portföy hedefi için **bugün çalışan** bir
veri kaynağına geçiliyor: 17 milyon kayıtlık AIS veri seti.

SAR modülü P7 olarak açık kalıyor; hazır olduğunda takılır.

---

## 1. Ürün tanımı

**Storebælt boğazında 45 günlük gemi trafiğinin risk, anomali ve verimlilik analizi.**

Storebælt'i özel kılan: feribotlar transit trafiği **dik keser**. Bu, düz bir
koridorda görülmeyen gerçek bir çatışma geometrisidir.

| | |
|---|---|
| Kayıt | 17.142.606 |
| Gemi | 3.290 benzersiz MMSI (1.424 tanesi ≥30 m) |
| Süre | 45 gün (2026-05-01 → 06-15) |
| Çözünürlük | **saniyelik** |

Saniyelik çözünürlük ayırt edici: çoğu AIS çalışması dakikalık/agrege veri
kullanır ve manevra ölçeğindeki olayları göremez.

---

## 2. Mimari — tek çekirdek, dört okuma

Dört özellik ayrı proje değil; **tek bir yörünge motorunun** dört çıktısı.

```
        ham AIS (17M kayıt)
                │
      ┌─────────▼──────────┐
      │  YÖRÜNGE MOTORU    │   geoport/ais/
      │  · alıcı gürültüsü temizleme
      │  · boşluk etiketleme
      │  · sabit adımlı yeniden örnekleme
      │  · durum sınıflama (seyir/duruş/rıhtım)
      └─────────┬──────────┘
                │
    ┌───────┬───┴────┬─────────┬──────────┐
    ▼       ▼        ▼         ▼          ▼
  boşluk  çiftler  duruş    hız+tip   (P7: SAR)
    │       │        │         │          │
   ANOMALİ  CPA/    BEKLEME  KARBON   KARANLIK
   (P3)    TCPA     (P4)     (P5)      GEMİ
           (P2)                         (P7)
                     │
              ┌──────▼──────┐
              │  DASHBOARD  │  (P6) 3B + zaman
              └─────────────┘
```

Faz 0'da kurulan altyapı **aynen taşınıyor**: `config.py` tek kaynak ilkesi,
`geoport/` paketi, `geoport/obb.py` (P7'de lazım), git hijyeni, bariyerler.

---

## 3. Fazlar

### P1 — Yörünge motoru ⭐ *diğer her şeyin temeli*

Fizibilite ölçümü iki tuzak gösterdi; ikisi de burada çözülür.

**🔴 Tuzak 1: "İmkânsız hız" alıcı gürültüsüdür, spoofing değil.**
Ham veride 3 günde 262 geminin 262'sinde >40 kn sıçrama çıkıyor — yani
neredeyse her gemide. Sebep: aynı saniyede birden çok baz istasyonundan gelen
kayıtlar arasında ~50 m konum farkı → 97 knot. Bu bir anomali değil, ölçüm
gürültüsü. **Filtrelenmezse P3 tamamen yanlış sonuç üretir.**

**🔴 Tuzak 2: Duran gemiler karşılaşma sayısını şişiriyor.**
3 günde 62.801 "yakınlaşma anı" ama sadece 221 benzersiz çift → aynı gemiler
saatlerce yan yana duruyor (rıhtım). **P2 sadece seyir halindeki gemileri almalı.**

Yapılacaklar:
1. **Tekilleştirme:** aynı MMSI + aynı saniye → tek kayıt (konum medyanı).
2. **Gürültü filtresi:** ardışık kayıtlar arası hız, geminin fiziksel üst
   sınırıyla karşılaştırılır (tip ve boya göre; konteyner ~25 kn, feribot ~28 kn).
   Aşanlar *anomali değil*, **hatalı kayıt** olarak işaretlenir.
3. **Boşluk etiketleme:** ardışık kayıtlar arası süre > eşik ise boşluk kaydı
   açılır. Eşik, geminin sınıfına göre değişir (Class A 2-10 sn, Class B 30 sn).
4. **Yeniden örnekleme:** sabit adımlı (10 sn) yörünge. Boşluklar
   **doldurulmaz**, boş bırakılır — sahte veri üretmemek için.
5. **Durum sınıflama:** `seyir` (SOG>2) / `manevra` (0.5-2) / `duruş` (<0.5),
   ve duruş için `rıhtım` vs `demirleme` ayrımı (kıyıya mesafe + Moored bayrağı).
6. **Sabit nesne eleme:** 45 gün boyunca hiç hareket etmeyen MMSI'ler
   (şamandıra, platform, ölçüm istasyonu) ayrı sınıfa alınır.
   Ölçüldü: tek bir MMSI 3 günde 27.011 kayıtla hiç kıpırdamamış.

**Doğrulama kapısı**
- Gürültü filtresi sonrası >40 kn olay sayısı: 2.295 → **< 20**
- Sabit nesne olarak işaretlenen MMSI listesi elle gözden geçirilebilir
- Rastgele 10 gemi yörüngesi haritada çizilip görsel kontrolden geçer
- Yeniden örneklenmiş yörüngelerde uydurma nokta yok (boşluklar boş)

---

### P2 — Karşılaşma riski (CPA / TCPA) ⭐ *başlık özellik*

Portföy projelerinde neredeyse hiç görülmeyen, operasyonel olarak gerçek analiz.

1. Her zaman diliminde **sadece seyir halindeki** gemiler arasında CPA
   (en yakın yaklaşma mesafesi) ve TCPA (o ana kalan süre) hesabı.
2. Uzamsal indeks (KD-ağacı) + zaman kovaları — kaba kuvvet O(n²) yerine.
3. Risk skoru: CPA mesafesi + TCPA + göreli hız + gemi boyu.
4. **Storebælt'in özel hali:** feribot–transit dik kesişimleri ayrı sınıflanır.
5. Çıktı: risk sıcaklık haritası + en riskli N karşılaşmanın zaman çizelgesi.

**Doğrulama kapısı**
- Ölçülen taban (3 gün, ≥30 m): 221 benzersiz çift < 463 m.
  Duran gemiler ayıklandıktan sonra bu sayı **düşmeli** — düşmezse filtre çalışmıyor.
- En riskli 5 karşılaşma tek tek yörünge çizimiyle doğrulanır
- Bilinen feribot hatlarının kesişim noktaları risk haritasında görünmeli

---

### P3 — AIS boşluk ve anomali tespiti ⭐ *başlık özellik*

Projenin "karanlık gemi" kimliğini **SAR olmadan** sürdüren eksen.

1. **Sinyal kesintisi:** seyir halindeyken beklenenden uzun sessizlik.
   Ölçülen taban (3 gün): 5-15 dk → 158 olay, 15-60 dk → 81, >1 sa → 118.
2. **Bağlamsal skorlama:** her boşluk aynı değerde değil.
   Kapsama sınırında mı? Yoğun bölgede mi? Gemi tipi riskli mi?
   Boşluk öncesi/sonrası rota tutarlı mı (kapanma sırasında sapma var mı)?
3. **Kimlik anomalileri:** aynı MMSI'nin iki farklı yerde olması,
   MMSI–IMO uyuşmazlığı, geçersiz MMSI formatı.
4. **Davranış anomalileri:** rota dışı dolaşma, beklenmedik duruş,
   tanımlı trafik ayrım şemasına aykırı hareket.

> **Uyarı:** "imkânsız hız" ham haliyle **kullanılmayacak** — P1'de gürültü
> olarak filtrelenecek. Anomali olarak raporlanan tek şey, gürültü modeliyle
> açıklanamayan sıçramalar olacak.

**Doğrulama kapısı**
- Raporlanan her anomali sınıfı için elle doğrulanmış en az 3 örnek
- Yanlış pozitif oranı: rastgele 30 anomali elle incelenir, ≥%70'i gerçek olmalı
- Alıcı gürültüsü kaynaklı olay sayısı sıfıra yakın

---

### P4 — Bekleme ve tıkanıklık *(destek katmanı)*

1. Demirleme/bekleme alanlarının **veriden keşfi** (kümeleme), elle çizim değil.
   Ölçüldü: 55.06N 10.62E'de 53 gemi, `Moored` oranı %10 → gerçek bekleme alanı.
2. Gemi başına bekleme süresi dağılımı, tipe ve boya göre kırılım.
3. Zaman serisi: günün saati / haftanın günü yoğunluk deseni.
4. Darboğaz tespiti: hızın sistematik düştüğü koridorlar.

**Doğrulama kapısı**
- Keşfedilen bekleme alanları harita üzerinde denizcilik pratiğiyle tutarlı
- Rıhtımda duran gemiler "bekliyor" sayılmıyor (Moored + kıyı mesafesi kontrolü)
- Sabit nesneler (şamandıra vb.) sonuçlara karışmıyor

---

### P5 — Karbon salımı ve meteoroloji *(destek katmanı)*

1. IMO 4. GHG Çalışması yaklaşımı: tip + boy + hız → güç → yakıt → CO₂.
   Veri yeterliliği ölçüldü: SOG %97, Length %93, tip %100 dolu.
2. Bekleme/rölanti sırasındaki salım ayrı hesaplanır — **P4 ile bağlanır**:
   "tıkanıklık şu kadar fazladan CO₂ demek."
3. Meteoroloji (rüzgâr/akıntı) eklenerek direnç düzeltmesi.
4. **Dürüstlük notu:** bu bir *tahmin*tir, ölçüm değil. Belirsizlik aralığı
   birlikte raporlanacak; tek bir kesin sayı sunulmayacak.

**Doğrulama kapısı**
- Toplam salım, bilinen kıyaslama değerleriyle aynı büyüklük mertebesinde
- Belirsizlik aralığı her çıktıda görünür

---

### P6 — Dashboard (3B + zaman)

1. Harita üzerinde zaman kaydırıcılı yörünge oynatımı.
2. Katmanlar: risk sıcaklık haritası, anomali işaretleri, bekleme alanları, salım.
3. 3B eksen **zaman veya risk yoğunluğu** olarak kullanılır — süslemek için değil.
4. Mevcut FastAPI iskeleti (`dashboard/app.py`) temel alınır;
   `app.py:21`'deki dosya varlık kontrolü eksikliği düzeltilir.

---

### P7 — SAR karanlık gemi modülü *(ertelendi, iptal değil)*

Hazır olduğunda:
1. `myGraph.xml` → `nodataValueAtSea` **false**
2. SNAP yeniden işleme (ham `.SAFE.zip`'ler duruyor, yeniden indirme yok)
3. `TECHNICAL_PLAN.md`'deki Faz 1-6 uygulanır
4. SAR tespitleri P3'ün anomali katmanına **bağımsız kanıt** olarak eklenir:
   AIS boşluğu + SAR tespiti = güçlü karanlık gemi delili

Faz 0'da yazılan `geoport/obb.py` bu modül için hazır bekliyor.

---

## 4. Portföy açısından ne anlatıyor

| Katman | Gösterdiği yetkinlik |
|---|---|
| P1 yörünge motoru | Büyük ölçekli, gürültülü zaman serisi verisiyle çalışma |
| P2 CPA/TCPA | Uzamsal indeksleme, geometri, algoritmik verimlilik |
| P3 anomali | Sinyal/gürültü ayrımı, bağlamsal skorlama, yanlış pozitif yönetimi |
| P4-P5 | Alan bilgisi (denizcilik, IMO metodolojisi) |
| P6 | Ürünleştirme, görselleştirme |
| P7 | Uzaktan algılama, derin öğrenme, çok kaynaklı füzyon |

**Anlatının en güçlü yeri** yaptıklarımız değil, *bulduğumuz kök neden* olacak:
"Hattı kurdum, sonuçlar tutmadı, ölçtüm, denizin silindiğini buldum."
Bu, biten bir dashboard'dan daha çok mühendislik olgunluğu gösterir.

---

## 5. Taşınan ilkeler

1. **Önce ölç, sonra inşa et.** Bu seansta SAR'ı haftalarca yeniden inşa
   etmekten bu ilke kurtardı.
2. **Tek parametre kaynağı.** `config.py` dışında sabit tanımlanmaz.
3. **Her fazın sonunda ölçülebilir doğrulama kapısı.** Kapı geçilmeden ilerlenmez.
4. **Belirsizliği gizleme.** Tahmin olan şey tahmin diye sunulur.
