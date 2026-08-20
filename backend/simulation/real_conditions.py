"""
Phase 3: run the CA on the real Big Sur terrain/fuel grid (Phase 1) with the
real ignition point and real hour-by-hour wind (Phase 2's toy wind was a
single fixed vector; here it actually changes direction overnight the way
real coastal wind does).

Soberanes Fire, 2016-07-22: reported 8:48am PDT (15:48 UTC) in Garrapata
State Park / Soberanes Canyon. Wikipedia's infobox coordinate for this fire
is wrong (it points ~50km inland) -- confirmed against Garrapata SP's actual
published location, used here instead.

This does NOT attempt time/accuracy calibration -- SimParams constants are
still the same rough values from Phase 2's toy conditions. See calibrate.py
and validate_perimeter.py (Phase 4) for that.

Usage:
    venv/Scripts/python.exe backend/simulation/real_conditions.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from fire_ca import UNBURNED, run_simulation
from soberanes_conditions import PROCESSED_DIR, SUBSTEPS_PER_HOUR, build_substep_params, load_grid

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "output"

SIM_HOURS = 48


def plot_progression(snapshots: list[np.ndarray], hours_to_show: list[int], ignite_rc, out_path: Path):
    # Crop to the final burn extent (+ padding) so growth is legible --
    # otherwise a ~65x46 cell fire is an unreadable speck on a 595x602 grid.
    final = snapshots[-1]
    ys, xs = np.nonzero(final != UNBURNED)
    pad = 25
    r0, r1 = max(0, ys.min() - pad), min(final.shape[0], ys.max() + pad)
    c0, c1 = max(0, xs.min() - pad), min(final.shape[1], xs.max() + pad)

    fig, axes = plt.subplots(1, len(hours_to_show), figsize=(4 * len(hours_to_show), 4.5))
    for ax, h in zip(axes, hours_to_show):
        crop = snapshots[h * SUBSTEPS_PER_HOUR][r0:r1, c0:c1]
        ax.imshow(crop, cmap="hot_r", vmin=0, vmax=2)
        ax.plot(ignite_rc[1] - c0, ignite_rc[0] - r0, "b+", markersize=10, markeredgewidth=2)
        ax.set_title(f"hour {h}")
        ax.axis("off")
    fig.suptitle("Soberanes Fire simulation -- real terrain, fuel, and hourly wind (uncalibrated)")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"[real conditions] wrote {out_path}")


def main():
    elevation_m, fuel_code, transform, crs, cell_size_m, ignite_row, ignite_col = load_grid()
    print(f"[grid] shape {elevation_m.shape}, cell size {cell_size_m}m")
    print(f"[ignition] grid cell (row={ignite_row}, col={ignite_col})")

    print(f"\n[wind] building {SIM_HOURS}-hour wind time series...")
    # Phase 2 toy-tuned constants -- see calibrate.py (Phase 4) for the
    # version fit against real fire growth instead of guessed.
    params_per_substep = build_substep_params(
        cell_size_m, SIM_HOURS, base_prob=0.22, k_slope=4.0, k_wind=0.6, burnout_hours=3.0,
    )

    print(f"\n[sim] running {SIM_HOURS}-hour simulation ({SUBSTEPS_PER_HOUR}x sub-steps/hour) from real ignition point...")
    n_steps = SIM_HOURS * SUBSTEPS_PER_HOUR
    snapshots = run_simulation(
        elevation_m=elevation_m,
        fuel_code=fuel_code,
        ignition_points=[(ignite_row, ignite_col)],
        params=params_per_substep,
        n_steps=n_steps,
        seed=7,
    )

    final = snapshots[-1]
    n_burned = int(np.count_nonzero(final != UNBURNED))
    area_km2 = n_burned * (cell_size_m ** 2) / 1e6
    print(f"\n[sim] final: {n_burned} cells burned/burning (~{area_km2:.1f} km^2, uncalibrated)")

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        PROCESSED_DIR / "soberanes_simulation.npz",
        final_state=final,
        ignite_row=ignite_row,
        ignite_col=ignite_col,
    )
    print(f"[sim] saved final state to {PROCESSED_DIR / 'soberanes_simulation.npz'}")

    hours_to_show = [0, 6, 12, 24, 36, 48]
    plot_progression(snapshots, hours_to_show, (ignite_row, ignite_col), OUTPUT_DIR / "phase3_real_conditions.png")


if __name__ == "__main__":
    main()
