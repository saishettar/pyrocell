"""
FastAPI backend. Phase 5 endpoints serve the pre-rendered Soberanes demo;
Phase 6 adds POST /api/simulate for on-demand click-to-simulate at an
arbitrary point within the fetched Big Sur AOI.

Usage:
    venv/Scripts/python.exe -m uvicorn backend.api.main:app --reload --port 8000
(run from the repo root so the "backend" package path resolves)
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
FRAMES_DIR = ROOT / "data" / "frames"
RAW_DIR = ROOT / "data" / "raw"
FRONTEND_DIR = ROOT / "frontend"

sys.path.insert(0, str(ROOT / "backend" / "simulation"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from soberanes_conditions import PROCESSED_DIR, latlon_to_rowcol, load_grid  # noqa: E402

from simulate import MAX_HOURS, MIN_HOURS, SimulationError, run_click_simulation  # noqa: E402

app = FastAPI(title="pyrocell")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

app.mount("/frames", StaticFiles(directory=FRAMES_DIR), name="frames")


@app.get("/api/meta")
def get_meta():
    return FileResponse(FRAMES_DIR / "meta.json")


@app.get("/api/perimeter")
def get_perimeter():
    return FileResponse(RAW_DIR / "soberanes_perimeter.geojson")


# Grid + calibrated params loaded once at startup, not per-request --
# rasterio file reads and the LFPS bundle don't change between requests.
_elevation_m, _fuel_code, _transform, _crs, _cell_size_m, _, _ = load_grid()
_grid = (_elevation_m, _fuel_code, _transform, _crs, _cell_size_m, lambda lat, lon: latlon_to_rowcol(lat, lon, _transform, _crs))


def _load_calibrated_params() -> dict:
    path = PROCESSED_DIR / "calibrated_params.txt"
    if not path.exists():
        raise RuntimeError(f"{path} missing -- run calibrate.py first")
    values = {}
    with open(path) as f:
        for line in f:
            k, v = line.strip().split("=")
            values[k] = float(v)
    return values


_calibrated_params = _load_calibrated_params()


class SimulateRequest(BaseModel):
    lat: float
    lon: float
    hours: int = 48
    start_time: str | None = None  # ISO 8601, naive UTC; omit for live current wind


@app.post("/api/simulate")
def simulate(req: SimulateRequest):
    try:
        return run_click_simulation(req.lat, req.lon, req.hours, req.start_time, _grid, _calibrated_params)
    except SimulationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/simulate/limits")
def simulate_limits():
    return {"min_hours": MIN_HOURS, "max_hours": MAX_HOURS}


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
