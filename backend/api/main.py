"""
FastAPI backend. Serves the pre-rendered demo animation for either fire
(Phase 5/8) and POST /api/simulate for on-demand click-to-simulate at an
arbitrary point (Phase 6), fire-aware since Phase 8 added the Dolan grid
alongside Soberanes.

Usage:
    venv/Scripts/python.exe -m uvicorn backend.api.main:app --reload --port 8000
(run from the repo root so the "backend" package path resolves)
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
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
from fire_config import DOLAN, SOBERANES  # noqa: E402
from soberanes_conditions import PROCESSED_DIR, latlon_to_rowcol, load_grid  # noqa: E402

from simulate import MAX_HOURS, MIN_HOURS, SimulationError, run_click_simulation  # noqa: E402

app = FastAPI(title="pyrocell")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

app.mount("/frames", StaticFiles(directory=FRAMES_DIR), name="frames")

FIRE_CONFIGS = {"soberanes": SOBERANES, "dolan": DOLAN}
DEFAULT_SEEDS = {"soberanes": 7, "dolan": 8}


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


def _load_all_grids() -> dict:
    grids = {}
    for slug, fire in FIRE_CONFIGS.items():
        elevation_m, fuel_code, transform, crs, cell_size_m, _, _ = load_grid(
            raw_dir=RAW_DIR / slug, ignition_lat=fire.ignition_lat, ignition_lon=fire.ignition_lon,
        )
        grids[slug] = (
            elevation_m, fuel_code, transform, crs, cell_size_m,
            lambda lat, lon, t=transform, c=crs: latlon_to_rowcol(lat, lon, t, c),
        )
    return grids


# Grids + calibrated params loaded once at startup, not per-request --
# rasterio file reads don't change between requests. Both fires' grids are
# small enough (a few arrays at a few hundred KB each) to hold in memory
# simultaneously.
_grids = _load_all_grids()
_calibrated_params = _load_calibrated_params()


def _fire_or_404(fire: str) -> str:
    if fire not in FIRE_CONFIGS:
        raise HTTPException(status_code=404, detail=f"unknown fire '{fire}', choose one of {list(FIRE_CONFIGS)}")
    return fire


@app.get("/api/fires")
def list_fires():
    return {
        slug: {"name": cfg.cal_fire_name.title(), "year": cfg.cal_fire_year}
        for slug, cfg in FIRE_CONFIGS.items()
    }


@app.get("/api/meta")
def get_meta(fire: str = Query("soberanes")):
    fire = _fire_or_404(fire)
    path = FRAMES_DIR / fire / "meta.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"no pre-rendered demo for '{fire}' -- run generate_frames.py --fire {fire}")
    return FileResponse(path)


@app.get("/api/perimeter")
def get_perimeter(fire: str = Query("soberanes")):
    fire = _fire_or_404(fire)
    return FileResponse(RAW_DIR / f"{fire}_perimeter.geojson")


class SimulateRequest(BaseModel):
    lat: float
    lon: float
    hours: int = 48
    start_time: str | None = None  # ISO 8601, naive UTC; omit for live current wind
    fire: str = "soberanes"


@app.post("/api/simulate")
def simulate(req: SimulateRequest):
    fire = _fire_or_404(req.fire)
    try:
        return run_click_simulation(
            req.lat, req.lon, req.hours, req.start_time,
            _grids[fire], _calibrated_params,
            wind_station=FIRE_CONFIGS[fire].wind_station,
            default_seed=DEFAULT_SEEDS[fire],
        )
    except SimulationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/simulate/limits")
def simulate_limits():
    return {"min_hours": MIN_HOURS, "max_hours": MAX_HOURS}


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
