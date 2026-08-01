from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import os
import json

app = FastAPI(title="Geoport-AI Dashboard")

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(BASE_DIR, "data", "dark_vessel_results")

# Ensure directories exist
os.makedirs(os.path.join(BASE_DIR, "dashboard", "static"), exist_ok=True)

# Serve static files
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "dashboard", "static")), name="static")

@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(BASE_DIR, "dashboard", "static", "index.html"))

@app.get("/api/dark_vessels")
async def get_dark_vessels():
    file_path = os.path.join(RESULTS_DIR, "dark_vessels.geojson")
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return JSONResponse(content=json.load(f))
    return JSONResponse(content={"type": "FeatureCollection", "features": []})

@app.get("/api/matched_vessels")
async def get_matched_vessels():
    file_path = os.path.join(RESULTS_DIR, "matched_vessels.geojson")
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return JSONResponse(content=json.load(f))
    return JSONResponse(content={"type": "FeatureCollection", "features": []})

@app.get("/api/ghost_signals")
async def get_ghost_signals():
    file_path = os.path.join(RESULTS_DIR, "ghost_signals.geojson")
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return JSONResponse(content=json.load(f))
    return JSONResponse(content={"type": "FeatureCollection", "features": []})

@app.get("/api/report")
async def get_report():
    file_path = os.path.join(RESULTS_DIR, "dark_vessel_report.json")
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return JSONResponse(content=json.load(f))
    return JSONResponse(content={})
