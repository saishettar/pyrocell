"""
Phase 2 sanity check: run the CA on synthetic (not real) terrain/wind/fuel to
confirm the model behaves physically before touching real historical data.

Three scenarios, all starting from a single ignition point at grid center:
  1. flat terrain, no wind        -> should spread ~isotropically
  2. sloped terrain, no wind      -> should spread farther uphill (+x) than downhill
  3. flat terrain, wind from west -> should spread farther downwind (+x) than upwind

Usage:
    venv/Scripts/python.exe backend/simulation/toy_conditions.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from fire_ca import BURNED, BURNING, SimParams, UNBURNED, run_simulation

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "output"

GRID_SIZE = 121
CELL_SIZE_M = 30.0
CENTER = GRID_SIZE // 2
N_STEPS = 40
UNIFORM_FUEL_CODE = 165  # a mid-rate timber-understory class, so slope/wind effects aren't swamped by fuel=1.0 grass


def burned_extent_along_x(final_state: np.ndarray) -> tuple[int, int]:
    """Burned/burning cell count to the west (-x) and east (+x) of center, on the center row."""
    row = final_state[CENTER, :]
    burned = row != UNBURNED
    west = np.count_nonzero(burned[:CENTER])
    east = np.count_nonzero(burned[CENTER + 1:])
    return west, east


def centroid_offset_m(final_state: np.ndarray) -> tuple[float, float]:
    ys, xs = np.nonzero(final_state != UNBURNED)
    if len(xs) == 0:
        return 0.0, 0.0
    dy = (ys.mean() - CENTER) * CELL_SIZE_M
    dx = (xs.mean() - CENTER) * CELL_SIZE_M
    return dy, dx


def run_scenario(elevation_m: np.ndarray, fuel_code: np.ndarray, params: SimParams, seed: int = 42) -> np.ndarray:
    snapshots = run_simulation(
        elevation_m=elevation_m,
        fuel_code=fuel_code,
        ignition_points=[(CENTER, CENTER)],
        params=params,
        n_steps=N_STEPS,
        seed=seed,
    )
    return snapshots[-1]


def mean_extent_over_seeds(
    elevation_m: np.ndarray, fuel_code: np.ndarray, params: SimParams, n_seeds: int = 16
) -> tuple[float, float]:
    """A single stochastic run is noisy (early growth is driven by very few
    burning cells), so symmetry/bias claims need averaging over seeds, not
    an eyeball on one realization."""
    wests, easts = [], []
    for seed in range(n_seeds):
        final_state = run_scenario(elevation_m, fuel_code, params, seed=seed)
        w, e = burned_extent_along_x(final_state)
        wests.append(w)
        easts.append(e)
    return float(np.mean(wests)), float(np.mean(easts))


def main():
    flat_elev = np.zeros((GRID_SIZE, GRID_SIZE), dtype=np.float32)
    uniform_fuel = np.full((GRID_SIZE, GRID_SIZE), UNIFORM_FUEL_CODE, dtype=np.float32)

    # Tilted plane: elevation rises to the east (+x), ~2% grade over the grid.
    xs = np.arange(GRID_SIZE, dtype=np.float32)
    sloped_elev = np.tile(xs * CELL_SIZE_M * 0.30, (GRID_SIZE, 1))

    scenarios = {
        "flat_no_wind": (
            flat_elev,
            SimParams(cell_size_m=CELL_SIZE_M, wind_speed_mps=0.0),
        ),
        "sloped_no_wind": (
            sloped_elev,
            SimParams(cell_size_m=CELL_SIZE_M, wind_speed_mps=0.0),
        ),
        "flat_wind_from_west": (
            flat_elev,
            # wind blowing TOWARD the east (90 deg) pushes fire eastward
            SimParams(cell_size_m=CELL_SIZE_M, wind_speed_mps=6.0, wind_dir_to_deg=90.0),
        ),
    }

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    results = {}
    for ax, (name, (elev, params)) in zip(axes, scenarios.items()):
        final_state = run_scenario(elev, uniform_fuel, params)
        results[name] = final_state

        ax.imshow(final_state, cmap="hot_r", vmin=0, vmax=2)
        ax.plot(CENTER, CENTER, "b+", markersize=12, markeredgewidth=2)
        ax.set_title(name)
        ax.axis("off")

        west, east = burned_extent_along_x(final_state)
        dy, dx = centroid_offset_m(final_state)
        print(f"{name}: west_cells={west} east_cells={east}  centroid_offset=({dy:.1f}m N/S, {dx:.1f}m E/W)")

    fig.suptitle(f"Phase 2 toy-condition sanity check ({N_STEPS} steps, uniform fuel={UNIFORM_FUEL_CODE})")
    fig.tight_layout()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "phase2_toy_conditions.png"
    fig.savefig(out_path, dpi=150)
    print(f"\n[toy conditions] wrote {out_path}")

    # Assertions -- fail loudly if the model doesn't behave physically.
    # A single stochastic realization is noisy, so these average over many
    # seeds rather than trusting the one run plotted above.
    print("\nRunning multi-seed averages for the physical sanity checks...")

    flat_elev, flat_params = scenarios["flat_no_wind"]
    flat_w, flat_e = mean_extent_over_seeds(flat_elev, uniform_fuel, flat_params)
    print(f"flat_no_wind (mean over seeds): west={flat_w:.1f} east={flat_e:.1f}")
    assert abs(flat_w - flat_e) <= 0.25 * max(flat_w, flat_e, 1), (
        f"flat/no-wind case should be roughly symmetric on average, got west={flat_w:.1f} east={flat_e:.1f}"
    )

    slope_elev, slope_params = scenarios["sloped_no_wind"]
    slope_w, slope_e = mean_extent_over_seeds(slope_elev, uniform_fuel, slope_params)
    print(f"sloped_no_wind (mean over seeds): west={slope_w:.1f} east={slope_e:.1f}")
    assert slope_e > slope_w, f"sloped case should spread farther uphill (east): west={slope_w:.1f} east={slope_e:.1f}"

    wind_elev, wind_params = scenarios["flat_wind_from_west"]
    wind_w, wind_e = mean_extent_over_seeds(wind_elev, uniform_fuel, wind_params)
    print(f"flat_wind_from_west (mean over seeds): west={wind_w:.1f} east={wind_e:.1f}")
    assert wind_e > wind_w, f"wind case should spread farther downwind (east): west={wind_w:.1f} east={wind_e:.1f}"

    print("\nAll physical sanity checks passed: symmetric baseline, faster uphill, faster downwind.")


if __name__ == "__main__":
    main()
