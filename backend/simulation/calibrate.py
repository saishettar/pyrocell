"""
Phase 4a: calibrate SimParams against real documented fire growth.

Phase 2/3 used arbitrary constants (base_prob=0.22, k_slope=4.0, k_wind=0.6)
tuned only so toy scenarios pointed the right direction. Here we fit
base_prob (holding k_slope/k_wind fixed -- one free parameter keeps the
search tractable and avoids overfitting three noisy checkpoints with three
knobs) against real reported acreage milestones for the Soberanes Fire's
first ~3 days, before containment efforts had much effect:

  t=24h (2016-07-23 AM): ~2,000 acres
  t=40h (2016-07-24 AM): ~10,000 acres
  t=65h (2016-07-25):     14,897 acres, 5% contained

Sources: Monterey County Weekly / local news incident coverage archived at
montereycountynow.com, see README.

Usage:
    venv/Scripts/python.exe backend/simulation/calibrate.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from fire_ca import UNBURNED, run_simulation
from soberanes_conditions import (
    PROCESSED_DIR, SUBSTEPS_PER_HOUR, build_substep_params, cells_to_acres, fetch_wind_series, load_grid,
)

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "output"

CHECKPOINTS_HOURS = [24, 40, 65]
CHECKPOINTS_ACRES = [2000, 10000, 14897]
N_HOURS = 65

K_SLOPE = 4.0
K_WIND = 0.6
BURNOUT_HOURS = 3.0

# Coarse-to-fine search over the one free parameter.
CANDIDATE_BASE_PROBS = [0.040, 0.043, 0.046, 0.048, 0.050, 0.052, 0.055, 0.058, 0.062]


def run_and_get_area_series(elevation_m, fuel_code, ignite_rc, cell_size_m, base_prob, wind_obs, seed=7):
    params = build_substep_params(
        cell_size_m, N_HOURS, base_prob=base_prob, k_slope=K_SLOPE, k_wind=K_WIND,
        burnout_hours=BURNOUT_HOURS, wind_obs=wind_obs,
    )
    n_steps = N_HOURS * SUBSTEPS_PER_HOUR
    snapshots = run_simulation(
        elevation_m=elevation_m, fuel_code=fuel_code, ignition_points=[ignite_rc],
        params=params, n_steps=n_steps, seed=seed,
    )
    # snapshots has one entry per sub-step; sample at hour boundaries.
    acres_per_hour = [
        cells_to_acres(int(np.count_nonzero(snapshots[h * SUBSTEPS_PER_HOUR] != UNBURNED)), cell_size_m)
        for h in range(N_HOURS + 1)
    ]
    return acres_per_hour


def fit_error(acres_per_hour: list[float]) -> float:
    """Sum of squared relative errors at the checkpoints."""
    err = 0.0
    for h, target_acres in zip(CHECKPOINTS_HOURS, CHECKPOINTS_ACRES):
        sim_acres = acres_per_hour[h]
        rel_err = (sim_acres - target_acres) / target_acres
        err += rel_err ** 2
    return err


def main():
    print("[calibrate] loading real terrain/fuel grid + ignition point...")
    elevation_m, fuel_code, transform, crs, cell_size_m, ignite_row, ignite_col = load_grid()
    print(f"[calibrate] fetching {N_HOURS}h of real wind...")
    wind_obs = fetch_wind_series(N_HOURS)

    results = {}
    print(f"\n[calibrate] searching base_prob over {CANDIDATE_BASE_PROBS}...")
    for bp in CANDIDATE_BASE_PROBS:
        acres_per_hour = run_and_get_area_series(
            elevation_m, fuel_code, (ignite_row, ignite_col), cell_size_m, bp, wind_obs,
        )
        err = fit_error(acres_per_hour)
        results[bp] = (acres_per_hour, err)
        checkpoint_vals = [f"{acres_per_hour[h]:.0f}ac@{h}h" for h in CHECKPOINTS_HOURS]
        print(f"  base_prob={bp:.2f}: {', '.join(checkpoint_vals)}  sq_rel_err={err:.3f}")

    best_bp = min(results, key=lambda bp: results[bp][1])
    best_acres_per_hour, best_err = results[best_bp]
    print(f"\n[calibrate] best fit: base_prob={best_bp} (sq_rel_err={best_err:.3f})")

    # Plot: simulated growth curve for a few candidates + real checkpoints.
    fig, ax = plt.subplots(figsize=(9, 6))
    hours = np.arange(N_HOURS + 1)
    for bp in CANDIDATE_BASE_PROBS:
        acres_per_hour, _ = results[bp]
        style = "-" if bp == best_bp else "--"
        alpha = 1.0 if bp == best_bp else 0.35
        lw = 2.5 if bp == best_bp else 1.0
        ax.plot(hours, acres_per_hour, style, alpha=alpha, lw=lw, label=f"base_prob={bp:.2f}" + (" (best fit)" if bp == best_bp else ""))
    ax.scatter(CHECKPOINTS_HOURS, CHECKPOINTS_ACRES, color="red", zorder=5, s=60, label="real reported acreage")
    ax.set_xlabel("hours since ignition")
    ax.set_ylabel("cumulative burned area (acres)")
    ax.set_title("Phase 4: calibrating base_prob against real Soberanes Fire growth")
    ax.legend(fontsize=8)
    fig.tight_layout()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "phase4_calibration.png"
    fig.savefig(out_path, dpi=150)
    print(f"[calibrate] wrote {out_path}")

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    with open(PROCESSED_DIR / "calibrated_params.txt", "w") as f:
        f.write(f"base_prob={best_bp}\nk_slope={K_SLOPE}\nk_wind={K_WIND}\nburnout_hours={BURNOUT_HOURS}\n")
    print(f"[calibrate] saved calibrated params to {PROCESSED_DIR / 'calibrated_params.txt'}")


if __name__ == "__main__":
    main()
