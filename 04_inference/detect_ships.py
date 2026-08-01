"""
GeoPort-AI: Hybrid Ship Detection Pipeline
============================================================
Combines CFAR (Constant False Alarm Rate) statistical detector with
YOLO-OBB / YOLO deep learning model.

1. CFAR: Detects 1-2 pixel small vessel candidates and weak targets
2. YOLO: Detects larger vessels with bounding boxes and confidence scores
3. Fusion: Merges overlapping detections via distance-based NMS
"""

import os
import argparse
import glob
import json

import cv2
import numpy as np
from ultralytics import YOLO

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from cfar_detector import compute_land_mask, cfar_detect, cluster_detections


def detect_hybrid(tile_path: str, yolo_model: YOLO, is_fallback_model: bool = False,
                  distance_threshold: float = 15.0,
                  sea_mask_gis: np.ndarray = None) -> list:
    """
    Runs both CFAR and YOLO on a single SAR tile and fuses the detection candidates.
    
    Args:
        tile_path: TIF/PNG SAR image file path
        yolo_model: Loaded Ultralytics YOLO model instance
        is_fallback_model: True if using generic pretrained yolov8n.pt (requires class 8 filter)
        distance_threshold: Max distance (pixels) to deduplicate overlapping CFAR & YOLO detections
    """
    img = cv2.imread(tile_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return []
    
    if len(img.shape) == 3 and img.shape[2] == 1:
        img = img.squeeze(2)
        
    img_rgb = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    
    # 1. CFAR Detections
    intensity_sea_mask = compute_land_mask(img)
    if sea_mask_gis is not None:
        sea_mask = sea_mask_gis & intensity_sea_mask
    else:
        sea_mask = intensity_sea_mask
        
    cfar_mask = cfar_detect(img, sea_mask)
    cfar_dets = cluster_detections(cfar_mask)
    
    # 2. YOLO Detections
    predict_kwargs = {"verbose": False}
    if is_fallback_model:
        predict_kwargs["classes"] = [config.YOLO_BOAT_CLASS_ID]  # Filter for boat class only

    results = yolo_model(img_rgb, **predict_kwargs)
    yolo_dets = []
    
    for r in results:
        for box in r.boxes:
            x1, y1, x2, y2 = [float(v) for v in box.xyxy[0].cpu().numpy()]
            cx = float((x1 + x2) / 2.0)
            cy = float((y1 + y2) / 2.0)
            
            # Check bounds and landmask
            int_cy, int_cx = int(cy), int(cx)
            if 0 <= int_cy < sea_mask.shape[0] and 0 <= int_cx < sea_mask.shape[1]:
                if not sea_mask[int_cy, int_cx]:
                    continue
            
            yolo_dets.append({
                "cx": cx,
                "cy": cy,
                "type": "YOLO",
                "bbox": [x1, y1, x2, y2],
                "conf": float(box.conf[0])
            })
    
    # 3. Fusion (NMS / Distance Matching)
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
    """Processes all image tiles in a directory and saves hybrid detections."""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    print(f"Loading YOLO model from: {model_path}")
    is_fallback = False
    try:
        model = YOLO(model_path)
    except Exception as e:
        print(f"Warning: Custom model weights not found ({e}). Falling back to pretrained {config.FALLBACK_YOLO_MODEL} (class 8 filter active).")
        model = YOLO(config.FALLBACK_YOLO_MODEL)
        is_fallback = True
        
    files = sorted(glob.glob(os.path.join(img_dir, "*.png")))
    print(f"Processing {len(files)} image tiles...")
    
    all_results = {}
    
    for i, file_path in enumerate(files):
        basename = os.path.basename(file_path)
        dets = detect_hybrid(file_path, model, is_fallback_model=is_fallback)
        all_results[basename] = dets
        
        if (i + 1) % 100 == 0 or (i + 1) == len(files):
            print(f"... {i+1}/{len(files)} tiles processed.")
            
    out_file = os.path.join(output_dir, "hybrid_detections.json")
    with open(out_file, "w") as f:
        json.dump(all_results, f, indent=2)
        
    print(f"\nProcessing complete. Results written to: {out_file}")
    
    yolo_count = sum(1 for tiles in all_results.values() for d in tiles if d["type"] == "YOLO")
    cfar_count = sum(1 for tiles in all_results.values() for d in tiles if d["type"] == "CFAR")
    print(f"Total YOLO Detections: {yolo_count}")
    print(f"Total CFAR Detections: {cfar_count}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GeoPort-AI Hybrid Ship Detection Pipeline")
    parser.add_argument("--img-dir", type=str, default="data/yolo_dataset/images/val",
                        help="Input image directory containing tiles")
    parser.add_argument("--model-path", type=str, default=config.DEFAULT_YOLO_MODEL_PATH,
                        help="Path to trained YOLO model weights")
    parser.add_argument("--out-dir", type=str, default=config.HYBRID_RESULTS_DIR,
                        help="Output directory for hybrid detections JSON")
    
    args = parser.parse_args()
    process_directory(args.img_dir, args.model_path, args.out_dir)
