"""
GeoPort-AI: CFAR (Constant False Alarm Rate) Ship Detector
============================================================
Sentinel-1 SAR görüntülerinde gemi tespiti için endüstri standardı
istatistiksel dedektör.

CFAR, her piksel için çevresindeki deniz yüzeyinin istatistiksel 
özelliklerini hesaplar ve anlamlı derecede parlak (yüksek backscatter) 
pikselleri "gemi adayı" olarak işaretler.

Neden CFAR?
- SAR'da gemiler çevrelerine göre çok daha parlak backscatter verir
- 1 piksellik hedeflerde bile çalışır (bbox gerektirmez)
- Gerçek deniz gözetleme sistemlerinin birincil dedektörüdür

Usage:
    python cfar_detector.py                         # Tüm tile'ları tara
    python cfar_detector.py --visualize             # İlk 5 tile'ı görselleştir
    python cfar_detector.py --tile <tile_path>      # Tek bir tile'ı tara
"""

raise SystemExit(
    "cfar_detector.py DEVRE DIŞI (Faz 0, 2026-08-01).\n"
    "Sebep: MAX_CLUSTER_SIZE=30 px, 244 m'lik gerçek bir gemiyi (~180 px küme)\n"
    "       REDDEDİYOR — filtre ters çalışıyor. Ölçüm: karo başına 13.3 yanlış\n"
    "       alarm (beklenen 0.026). Ayrıca uint8 render üzerinde çalışıyor.\n"
    "Yerine: Faz 4a'da geoport/detect/cfar.py (float dB, Gamma-CFAR) gelecek.\n"
    "Ayrıntı: TECHNICAL_PLAN.md"
)

import argparse
import glob
import os

import cv2
import numpy as np
from scipy import ndimage

# --- Configuration ---
TILE_DIR = "data/yolo_dataset/images"
LABEL_DIR = "data/yolo_dataset/labels"
OUTPUT_DIR = "data/cfar_detections"
VIS_DIR = "data/cfar_visualizations"

# CFAR Parametreleri
GUARD_RADIUS = 2        # Hedefin kendisini kapsayan koruma bölgesi (piksel)
BG_RADIUS = 15          # Arka plan istatistiği hesaplanan bölge (piksel) - Daha geniş bir alan
PFA = 1e-7              # Yanlış alarm olasılığı (Daha katı)
MIN_BRIGHTNESS = 120    # Minimum piksel parlaklığı (0-255 normalized SAR) - Daha dengeli
LAND_THRESHOLD = 200   # Bu değerin üstü büyük olasılıkla kara parçası - Orijinal değere döndü
MIN_CLUSTER_SIZE = 1    # Minimum piksel kümesi boyutu
MAX_CLUSTER_SIZE = 30   # Maksimum piksel kümesi (>30px muhtemelen kara/artefakt)

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(VIS_DIR, exist_ok=True)


def compute_land_mask(tile: np.ndarray, threshold: int = LAND_THRESHOLD,
                      kernel_size: int = 15) -> np.ndarray:
    """
    SAR görüntüsünde kara parçalarını maskeler.
    
    Kara, SAR'da genellikle yüksek ve düzgün backscatter verir.
    Büyük parlak bölgeleri morfolojik operasyonlarla tespit eder.
    
    Returns:
        Boolean mask: True = deniz (geçerli), False = kara (maskelendi)
    """
    # Yüksek parlaklıktaki büyük bölgeleri bul
    bright = tile > threshold
    
    # Morfolojik kapanış: küçük boşlukları doldur (kara üzerindeki gölgeler)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    closed = cv2.morphologyEx(bright.astype(np.uint8), cv2.MORPH_CLOSE, kernel)
    
    # Morfolojik açılış: küçük noktaları (gemileri) kaldır
    opened = cv2.morphologyEx(closed, cv2.MORPH_OPEN, kernel)
    
    # Bağlı bileşen analizi: küçük parlak noktalar gemi, büyük alanlar kara
    labeled, n_features = ndimage.label(opened)
    component_sizes = ndimage.sum(opened, labeled, range(1, n_features + 1))
    
    land_mask = np.zeros_like(tile, dtype=bool)
    for i, size in enumerate(component_sizes):
        if size > 500:  # 500 pikselden büyük parlak bölgeler = kara
            land_mask[labeled == (i + 1)] = True
    
    # Kara maskesini genişlet (kıyı şeridindeki yanlış alarmları önle)
    dilate_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
    land_mask = cv2.dilate(land_mask.astype(np.uint8), dilate_kernel).astype(bool)
    
    # True = deniz (geçerli alan)
    sea_mask = ~land_mask
    return sea_mask


