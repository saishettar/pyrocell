"""
Phase 5: pre-render the calibrated Soberanes simulation as a sequence of
transparent PNG map overlays (one per hour), plus the metadata the frontend
needs to place them on a real Leaflet map and drive a play/scrub timeline.

Rendering server-side to plain PNGs (rather than shipping raw grid data to
the browser and rendering client-side) keeps the frontend to vanilla
Leaflet + a slider -- no WebGL/canvas geospatial rendering code needed, and
the grid is real UTM/Albers-projected data with true lat/lon bounds, so a
Leaflet ImageOverlay placed at those bounds lines up with the basemap
correctly despite the small amount of projection distortion at this AOI's
scale (~35km across -- negligible).

Usage:
    venv/Scripts/python.exe backend/api/generate_frames.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pyproj
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "simulation"))
from fire_ca import BURNED, BURNING, UNBURNED, run_simulation  # noqa: E402
from soberanes_conditions import (  # noqa: E402
    IGNITION_LAT, IGNITION_LON, PROCESSED_DIR, SUBSTEPS_PER_HOUR,
    build_substep_params, cells_to_acres, load_grid,
)

ROOT = Path(__file__).resolve().parents[2]
FRAMES_DIR = ROOT / "data" / "frames"
RAW_DIR = ROOT / "data" / "raw"

N_HOURS = 168  # 7 days -- long enough to show dramatic growth, short enough to render/scrub quickly

COLOR_BURNING = (255, 100, 0, 210)   # orange
COLOR_BURNED = (60, 20, 10, 190)     # dark ember red


def load_calibrated_params() -> dict:
    path = PROCESSED_DIR / "calibrated_params.txt"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found -- run calibrate.py (Phase 4) first")
    values = {}
    with open(path) as f:
        for line in f:
            k, v = line.strip().split("=")
            values[k] = float(v)
    return values


def grid_bounds_latlon(transform, crs, shape) -> dict:
    """Axis-aligned lat/lon bounding box from the raster's four projected
    corners -- fine at this AOI's scale, where meridian convergence is
    negligible."""
    h, w = shape
    corners_xy = [
        transform * (0, 0), transform * (w, 0),
        transform * (0, h), transform * (w, h),
    ]
    to_wgs84 = pyproj.Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    lons, lats = zip(*[to_wgs84.transform(x, y) for x, y in corners_xy])
    return {"south": min(lats), "north": max(lats), "west": min(lons), "east": max(lons)}


def render_frame(state: np.ndarray) -> Image.Image:
    rgba = np.zeros((*state.shape, 4), dtype=np.uint8)
    rgba[state == BURNING] = COLOR_BURNING
    rgba[state == BURNED] = COLOR_BURNED
    return Image.fromarray(rgba, mode="RGBA")


def main():
    print("[frames] loading real terrain/fuel grid + calibrated params...")
    elevation_m, fuel_code, transform, crs, cell_size_m, ignite_row, ignite_col = load_grid()
    params = load_calibrated_params()
    print(f"[frames] params: {params}")

    print(f"[frames] building {N_HOURS}h wind series + running simulation ({SUBSTEPS_PER_HOUR}x sub-steps/hour)...")
    params_per_substep = build_substep_params(cell_size_m, N_HOURS, wind_obs=None, **params)
    n_steps = N_HOURS * SUBSTEPS_PER_HOUR
    snapshots = run_simulation(
        elevation_m=elevation_m, fuel_code=fuel_code,
        ignition_points=[(ignite_row, ignite_col)],
        params=params_per_substep, n_steps=n_steps, seed=7,
    )

    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    for f in FRAMES_DIR.glob("frame_*.png"):
        f.unlink()

    hours_meta = []
    print(f"[frames] rendering {N_HOURS + 1} hourly frame PNGs...")
    for h in range(N_HOURS + 1):
        state = snapshots[h * SUBSTEPS_PER_HOUR]
        img = render_frame(state)
        img.save(FRAMES_DIR / f"frame_{h:04d}.png")
        acres = cells_to_acres(int(np.count_nonzero(state != UNBURNED)), cell_size_m)
        hours_meta.append({"hour": h, "acres": round(acres)})

    bounds = grid_bounds_latlon(transform, crs, elevation_m.shape)
    meta = {
        "bounds": bounds,
        "ignition": {"lat": IGNITION_LAT, "lon": IGNITION_LON},
        "n_hours": N_HOURS,
        "hours": hours_meta,
        "params": params,
    }
    with open(FRAMES_DIR / "meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    print(f"[frames] wrote {N_HOURS + 1} frames + meta.json to {FRAMES_DIR}")
    print(f"[frames] bounds: {bounds}")
    print(f"[frames] final: {hours_meta[-1]['acres']:,} acres at hour {N_HOURS}")


if __name__ == "__main__":
    main()
