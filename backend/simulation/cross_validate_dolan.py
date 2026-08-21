"""
Phase 7: cross-validate the Soberanes-calibrated model against a second,
independent fire (2020 Dolan Fire) WITHOUT refitting base_prob/k_slope/
k_wind/burnout_hours. The whole point is to answer "did we just curve-fit
one fire?" -- so this script deliberately does not touch calibrate.py's
output; it only consumes it.

Multi-seed, not single-seed: a first single-seed pass (seed=7) came back
as a total flatline -- burning cells hit zero at hour 14 and never
recovered. That looked like a bug at first, but it isn't one: BURNED is a
terminal state, so a probabilistic CA with a finite burnout window can
genuinely go stochastically extinct before it "catches", the same way some
real small ignitions fizzle out without becoming a big fire. A 16-seed
screen at 48h confirmed this: seed 7 was just the unlucky 1-in-16 draw --
15/16 seeds escape and grow normally. Reporting a single unlucky seed as
"the" cross-validation result would have been misleading, so this script
runs several seeds and reports the escape rate plus the IoU distribution
across escaped runs, the same Monte-Carlo-over-eyeballing discipline used
for the Phase 2 toy-condition checks.

Usage:
    venv/Scripts/python.exe backend/simulation/cross_validate_dolan.py
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pyproj
import rasterio.features
from shapely.geometry import shape
from shapely.ops import transform as shapely_transform

from fire_ca import BURNING, FireGrid, UNBURNED, run_simulation
from fire_config import DOLAN
from soberanes_conditions import PROCESSED_DIR, RAW_DIR, SUBSTEPS_PER_HOUR, build_substep_params, cells_to_acres, load_grid

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "output"
DOLAN_RAW_DIR = RAW_DIR / "dolan"

SCREEN_HOURS = 48
SCREEN_SEEDS = list(range(16))
FULL_HOURS = 24 * 21  # match Soberanes Phase 4b's 3-week run for a fair comparison
FULL_SEEDS = [0, 2, 3, 7, 8]  # spans the range seen in the 48h screen, including the one extinct seed


def load_calibrated_params() -> dict:
    path = PROCESSED_DIR / "calibrated_params.txt"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing -- run calibrate.py first (Soberanes calibration, not refit here)")
    values = {}
    with open(path) as f:
        for line in f:
            k, v = line.strip().split("=")
            values[k] = float(v)
    return values


def rasterize_real_perimeter(transform, crs, out_shape):
    geojson_path = DOLAN_RAW_DIR.parent / "dolan_perimeter.geojson"
    with open(geojson_path) as f:
        data = json.load(f)
    props = data["features"][0]["properties"]
    geom_4326 = shape(data["features"][0]["geometry"])
    to_grid_crs = pyproj.Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform
    geom_grid_crs = shapely_transform(to_grid_crs, geom_4326)
    mask = rasterio.features.rasterize(
        [(geom_grid_crs, 1)], out_shape=out_shape, transform=transform, fill=0, dtype=np.uint8,
    )
    return mask.astype(bool), props["GIS_ACRES"]


def main():
    params = load_calibrated_params()
    print(f"[dolan] using Soberanes-calibrated params UNCHANGED: {params}")

    elevation_m, fuel_code, transform, crs, cell_size_m, ignite_row, ignite_col = load_grid(
        raw_dir=DOLAN_RAW_DIR, ignition_lat=DOLAN.ignition_lat, ignition_lon=DOLAN.ignition_lon,
    )
    print(f"[dolan] grid shape {elevation_m.shape}, ignition cell (row={ignite_row}, col={ignite_col})")

    real_mask, real_acres_official = rasterize_real_perimeter(transform, crs, elevation_m.shape)
    real_acres_in_grid = cells_to_acres(int(real_mask.sum()), cell_size_m)
    print(f"[dolan] real perimeter: {real_acres_official:,.0f}ac officially, "
          f"{real_acres_in_grid:,.0f}ac ({real_acres_in_grid/real_acres_official:.0%}) inside our AOI\n")

    # --- Stage 1: cheap 48h screen across many seeds for the escape/extinction rate ---
    print(f"[dolan] screening {len(SCREEN_SEEDS)} seeds at {SCREEN_HOURS}h for escape vs stochastic extinction...")
    screen_params = build_substep_params(
        cell_size_m, SCREEN_HOURS, start_time=DOLAN.ignition_time_utc, station=DOLAN.wind_station, **params,
    )
    n_escaped = 0
    for seed in SCREEN_SEEDS:
        grid = FireGrid(elevation_m=elevation_m, fuel_code=fuel_code)
        grid.ignite(ignite_row, ignite_col)
        rng = np.random.default_rng(seed)
        for p in screen_params:
            grid.step(p, rng)
        escaped = np.count_nonzero(grid.state == BURNING) > 0
        n_escaped += escaped
    print(f"[dolan] escape rate: {n_escaped}/{len(SCREEN_SEEDS)} seeds still burning at {SCREEN_HOURS}h "
          f"({n_escaped/len(SCREEN_SEEDS):.0%}) -- the rest went stochastically extinct, not a bug\n")

    # --- Stage 2: full-duration runs for a handful of seeds, IoU per seed ---
    print(f"[dolan] running {len(FULL_SEEDS)} seeds at full {FULL_HOURS}h ({FULL_HOURS/24:.0f}d) duration...")
    full_params = build_substep_params(
        cell_size_m, FULL_HOURS, start_time=DOLAN.ignition_time_utc, station=DOLAN.wind_station, **params,
    )
    n_steps = FULL_HOURS * SUBSTEPS_PER_HOUR

    seed_results = []  # (seed, sim_mask, acres, iou, escaped)
    for seed in FULL_SEEDS:
        snapshots = run_simulation(
            elevation_m=elevation_m, fuel_code=fuel_code, ignition_points=[(ignite_row, ignite_col)],
            params=full_params, n_steps=n_steps, seed=seed,
        )
        sim_mask = snapshots[-1] != UNBURNED
        acres = cells_to_acres(int(sim_mask.sum()), cell_size_m)
        iou = np.logical_and(sim_mask, real_mask).sum() / np.logical_or(sim_mask, real_mask).sum()
        escaped = acres > 1000  # extinct runs stall in the tens of acres; escaped runs reach thousands+
        seed_results.append((seed, sim_mask, acres, iou, escaped))
        tag = "escaped" if escaped else "EXTINCT"
        print(f"  seed {seed}: {tag:8s} final={acres:,.0f}ac  IoU={iou:.3f}")

    escaped_results = [r for r in seed_results if r[4]]
    ious = [r[3] for r in escaped_results]
    print(f"\n[dolan] among escaped seeds: IoU mean={np.mean(ious):.3f}, range=[{min(ious):.3f}, {max(ious):.3f}]")
    print(f"[dolan] for comparison, Soberanes' own (calibrated-on) validation IoU was ~0.24 (Phase 4b, area-matched)")

    # Plot: one representative escaped seed (closest to the mean IoU) alongside the real perimeter.
    mean_iou = np.mean(ious)
    seed, sim_mask, acres, iou, _ = min(escaped_results, key=lambda r: abs(r[3] - mean_iou))

    combined = sim_mask | real_mask
    ys, xs = np.nonzero(combined)
    pad = 15
    r0, r1 = max(0, ys.min() - pad), min(elevation_m.shape[0], ys.max() + pad)
    c0, c1 = max(0, xs.min() - pad), min(elevation_m.shape[1], xs.max() + pad)

    fig, ax = plt.subplots(figsize=(11, 9.5))
    ax.imshow(elevation_m[r0:r1, c0:c1], cmap="gray", alpha=0.5)
    overlay = np.zeros((r1 - r0, c1 - c0, 4))
    overlay[sim_mask[r0:r1, c0:c1]] = [1.0, 0.3, 0.0, 0.55]
    ax.imshow(overlay)
    ax.contour(real_mask[r0:r1, c0:c1], levels=[0.5], colors="blue", linewidths=2)
    ax.plot(ignite_col - c0, ignite_row - r0, "k+", markersize=14, markeredgewidth=2)
    ax.set_title(
        f"Dolan Fire cross-validation (seed {seed}, closest to mean IoU): sim={acres:,.0f}ac vs "
        f"real(in-grid)={real_acres_in_grid:,.0f}ac, IoU={iou:.2f}"
    )
    ax.axis("off")
    fig.suptitle(
        f"Cross-validation: Dolan Fire (2020), Soberanes-calibrated params NOT refit\n"
        f"escape rate {n_escaped}/{len(SCREEN_SEEDS)}, mean IoU {mean_iou:.2f} across escaped seeds "
        f"(real perimeter took ~4.5mo under active suppression, not modeled)",
        fontsize=11, y=1.0,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.90])
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "phase7_dolan_cross_validation.png"
    fig.savefig(out_path, dpi=150)
    print(f"\n[dolan] wrote {out_path}")


if __name__ == "__main__":
    main()