def cfar_detect(tile: np.ndarray, sea_mask: np.ndarray,
                guard_radius: int = GUARD_RADIUS,
                bg_radius: int = BG_RADIUS,
                pfa: float = PFA) -> np.ndarray:
    """
    2D CA-CFAR (Cell Averaging CFAR) dedektörü.
    
    Her piksel (CUT = Cell Under Test) için:
    1. Guard bölgesi: CUT etrafında guard_radius kadar piksel (hedefin kendisi)
    2. Background bölgesi: Guard'ın dışında bg_radius kadar piksel (deniz yüzeyi)
    3. Background'un ortalaması ve std'si hesaplanır
    4. CUT > mean + T * std ise hedef olarak işaretlenir
    
    T (threshold multiplier) PFA'dan türetilir.
    
    Returns:
        Boolean detection mask: True = gemi adayı
    """
    tile_f = tile.astype(np.float64)
    if len(tile_f.shape) == 3 and tile_f.shape[2] == 1:
        tile_f = tile_f.squeeze(2)
    h, w = tile_f.shape
    
    # Threshold multiplier: PFA'dan Gaussian yaklaşımla türet
    # T = sqrt(2) * erfinv(1 - 2*PFA) ≈ daha basit: -log(PFA) tabanlı
    from scipy.special import erfinv
    T = np.sqrt(2) * erfinv(1 - 2 * pfa)
    
    # Verimli hesaplama için integral görüntüler (box filter)
    # Background bölgesi = büyük kutu - guard kutu
    
    # Büyük kutu (bg_radius)
    bg_size = 2 * bg_radius + 1
    bg_kernel = np.ones((bg_size, bg_size), dtype=np.float64)
    
    # Guard kutu
    guard_size = 2 * guard_radius + 1
    guard_kernel = np.zeros((bg_size, bg_size), dtype=np.float64)
    g_start = bg_radius - guard_radius
    g_end = bg_radius + guard_radius + 1
    guard_kernel[g_start:g_end, g_start:g_end] = 1.0
    
    # Annular kernel = bg - guard
    annular_kernel = bg_kernel - guard_kernel
    n_bg_cells = annular_kernel.sum()
    
    # Ortalama hesapla (convolution ile verimli)
    bg_sum = cv2.filter2D(tile_f, -1, annular_kernel, borderType=cv2.BORDER_REFLECT)
    bg_mean = bg_sum / n_bg_cells
    
    # Standart sapma hesapla
    bg_sq_sum = cv2.filter2D(tile_f ** 2, -1, annular_kernel, borderType=cv2.BORDER_REFLECT)
    bg_var = (bg_sq_sum / n_bg_cells) - (bg_mean ** 2)
    bg_var = np.maximum(bg_var, 0)  # Sayısal kararlılık
    bg_std = np.sqrt(bg_var)
    
    # CFAR eşiği
    threshold_map = bg_mean + T * bg_std
    
    # Tespit: piksel > eşik VE minimum parlaklık VE deniz üzerinde
    detection = (tile_f > threshold_map) & (tile_f > MIN_BRIGHTNESS) & sea_mask
    
    return detection


def cluster_detections(detection_mask: np.ndarray,
                       min_size: int = MIN_CLUSTER_SIZE,
                       max_size: int = MAX_CLUSTER_SIZE) -> list:
    """
    Bitişik pozitif pikselleri gruplandırır ve her grubun 
    merkez koordinatını döndürür.
    
    Returns:
        List of dicts: [{"cx": float, "cy": float, "area_px": int}, ...]
    """
    labeled, n_features = ndimage.label(detection_mask)
    
    detections = []
    for i in range(1, n_features + 1):
        component = (labeled == i)
        area = component.sum()
        
        if area < min_size or area > max_size:
            continue
        
        # Merkez koordinat (intensity-weighted centroid)
        ys, xs = np.where(component)
        cx = float(xs.mean())
        cy = float(ys.mean())
        
        detections.append({
            "cx": cx,
            "cy": cy,
            "area_px": int(area),
        })
    
    return detections


