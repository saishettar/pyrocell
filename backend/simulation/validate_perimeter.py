"""
Phase 4b: shape validation against the real recorded Soberanes Fire
perimeter (CAL FIRE FRAP historical fire perimeters dataset), via IoU
(intersection-over-union) between the simulated burned mask and the real
final perimeter, rasterized onto the same grid.

Important caveat, stated plainly rather than buried: the real perimeter
took 83 days under active firefighting (containment lines, aircraft
retardant, backburns). This model has no suppression mechanics at all --
it only stops where fuel runs out or terrain/coastline blocks it. So this
IoU is not "how accurate is the physics" in isolation; it's "how well does
unsuppressed natural-spread direction/shape resemble the actual (suppressed)
footprint," which conflates spread physics with three months of firefighting
decisions we don't model. Treat the number as a directional-plausibility
signal, not a validated accuracy claim -- that's the honest framing for a
CA model at this level of simplification.

Usage:
    venv/Scripts/python.exe backend/simulation/validate_perimeter.py [n_hours]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pyproj
import rasterio.features
from shapely.geometry import shape
from shapely.ops import transform as shapely_transform

from fire_ca import UNBURNED, run_simulation
from soberanes_conditions import (
    PROCESSED_DIR, RAW_DIR, SUBSTEPS_PER_HOUR, build_substep_params, cells_to_acres, load_grid,
)

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "output"

DEFAULT_N_HOURS = 24 * 21  # 3 weeks -- long enough to see if the calibrated
                            # rate gets anywhere near the real final footprint,
                            # short of the real 83-day (suppressed) duration


def load_calibrated_params() -> dict:
    path = PROCESSED_DIR / "calibrated_params.txt"
    if not path.exists():
        print("[validate] WARNING: no calibrated_params.txt found -- run calibrate.py first. Using Phase 2 defaults.")
        return dict(base_prob=0.22, k_slope=4.0, k_wind=0.6, burnout_hours=3.0)
    values = {}
    with open(path) as f:
        for line in f:
            k, v = line.strip().split("=")
            values[k] = float(v)
    return values


def rasterize_real_perimeter(transform, crs, out_shape):
    geojson_path = RAW_DIR / "soberanes_perimeter.geojson"
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
    n_hours = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_N_HOURS
    params = load_calibrated_params()
    print(f"[validate] using params: {params}")

    elevation_m, fuel_code, transform, crs, cell_size_m, ignite_row, ignite_col = load_grid()

    print(f"[validate] building {n_hours}h ({n_hours/24:.1f} day) wind series...")
    params_per_substep = build_substep_params(cell_size_m, n_hours, wind_obs=None, **params)

    print(f"[validate] running {n_hours}h simulation ({SUBSTEPS_PER_HOUR}x sub-steps/hour)...")
    n_steps = n_hours * SUBSTEPS_PER_HOUR
    snapshots = run_simulation(
        elevation_m=elevation_m, fuel_code=fuel_code,
        ignition_points=[(ignite_row, ignite_col)],
        params=params_per_substep, n_steps=n_steps, seed=7,
    )
    sim_mask = snapshots[-1] != UNBURNED
    sim_acres = cells_to_acres(int(sim_mask.sum()), cell_size_m)

    print("[validate] rasterizing real final perimeter onto the same grid...")
    real_mask, real_acres_official = rasterize_real_perimeter(transform, crs, elevation_m.shape)
    real_acres_in_grid = cells_to_acres(int(real_mask.sum()), cell_size_m)
    if real_acres_in_grid < 0.9 * real_acres_official:
        print(
            f"[validate] NOTE: real perimeter is {real_acres_official:,.0f} acres officially, but only "
            f"{real_acres_in_grid:,.0f} acres ({real_acres_in_grid/real_acres_official:.0%}) fall inside our "
            f"fetched AOI -- the rest of the real fire extended past our grid's east edge. IoU below is "
            f"computed against the truncated in-grid perimeter, not the true fire extent."
        )

    intersection = np.logical_and(sim_mask, real_mask).sum()
    union = np.logical_or(sim_mask, real_mask).sum()
    iou = intersection / union if union > 0 else 0.0

    print(f"\n[validate] simulated burned area:        {sim_acres:,.0f} acres ({n_hours/24:.1f} days, no suppression)")
    print(f"[validate] real perimeter (in-grid):     {real_acres_in_grid:,.0f} acres (of {real_acres_official:,.0f} official, 83 days, active suppression)")
    print(f"[validate] IoU @ {n_hours/24:.0f}d (size-mismatched):  {iou:.3f} ({iou*100:.1f}%)")

    # Area-matched comparison: find the earliest snapshot whose burned area
    # first reaches the in-grid real acreage, so shape agreement isn't
    # conflated with "the model just kept growing longer than the real fire
    # did in-frame." This is the fairer of the two numbers.
    matched_idx = None
    for idx, s in enumerate(snapshots):
        if cells_to_acres(int(np.count_nonzero(s != UNBURNED)), cell_size_m) >= real_acres_in_grid:
            matched_idx = idx
            break
    if matched_idx is not None:
        matched_mask = snapshots[matched_idx] != UNBURNED
        matched_acres = cells_to_acres(int(matched_mask.sum()), cell_size_m)
        m_intersection = np.logical_and(matched_mask, real_mask).sum()
        m_union = np.logical_or(matched_mask, real_mask).sum()
        iou_matched = m_intersection / m_union if m_union > 0 else 0.0
        matched_hour = matched_idx / SUBSTEPS_PER_HOUR
        print(f"[validate] IoU @ area-matched ({matched_acres:,.0f}ac, ~{matched_hour/24:.1f}d): {iou_matched:.3f} ({iou_matched*100:.1f}%)")
    else:
        iou_matched = None
        matched_mask = None
        print("[validate] simulation never reached the real in-grid acreage within the run duration")

    # Visualize: real perimeter outline vs simulated burned mask (full-duration
    # run, and the area-matched snapshot side by side), cropped to their combined extent.
    combined = sim_mask | real_mask
    ys, xs = np.nonzero(combined)
    pad = 15
    r0, r1 = max(0, ys.min() - pad), min(elevation_m.shape[0], ys.max() + pad)
    c0, c1 = max(0, xs.min() - pad), min(elevation_m.shape[1], xs.max() + pad)

    n_panels = 2 if matched_mask is not None else 1
    fig, axes = plt.subplots(1, n_panels, figsize=(9 * n_panels, 9))
    axes = [axes] if n_panels == 1 else list(axes)

    panels = [(sim_mask, f"full {n_hours/24:.0f}-day run", sim_acres, iou)]
    if matched_mask is not None:
        panels.append((matched_mask, f"area-matched (~{matched_hour/24:.1f}d)", matched_acres, iou_matched))

    for ax, (mask, label, acres, this_iou) in zip(axes, panels):
        ax.imshow(elevation_m[r0:r1, c0:c1], cmap="gray", alpha=0.5)
        overlay = np.zeros((r1 - r0, c1 - c0, 4))
        overlay[mask[r0:r1, c0:c1]] = [1.0, 0.3, 0.0, 0.55]  # orange = simulated
        ax.imshow(overlay)
        ax.contour(real_mask[r0:r1, c0:c1], levels=[0.5], colors="blue", linewidths=2)
        ax.plot(ignite_col - c0, ignite_row - r0, "k+", markersize=14, markeredgewidth=2)
        ax.set_title(f"{label}: sim={acres:,.0f}ac vs real(in-grid)={real_acres_in_grid:,.0f}ac\nIoU={this_iou:.2f}")
        ax.axis("off")

    fig.suptitle(
        "Simulated (orange) vs real final perimeter (blue outline) -- Soberanes Fire\n"
        f"real perimeter took 83 days under active suppression (not modeled); "
        f"{real_acres_in_grid/real_acres_official:.0%} of the {real_acres_official:,.0f}ac official perimeter falls inside our AOI",
        y=1.0,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.88])
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "phase4_perimeter_validation.png"
    fig.savefig(out_path, dpi=150)
    print(f"[validate] wrote {out_path}")


if __name__ == "__main__":
    main()
