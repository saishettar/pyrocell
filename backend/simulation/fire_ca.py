"""
Core cellular-automaton fire spread model.

Not the full Rothermel (1972) rate-of-spread equations -- those need fuel
particle geometry, heat content, bulk density, and moisture-of-extinction
terms we don't have clean rasters for yet. Instead each unburned cell gets a
per-neighbor ignition probability each timestep, built from three
multiplicative factors on top of a fuel base rate:

  p = base_prob * fuel_factor(neighbor's fuel) * slope_factor(dir) * wind_factor(dir)

- fuel_factor:  relative spread rate by Scott & Burgan FBFM40 class bucket
                (grass fastest, timber litter slowest, non-burnable = 0)
- slope_factor: exp(k_slope * gradient), gradient = rise/run toward the
                neighbor -- uphill accelerates, downhill decelerates
- wind_factor:  exp(k_wind * wind_speed * cos(angle between spread
                direction and downwind direction)) -- this is the standard
                simplified wind term used in CA fire-spread literature
                (e.g. Alexandridis et al. 2008); max at dead downwind,
                min at dead upwind, neutral crosswind

A cell can be pushed by multiple burning neighbors at once; those
probabilities combine as an independent-trials OR:
  P(ignite) = 1 - prod(1 - p_i)

Everything is vectorized over the whole grid per timestep -- no
cell-by-cell Python loops.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

UNBURNED = np.uint8(0)
BURNING = np.uint8(1)
BURNED = np.uint8(2)

# (row_offset, col_offset, compass_degrees_from_center_to_neighbor, distance_factor)
# Row increases southward (standard north-up raster), so -1 row = north.
_SQRT2 = math.sqrt(2)
NEIGHBOR_OFFSETS = [
    (-1, 0, 0.0, 1.0),      # N
    (-1, 1, 45.0, _SQRT2),  # NE
    (0, 1, 90.0, 1.0),      # E
    (1, 1, 135.0, _SQRT2),  # SE
    (1, 0, 180.0, 1.0),     # S
    (1, -1, 225.0, _SQRT2), # SW
    (0, -1, 270.0, 1.0),    # W
    (-1, -1, 315.0, _SQRT2),# NW
]

# Coarse relative spread-rate bucket by FBFM40 hundred/ten group. This is a
# simplification of Scott & Burgan (2005) fuel model groupings, not a
# literal rate-of-spread value -- grass carries fire fastest (flashy, low
# fuel load), timber litter slowest (compact, shaded, slow-drying).
def fuel_spread_rate(fuel_code: np.ndarray) -> np.ndarray:
    # Default is non-burnable, not a generic "burnable" fallback -- this
    # also covers LANDFIRE nodata (-9999, e.g. open ocean beyond its
    # coverage extent) and any unrecognized code safely. An earlier version
    # defaulted unmatched codes to 0.3 (moderately burnable), which silently
    # treated nodata as real fuel; that never showed up against the
    # Soberanes AOI (its ocean cells are real LANDFIRE code 98, not nodata)
    # but did against Dolan's, whose AOI reaches open water outside
    # LANDFIRE's coverage. Found via cross-validation, not by inspection.
    code = np.asarray(fuel_code)
    rate = np.zeros(code.shape, dtype=np.float32)
    rate = np.where((code >= 100) & (code < 110), 1.0, rate)    # grass
    rate = np.where((code >= 120) & (code < 130), 0.85, rate)   # grass-shrub
    rate = np.where((code >= 140) & (code < 150), 0.7, rate)    # shrub/chaparral
    rate = np.where((code >= 160) & (code < 170), 0.45, rate)   # timber-understory
    rate = np.where((code >= 180) & (code < 190), 0.25, rate)   # timber litter
    rate = np.where((code >= 200) & (code < 210), 0.55, rate)   # slash-blowdown
    return rate


def _shift(a: np.ndarray, dy: int, dx: int, fill) -> np.ndarray:
    """out[i, j] = a[i + dy, j + dx] where in-bounds, else `fill`."""
    h, w = a.shape
    out = np.full_like(a, fill)

    a_rows = slice(dy, h) if dy >= 0 else slice(0, h + dy)
    o_rows = slice(0, h - dy) if dy >= 0 else slice(-dy, h)
    a_cols = slice(dx, w) if dx >= 0 else slice(0, w + dx)
    o_cols = slice(0, w - dx) if dx >= 0 else slice(-dx, w)

    out[o_rows, o_cols] = a[a_rows, a_cols]
    return out


@dataclass
class SimParams:
    cell_size_m: float
    base_prob: float = 0.22       # per-neighbor ignition probability at baseline (flat, no wind, rate=1 fuel)
    k_slope: float = 4.0          # slope sensitivity
    k_wind: float = 0.6           # wind sensitivity (per m/s)
    burnout_steps: int = 3        # timesteps a cell stays BURNING before becoming BURNED
    wind_speed_mps: float = 0.0
    wind_dir_to_deg: float = 0.0  # compass degrees the wind is blowing TOWARD (0=N, 90=E)


@dataclass
class FireGrid:
    elevation_m: np.ndarray
    fuel_code: np.ndarray
    state: np.ndarray = field(init=False)
    time_burning: np.ndarray = field(init=False)

    def __post_init__(self):
        shape = self.elevation_m.shape
        self.state = np.full(shape, UNBURNED, dtype=np.uint8)
        self.time_burning = np.zeros(shape, dtype=np.int32)
        self._fuel_rate = fuel_spread_rate(self.fuel_code)

    def ignite(self, row: int, col: int):
        self.state[row, col] = BURNING

    def step(self, params: SimParams, rng: np.random.Generator):
        is_burning = self.state == BURNING
        is_unburned = self.state == UNBURNED

        p_no_ignite = np.ones_like(self.elevation_m, dtype=np.float32)

        for dy, dx, deg_to_neighbor, dist_factor in NEIGHBOR_OFFSETS:
            neighbor_is_burning = _shift(is_burning, dy, dx, fill=False)
            if not neighbor_is_burning.any():
                continue

            elev_neighbor = _shift(self.elevation_m, dy, dx, fill=np.nan)
            run = dist_factor * params.cell_size_m
            gradient = (self.elevation_m - elev_neighbor) / run  # >0 => center is uphill from neighbor
            gradient = np.nan_to_num(gradient, nan=0.0)
            # A cell bordering NODATA (e.g. LANDFIRE's -9999 fill just past
            # its ocean coverage extent) produces a nonsense multi-hundred-
            # unit "gradient" against a real neighbor. That cell always has
            # fuel_rate=0 so it can never ignite regardless, but clip before
            # exp() anyway rather than relying on downstream zeroing to mask
            # an overflow -> inf -> 0*inf -> NaN chain.
            slope_factor = np.exp(np.clip(params.k_slope * gradient, -50.0, 50.0))

            # Fire travels FROM the neighbor INTO this cell, i.e. opposite
            # of the center->neighbor compass bearing.
            spread_deg = (deg_to_neighbor + 180.0) % 360.0
            angle_diff = math.radians(spread_deg - params.wind_dir_to_deg)
            wind_factor = math.exp(params.k_wind * params.wind_speed_mps * math.cos(angle_diff))

            p_dir = params.base_prob * self._fuel_rate * slope_factor * wind_factor
            p_dir = np.clip(p_dir, 0.0, 1.0)
            p_dir = np.where(neighbor_is_burning, p_dir, 0.0)

            p_no_ignite *= (1.0 - p_dir)

        p_ignite = 1.0 - p_no_ignite
        p_ignite = np.where(self._fuel_rate > 0, p_ignite, 0.0)

        roll = rng.random(self.state.shape)
        newly_ignited = is_unburned & (roll < p_ignite)
        self.state[newly_ignited] = BURNING

        self.time_burning[is_burning] += 1
        burned_out = is_burning & (self.time_burning >= params.burnout_steps)
        self.state[burned_out] = BURNED


def run_simulation(
    elevation_m: np.ndarray,
    fuel_code: np.ndarray,
    ignition_points: list[tuple[int, int]],
    params: SimParams | list[SimParams],
    n_steps: int,
    seed: int = 0,
) -> list[np.ndarray]:
    """Returns a list of state-grid snapshots, one per timestep (including t=0).

    `params` can be a single SimParams (held constant, e.g. for toy
    conditions) or a list of one SimParams per step -- used to drive the
    simulation with real hour-by-hour wind observations, where speed/
    direction change but slope/fuel-sensitivity constants stay fixed.
    """
    grid = FireGrid(elevation_m=elevation_m, fuel_code=fuel_code)
    for row, col in ignition_points:
        grid.ignite(row, col)

    if isinstance(params, list):
        assert len(params) == n_steps, f"expected {n_steps} per-step params, got {len(params)}"
        params_per_step = params
    else:
        params_per_step = [params] * n_steps

    rng = np.random.default_rng(seed)
    snapshots = [grid.state.copy()]
    for step_params in params_per_step:
        grid.step(step_params, rng)
        snapshots.append(grid.state.copy())
    return snapshots