def detect_tile(tile_path: str) -> list:
    """
    Tek bir tile üzerinde CFAR tespitini çalıştırır.
    
    Returns:
        List of detection dicts
    """
    import re
    import rasterio
    from rasterio.windows import Window
    
    img = cv2.imread(tile_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return []
        
    # Attempt to load GIS sea mask
    sea_mask = None
    basename = os.path.basename(tile_path)
    pattern = re.compile(r"^(.*?)_x(\d+)_y(\d+)\.png$")
    match = pattern.match(basename)
    
    if match:
        scene_name = match.group(1)
        x_off = int(match.group(2))
        y_off = int(match.group(3))
        mask_path = f"data/sentinel1/normalized/{scene_name}_landmask.tif"
        
        if os.path.exists(mask_path):
            try:
                with rasterio.open(mask_path) as src:
                    window = Window(x_off, y_off, 512, 512)
                    mask_tile = src.read(1, window=window, boundless=True, fill_value=1)
                    sea_mask = (mask_tile == 0)
            except Exception as e:
                print(f"Warning: Failed to load GIS mask for {basename} ({e})")
                
    if sea_mask is None:
        sea_mask = compute_land_mask(img)
        
    detection_mask = cfar_detect(img, sea_mask)
    detections = cluster_detections(detection_mask)
    
    return detections


def load_ground_truth(label_path: str, tile_size: int = 512) -> list:
    """
    YOLO-OBB formatındaki label dosyasını okur ve merkez koordinatları döndürür.
    
    Returns:
        List of dicts: [{"cx": float, "cy": float}, ...]
    """
    if not os.path.exists(label_path):
        return []
    
    gt_points = []
    with open(label_path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 9:
                continue
            
            # OBB format: class x1 y1 x2 y2 x3 y3 x4 y4 (normalized)
            coords = [float(p) for p in parts[1:9]]
            xs = [coords[i] for i in range(0, 8, 2)]
            ys = [coords[i] for i in range(1, 8, 2)]
            
            cx = sum(xs) / 4 * tile_size
            cy = sum(ys) / 4 * tile_size
            gt_points.append({"cx": cx, "cy": cy})
    
    return gt_points


def evaluate_detections(detections: list, ground_truth: list,
                        distance_threshold: float = 20.0) -> dict:
    """
    Tespit sonuçlarını ground truth ile karşılaştırır.
    Mesafe bazlı eşleştirme kullanır (IoU yerine).
    
    Args:
        distance_threshold: Piksel cinsinden eşleştirme mesafesi (20px = 200m @ 10m/px)
    
    Returns:
        dict: {"tp": int, "fp": int, "fn": int, "precision": float, "recall": float}
    """
    matched_gt = set()
    matched_det = set()
    
    for d_idx, det in enumerate(detections):
        best_dist = float("inf")
        best_gt_idx = -1
        
        for g_idx, gt in enumerate(ground_truth):
            if g_idx in matched_gt:
                continue
            
            dist = np.sqrt((det["cx"] - gt["cx"]) ** 2 + (det["cy"] - gt["cy"]) ** 2)
            if dist < best_dist:
                best_dist = dist
                best_gt_idx = g_idx
        
        if best_dist <= distance_threshold and best_gt_idx >= 0:
            matched_gt.add(best_gt_idx)
            matched_det.add(d_idx)
    
    tp = len(matched_gt)
    fp = len(detections) - tp
    fn = len(ground_truth) - tp
    
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    
    return {
        "tp": tp, "fp": fp, "fn": fn,
        "precision": precision, "recall": recall, "f1": f1,
    }


def visualize_tile(tile_path: str, detections: list, ground_truth: list,
                   output_path: str) -> None:
    """
    Bir tile üzerinde CFAR tespitlerini ve ground truth'u görselleştirir.
    Kırmızı: CFAR tespiti, Yeşil: Ground Truth (AIS)
    """
    img = cv2.imread(tile_path)
    if img is None:
        return
    
    # Ground truth (yeşil daireler)
    for gt in ground_truth:
        cv2.circle(img, (int(gt["cx"]), int(gt["cy"])), 8, (0, 255, 0), 2)
        cv2.circle(img, (int(gt["cx"]), int(gt["cy"])), 2, (0, 255, 0), -1)
    
    # CFAR tespitleri (kırmızı daireler)
    for det in detections:
        cv2.circle(img, (int(det["cx"]), int(det["cy"])), 6, (0, 0, 255), 2)
        cv2.putText(img, f"{det['area_px']}px",
                    (int(det["cx"]) + 8, int(det["cy"]) - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 255), 1)
    
    # Bilgi metni
    info = f"CFAR: {len(detections)} det | GT: {len(ground_truth)} ships"
    cv2.putText(img, info, (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)
    
    cv2.imwrite(output_path, img)


def run_full_evaluation(split: str = "val") -> dict:
    """
    Tüm val veya train seti üzerinde CFAR değerlendirmesi yapar.
    """
    img_dir = os.path.join(TILE_DIR, split)
    lbl_dir = os.path.join(LABEL_DIR, split)
    
    tile_files = sorted(glob.glob(os.path.join(img_dir, "*.png")))
    
    total_tp, total_fp, total_fn = 0, 0, 0
    tiles_with_ships = 0
    tiles_detected = 0
    
    print(f"\n{'='*60}")
    print(f"CFAR Evaluation on {split} set ({len(tile_files)} tiles)")
    print(f"{'='*60}")
    print(f"Guard radius: {GUARD_RADIUS}, BG radius: {BG_RADIUS}, PFA: {PFA}")
    print(f"Min brightness: {MIN_BRIGHTNESS}")
    print()
    
    for i, tile_path in enumerate(tile_files):
        basename = os.path.splitext(os.path.basename(tile_path))[0]
        label_path = os.path.join(lbl_dir, f"{basename}.txt")
        
        detections = detect_tile(tile_path)
        ground_truth = load_ground_truth(label_path)
        
        if ground_truth:
            tiles_with_ships += 1
            metrics = evaluate_detections(detections, ground_truth)
            total_tp += metrics["tp"]
            total_fp += metrics["fp"]
            total_fn += metrics["fn"]
            
            if metrics["tp"] > 0:
                tiles_detected += 1
            
            if metrics["tp"] > 0 or metrics["fn"] > 0:
                print(f"  [{basename[-20:]}] GT={len(ground_truth)} "
                      f"DET={len(detections)} TP={metrics['tp']} "
                      f"FP={metrics['fp']} FN={metrics['fn']}")
        else:
            # Arka plan tile'ı — yanlış alarmları say
            if detections:
                total_fp += len(detections)
        
        if (i + 1) % 100 == 0:
            print(f"  ... {i+1}/{len(tile_files)} tile işlendi")
    
    # Toplam metrikler
    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    
    results = {
        "split": split,
        "total_tiles": len(tile_files),
        "tiles_with_ships": tiles_with_ships,
        "tiles_detected": tiles_detected,
        "total_tp": total_tp,
        "total_fp": total_fp,
        "total_fn": total_fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }
    
    print(f"\n{'='*60}")
    print(f"CFAR SONUÇLARI ({split})")
    print(f"{'='*60}")
    print(f"Gemi içeren tile sayısı:   {tiles_with_ships}")
    print(f"En az 1 tespit olan tile:  {tiles_detected}")
    print(f"True Positives:            {total_tp}")
    print(f"False Positives:           {total_fp}")
    print(f"False Negatives:           {total_fn}")
    print(f"Precision:                 {precision:.4f}")
    print(f"Recall:                    {recall:.4f}")
    print(f"F1 Score:                  {f1:.4f}")
    print(f"{'='*60}")
    
    return results


def run_with_visualizations(split: str = "val", max_vis: int = 10) -> dict:
    """
    Değerlendirme yapar + gemi içeren tile'ları görselleştirir.
    """
    img_dir = os.path.join(TILE_DIR, split)
    lbl_dir = os.path.join(LABEL_DIR, split)
    
    tile_files = sorted(glob.glob(os.path.join(img_dir, "*.png")))
    
    vis_count = 0
    total_tp, total_fp, total_fn = 0, 0, 0
    tiles_with_ships = 0
    
    for tile_path in tile_files:
        basename = os.path.splitext(os.path.basename(tile_path))[0]
        label_path = os.path.join(lbl_dir, f"{basename}.txt")
        
        detections = detect_tile(tile_path)
        ground_truth = load_ground_truth(label_path)
        
        if ground_truth:
            tiles_with_ships += 1
            metrics = evaluate_detections(detections, ground_truth)
            total_tp += metrics["tp"]
            total_fp += metrics["fp"]
            total_fn += metrics["fn"]
            
            if vis_count < max_vis:
                vis_path = os.path.join(VIS_DIR, f"cfar_{basename[-30:]}.png")
                visualize_tile(tile_path, detections, ground_truth, vis_path)
                vis_count += 1
                print(f"  Görsel kaydedildi: {vis_path}")
        else:
            if detections:
                total_fp += len(detections)
    
    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    
    print(f"\nCFAR Sonuç: P={precision:.3f} R={recall:.3f} F1={f1:.3f}")
    print(f"TP={total_tp} FP={total_fp} FN={total_fn}")
    print(f"Görselleştirmeler: {VIS_DIR}/")
    
    return {"precision": precision, "recall": recall, "f1": f1,
            "tp": total_tp, "fp": total_fp, "fn": total_fn}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GeoPort-AI CFAR Ship Detector")
    parser.add_argument("--split", default="val", choices=["train", "val"],
                        help="Hangi veri setini tara")
    parser.add_argument("--visualize", action="store_true",
                        help="Görselleştirme çıktıları oluştur")
    parser.add_argument("--tile", type=str, default=None,
                        help="Tek bir tile dosyası tara")
    parser.add_argument("--max-vis", type=int, default=10,
                        help="Maksimum görselleştirme sayısı")
    args = parser.parse_args()
    
    if args.tile:
        # Tek tile modu
        dets = detect_tile(args.tile)
        print(f"Tile: {args.tile}")
        print(f"Tespit edilen gemi adayı: {len(dets)}")
        for d in dets:
            print(f"  ({d['cx']:.1f}, {d['cy']:.1f}) area={d['area_px']}px")
    elif args.visualize:
        run_with_visualizations(args.split, args.max_vis)
    else:
        run_full_evaluation(args.split)
