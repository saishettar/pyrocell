"""
Phase 5 (generalized in Phase 8 for multiple fires): pre-render a
calibrated simulation as a sequence of transparent PNG map overlays (one
per hour), plus the metadata the frontend needs to place them on a real
Leaflet map and drive a play/scrub timeline.

Rendering server-side to plain PNGs (rather than shipping raw grid data to
the browser and rendering client-side) keeps the frontend to vanilla
Leaflet + a slider -- no WebGL/canvas geospatial rendering code needed, and
the grid is real UTM/Albers-projected data with true lat/lon bounds, so a
Leaflet ImageOverlay placed at those bounds lines up with the basemap
correctly despite the small amount of projection distortion at this AOI's
scale (negligible).

Dolan's demo seed matters: Phase 7 found the calibrated params sit close
to a percolation threshold for Dolan specifically -- most random seeds
"escape" and grow normally, but a naive default (unlucky) seed can
self-extinguish in the first few hours. --seed defaults per-fire to a seed
already known to escape (7 for Soberanes, which always has; 8 for Dolan,
confirmed in Phase 7's cross-validation).

Usage:
    venv/Scripts/python.exe backend/api/generate_frames.py --fire soberanes
    venv/Scripts/python.exe backend/api/generate_frames.py --fire dolan --hours 168 --seed 8
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pyproj
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "simulation"))
from fire_ca import BURNED, BURNING, UNBURNED, run_simulation  # noqa: E402
from fire_config import DOLAN, SOBERANES  # noqa: E402
from soberanes_conditions import (  # noqa: E402
    PROCESSED_DIR, RAW_DIR, SUBSTEPS_PER_HOUR, build_substep_params, cells_to_acres, load_grid,
)

ROOT = Path(__file__).resolve().parents[2]
FRAMES_DIR = ROOT / "data" / "frames"

FIRE_CONFIGS = {"soberanes": SOBERANES, "dolan": DOLAN}
DEFAULT_SEEDS = {"soberanes": 7, "dolan": 8}

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
    parser = argparse.ArgumentParser()
    parser.add_argument("--fire", choices=FIRE_CONFIGS.keys(), default="soberanes")
    parser.add_argument("--hours", type=int, default=168, help="7 days -- long enough to show dramatic growth, short enough to render/scrub quickly")
    parser.add_argument("--seed", type=int, default=None, help="defaults to a known-escaping seed per fire")
    args = parser.parse_args()

    fire = FIRE_CONFIGS[args.fire]
    seed = args.seed if args.seed is not None else DEFAULT_SEEDS[args.fire]
    out_dir = FRAMES_DIR / args.fire

    print(f"[frames] loading real terrain/fuel grid for {args.fire}...")
    elevation_m, fuel_code, transform, crs, cell_size_m, ignite_row, ignite_col = load_grid(
        raw_dir=RAW_DIR / args.fire, ignition_lat=fire.ignition_lat, ignition_lon=fire.ignition_lon,
    )
    # Dolan's demo intentionally reuses the Soberanes calibration -- that's
    # the whole point of Phase 7, and there's no separate "Dolan-calibrated"
    # params file.
    params = load_calibrated_params()
    print(f"[frames] params (Soberanes-calibrated): {params}")

    print(f"[frames] building {args.hours}h wind series + running simulation "
          f"({SUBSTEPS_PER_HOUR}x sub-steps/hour, seed={seed})...")
    params_per_substep = build_substep_params(
        cell_size_m, args.hours, start_time=fire.ignition_time_utc, station=fire.wind_station,
        wind_obs=None, **params,
    )
    n_steps = args.hours * SUBSTEPS_PER_HOUR
    snapshots = run_simulation(
        elevation_m=elevation_m, fuel_code=fuel_code,
        ignition_points=[(ignite_row, ignite_col)],
        params=params_per_substep, n_steps=n_steps, seed=seed,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    for f in out_dir.glob("frame_*.png"):
        f.unlink()

    hours_meta = []
    print(f"[frames] rendering {args.hours + 1} hourly frame PNGs to {out_dir}...")
    for h in range(args.hours + 1):
        state = snapshots[h * SUBSTEPS_PER_HOUR]
        img = render_frame(state)
        img.save(out_dir / f"frame_{h:04d}.png")
        acres = cells_to_acres(int(np.count_nonzero(state != UNBURNED)), cell_size_m)
        hours_meta.append({"hour": h, "acres": round(acres)})

    bounds = grid_bounds_latlon(transform, crs, elevation_m.shape)
    meta = {
        "fire": args.fire,
        "fire_name": fire.cal_fire_name.title(),
        "fire_year": fire.cal_fire_year,
        "bounds": bounds,
        "ignition": {"lat": fire.ignition_lat, "lon": fire.ignition_lon},
        "ignition_time_utc": fire.ignition_time_utc.isoformat(),
        "n_hours": args.hours,
        "hours": hours_meta,
        "params": params,
        "seed": seed,
    }
    with open(out_dir / "meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    print(f"[frames] wrote {args.hours + 1} frames + meta.json to {out_dir}")
    print(f"[frames] bounds: {bounds}")
    print(f"[frames] final: {hours_meta[-1]['acres']:,} acres at hour {args.hours}")


if __name__ == "__main__":
    main()
