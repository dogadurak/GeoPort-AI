"""
GeoPort-AI: Results Verification Script
=======================================
Cross-checks the dark_vessel_report.json numbers against underlying
GeoJSON output files to catch silent errors (double counting, spatial out-of-bounds,
or Matched + Ghost mismatch against total AIS).
"""

raise SystemExit(
    "verify_dark_vessel_results.py DEVRE DIŞI (Faz 0, 2026-08-01).\n"
    "Sebep: Rapor dosyası yoksa exit code 0 ile SESSİZCE geçiyor — 'doğrulama'\n"
    "       scripti hiçbir şey doğrulamadan başarılı görünüyor. Ayrıca arşivlenen\n"
    "       eski raporu (total_yolo anahtarlı) doğruluyordu.\n"
    "Yerine: Faz 7'de gerçek invariant'ları kontrol eden sürüm gelecek.\n"
    "Ayrıntı: TECHNICAL_PLAN.md"
)

import json
import os
import geopandas as gpd

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

REPORT_PATH = os.path.join(config.DARK_VESSEL_RESULTS_DIR, "dark_vessel_report.json")
DARK_PATH = os.path.join(config.DARK_VESSEL_RESULTS_DIR, "dark_vessels.geojson")
MATCHED_PATH = os.path.join(config.DARK_VESSEL_RESULTS_DIR, "matched_vessels.geojson")
GHOST_PATH = os.path.join(config.DARK_VESSEL_RESULTS_DIR, "ghost_signals.geojson")

issues = []


def check(label: str, condition: bool, detail: str = ""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        issues.append(label)


def main():
    if not os.path.exists(REPORT_PATH):
        print(f"Report file not found at {REPORT_PATH}")
        return

    with open(REPORT_PATH) as f:
        report = json.load(f)

    scene_report = report.get("scenes", [])

    # 1. Scene count check
    check("Report contains processed scenes", len(scene_report) > 0, f"Found {len(scene_report)} scenes")

    # 2. Total Matched + Total Ghost = Total AIS
    total_matched = sum(s["matched"] for s in scene_report)
    total_ghosts = sum(s["ghost_signals"] for s in scene_report)
    total_ais = sum(s["total_ais"] for s in scene_report)

    check("Total Matched + Total Ghost == Total AIS", total_matched + total_ghosts == total_ais,
          f"{total_matched} + {total_ghosts} != {total_ais}")
    check("Summary report numbers match aggregated sum",
          report["summary"]["total_matched"] == total_matched and
          report["summary"]["total_ghost_signals"] == total_ghosts and
          report["summary"]["total_dark_vessels"] == sum(s["dark_vessels"] for s in scene_report))

    # 3. GeoJSON feature count consistency
    dark_gdf = gpd.read_file(DARK_PATH) if os.path.exists(DARK_PATH) else None
    matched_gdf = gpd.read_file(MATCHED_PATH) if os.path.exists(MATCHED_PATH) else None
    ghost_gdf = gpd.read_file(GHOST_PATH) if os.path.exists(GHOST_PATH) else None

    if dark_gdf is not None:
        check("Dark Vessel GeoJSON feature count matches report",
              len(dark_gdf) == report["summary"]["total_dark_vessels"],
              f"GeoJSON: {len(dark_gdf)}, Report: {report['summary']['total_dark_vessels']}")
    if matched_gdf is not None:
        check("Matched GeoJSON feature count matches report",
              len(matched_gdf) == report["summary"]["total_matched"],
              f"GeoJSON: {len(matched_gdf)}, Report: {report['summary']['total_matched']}")
    if ghost_gdf is not None:
        check("Ghost GeoJSON feature count matches report",
              len(ghost_gdf) == report["summary"]["total_ghost_signals"],
              f"GeoJSON: {len(ghost_gdf)}, Report: {report['summary']['total_ghost_signals']}")

    # 4. Spatial extent sanity check
    bbox = config.STOREBAELT_BBOX
    if dark_gdf is not None and len(dark_gdf) > 0:
        bounds = dark_gdf.total_bounds
        is_in_bounds = (bounds[0] >= bbox["min_lon"] - 0.5 and bounds[2] <= bbox["max_lon"] + 0.5 and
                        bounds[1] >= bbox["min_lat"] - 0.5 and bounds[3] <= bbox["max_lat"] + 0.5)
        check("Dark Vessels are within Storebaelt spatial extent", is_in_bounds, f"Bounds: {bounds}")

    print("\n--- VERIFICATION RESULT ---")
    if issues:
        print(f"[FAIL] {len(issues)} ISSUE(S) DETECTED:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("[SUCCESS] ALL VERIFICATION CHECKS PASSED SUCCESSFULLY.")


if __name__ == "__main__":
    main()
