"""
Phase 5: serves the pre-rendered frame PNGs + metadata to the Leaflet
frontend. Deliberately thin -- no simulation runs at request time yet
(that's Phase 6, click-to-simulate); this just serves what generate_frames.py
already computed.

Usage:
    venv/Scripts/python.exe -m uvicorn backend.api.main:app --reload --port 8000
(run from the repo root so the "backend" package path resolves)
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[2]
FRAMES_DIR = ROOT / "data" / "frames"
RAW_DIR = ROOT / "data" / "raw"
FRONTEND_DIR = ROOT / "frontend"

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


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
