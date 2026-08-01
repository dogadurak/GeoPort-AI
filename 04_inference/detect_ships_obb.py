"""
GeoPort-AI: Hybrid Ship Detection Pipeline (OBB Version)
============================================================
Bu modül, CFAR istatistiksel dedektörü ile yeni eğitilmiş
YOLO-OBB (Oriented Bounding Box) derin öğrenme modelini birleştirir.

Eski 'detect_ships.py' scriptini KORUMAK için bu dosya özel olarak
OBB formatındaki açılı kutuları okuyacak şekilde yeniden tasarlanmıştır.
"""

raise SystemExit(
    "detect_ships_obb.py DEVRE DIŞI (Faz 0, 2026-08-01).\n"
    "Sebep: Ürettiği hybrid_detections_obb.json içinde 0 adet YOLO-OBB tespiti\n"
    "       vardı — OBB modeli hiç öğrenmemişti (loss=0). Ayrıca detect_ships.py\n"
    "       ile %80 kopya ve sahne düzeyi tekilleştirme yok (aynı gemi 2 kez).\n"
    "Yerine: Faz 5'te geoport/detect/ (tek implementasyon + global NMS) gelecek.\n"
    "Ayrıntı: TECHNICAL_PLAN.md"
)

import os
import argparse
import glob
import json

import cv2
import numpy as np
from ultralytics import YOLO

# CFAR Fonksiyonları (Eski yapıdan aynen alınmıştır, dokunulmadı)
from cfar_detector import compute_land_mask, cfar_detect, cluster_detections


def detect_hybrid_obb(tile_path: str, yolo_model: YOLO,
                      distance_threshold: float = 15.0,
                      sea_mask_gis: np.ndarray = None) -> list:
    img = cv2.imread(tile_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return []
    
    if len(img.shape) == 3 and img.shape[2] == 1:
        img = img.squeeze(2)
        
    img_rgb = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    
    # 1. CFAR Tespitleri (Dokunulmadı)
    intensity_sea_mask = compute_land_mask(img)
    if sea_mask_gis is not None:
        sea_mask = sea_mask_gis & intensity_sea_mask
    else:
        sea_mask = intensity_sea_mask
        
    cfar_mask = cfar_detect(img, sea_mask)
    cfar_dets = cluster_detections(cfar_mask)
    
    # 2. YOLO-OBB Tespitleri (YENİ OBB MANTIĞI)
    results = yolo_model(img_rgb, verbose=False)
    yolo_dets = []
    
    for r in results:
        # Eğer model OBB ise r.obb dizisi dolu gelir
        if r.obb is not None:
            for obb_box in r.obb:
                # OBB formatı xywhr şeklindedir (center_x, center_y, width, height, rotation)
                cx, cy, w, h, angle = [float(v) for v in obb_box.xywhr[0].cpu().numpy()]
                
                # Kara parçasındaysa atla
                if not sea_mask[int(cy), int(cx)]:
                    continue
                
                # Açılı kutu köşe koordinatlarını al (görselleştirme/geojson için)
                points = obb_box.xyxyxyxy[0].cpu().numpy().tolist()
                
                yolo_dets.append({
                    "cx": cx,
                    "cy": cy,
                    "type": "YOLO-OBB",
                    "bbox_points": points, # Açılı kutunun 4 köşesi
                    "conf": float(obb_box.conf[0])
                })
    
    # 3. Sonuç Füzyonu
    fused_detections = []
    
    for yd in yolo_dets:
        fused_detections.append(yd)
        
    for cd in cfar_dets:
        is_duplicate = False
        for yd in yolo_dets:
            dist = np.sqrt((cd["cx"] - yd["cx"])**2 + (cd["cy"] - yd["cy"])**2)
            if dist < distance_threshold:
                is_duplicate = True
                break
                
        if not is_duplicate:
            fused_detections.append({
                "cx": cd["cx"],
                "cy": cd["cy"],
                "type": "CFAR",
                "area_px": cd["area_px"]
            })
            
    return fused_detections


def process_directory(img_dir: str, model_path: str, output_dir: str):
    import re

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    print(f"YOLO-OBB modeli yükleniyor: {model_path}")
    try:
        model = YOLO(model_path)
    except Exception as e:
        print(f"HATA: Model yüklenemedi ({e}). Lütfen train_yolo.py ile OBB modelini eğitin.")
        return
        
    files = glob.glob(os.path.join(img_dir, "*.png"))
    print(f"Toplam {len(files)} görüntü işlenecek.")
    
    all_results = {}
    
    for i, file_path in enumerate(files):
        basename = os.path.basename(file_path)
        
        dets = detect_hybrid_obb(file_path, model, sea_mask_gis=None)
        all_results[basename] = dets
        
        if (i+1) % 50 == 0:
            print(f"... {i+1}/{len(files)} işlendi.")
            
    out_file = os.path.join(output_dir, "hybrid_detections_obb.json")
    with open(out_file, "w") as f:
        json.dump(all_results, f, indent=2)
        
    print(f"\nİşlem tamamlandı. Sonuçlar {out_file} dosyasına kaydedildi.")
    
    yolo_count = sum(1 for tiles in all_results.values() for d in tiles if d["type"] == "YOLO-OBB")
    cfar_count = sum(1 for tiles in all_results.values() for d in tiles if d["type"] == "CFAR")
    print(f"Toplam YOLO-OBB Tespiti: {yolo_count}")
    print(f"Toplam CFAR Tespiti: {cfar_count}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--img-dir", type=str, default="data/yolo_dataset/images/val",
                        help="İşlenecek görüntü klasörü")
    # VARSAYILAN MODEL: Yeni eğiteceğimiz obb modeli
    parser.add_argument("--model-path", type=str, default="runs/obb/geoport_obb_v1/weights/best.pt",
                        help="Eğitilmiş YOLO-OBB modeli")
    parser.add_argument("--out-dir", type=str, default="data/hybrid_results")
    
    args = parser.parse_args()
    process_directory(args.img_dir, args.model_path, args.out_dir)
