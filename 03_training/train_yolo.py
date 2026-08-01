raise SystemExit(
    "train_yolo.py DEVRE DIŞI (Faz 0, 2026-08-01).\n"
    "Sebep: İhtiyaç duyduğu data/yolo_dataset/data.yaml yok; önceki tüm OBB\n"
    "       eğitimlerinde loss=0 ve mAP=0 çıkmıştı (dataloader hiç etiket görmedi).\n"
    "       Ayrıca device=0 sabit — GPU yoksa çöker.\n"
    "Yerine: Faz 4b'de geoport/train.py gelecek (Faz 3 veri setinden sonra).\n"
    "Ayrıntı: TECHNICAL_PLAN.md"
)

import os
from ultralytics import YOLO

def train_obb():
    # Model: YOLOv8 OBB (Oriented Bounding Box) modeli kullanılmalı.
    # Standart 'yolov8n.pt' HBB (Düz Kutu) üretir, bizim veri setimiz ise OBB (Açılı Kutu).
    model = YOLO("yolov8n-obb.pt")

    # Veri seti yapılandırma dosyası
    data_yaml = os.path.abspath("data/yolo_dataset/data.yaml")

    # Eğitimi başlat
    results = model.train(
        data=data_yaml,
        epochs=50,             # Başlangıç için 50 epoch idealdir.
        imgsz=512,             # Karolarımızı 512x512 hazırladığımız için imgsz=512 kalmalı.
        batch=16,              # Ekran kartı belleğinize göre 8 veya 32 yapılabilir.
        device=0,              # GPU kullanımı (CUDA varsa)
        project="runs/obb",    # Eski 'runs/detect' ile karışmaması için projeyi ayırıyoruz.
        name="geoport_obb_v1", # Bu eğitimin adı
        optimizer="auto",      # Otomatik optimizer seçimi (genelde AdamW)
        patience=10,           # 10 epoch boyunca iyileşme olmazsa eğitimi erken durdur.
        exist_ok=True          # Aynı isimde klasör varsa üstüne yazar
    )

    print("Eğitim tamamlandı. Model ağırlıkları 'runs/obb/geoport_obb_v1/weights/best.pt' yolunda bulunabilir.")

if __name__ == "__main__":
    train_obb()
