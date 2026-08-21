"""
Shared setup for real-fire runs: the real grid, real ignition point, and
real hourly wind, factored out of real_conditions.py so calibrate.py and
validate_perimeter.py don't duplicate it.

Originally Soberanes-only (hence the filename); every function now takes
optional overrides so cross_validate_dolan.py can reuse the same logic for
a second fire without duplicating it. Existing call sites that don't pass
the new params get identical behavior to before -- all defaults still
resolve to Soberanes.
"""
from __future__ import annotations

import csv
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pyproj
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data_pipeline"))
from wind_client import WindObservation, fetch_historical_wind, wind_at_or_before  # noqa: E402

from fire_ca import SimParams  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"

SOBERANES_RAW_DIR = RAW_DIR / "soberanes"

IGNITION_LAT = 36.456429
IGNITION_LON = -121.924016
IGNITION_TIME_UTC = datetime(2016, 7, 22, 15, 48, tzinfo=timezone.utc)
WIND_STATION = "MRY"

ACRE_M2 = 4046.8564224

# A Moore-neighborhood CA can advance at most 1 cell per timestep. At 1
# step = 1 real hour and 60m cells, that's a hard ceiling of 60m/hour
# (~1.4 km/day) radial spread -- too slow to reach real wind-driven fire
# run rates no matter how high base_prob goes (confirmed empirically: the
# Phase 4 calibration search saturated well below the real growth curve
# across the whole base_prob range). Running multiple CA sub-steps per
# real hour, each using that hour's wind reading, raises the effective
# speed ceiling without needing finer wind data than we actually have.
SUBSTEPS_PER_HOUR = 6


def find_bundle_tif(raw_dir: Path = None) -> Path:
    raw_dir = raw_dir or SOBERANES_RAW_DIR
    tifs = list(raw_dir.glob("*.tif"))
    if not tifs:
        raise FileNotFoundError(f"no .tif in {raw_dir} -- run the fetch script for this fire first")
    return tifs[0]


def latlon_to_rowcol(lat: float, lon: float, transform, crs) -> tuple[int, int]:
    transformer = pyproj.Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    x, y = transformer.transform(lon, lat)
    row, col = rasterio.transform.rowcol(transform, x, y)
    return int(row), int(col)


def load_grid(raw_dir: Path = None, ignition_lat: float = None, ignition_lon: float = None):
    """Returns (elevation_m, fuel_code, transform, crs, cell_size_m, ignite_row, ignite_col)."""
    ignition_lat = IGNITION_LAT if ignition_lat is None else ignition_lat
    ignition_lon = IGNITION_LON if ignition_lon is None else ignition_lon

    tif_path = find_bundle_tif(raw_dir)
    with rasterio.open(tif_path) as src:
        elevation_m = src.read(1).astype(np.float32)
        fuel_code = src.read(4).astype(np.float32)
        transform = src.transform
        crs = src.crs
        cell_size_m = abs(transform.a)

    ignite_row, ignite_col = latlon_to_rowcol(ignition_lat, ignition_lon, transform, crs)
    h, w = elevation_m.shape
    if not (0 <= ignite_row < h and 0 <= ignite_col < w):
        raise ValueError(f"ignition point falls outside the fetched grid ({h}x{w})")

    return elevation_m, fuel_code, transform, crs, cell_size_m, ignite_row, ignite_col


def fetch_wind_series(n_hours: int, station: str = None, ignition_time: datetime = None) -> list[WindObservation]:
    station = station or WIND_STATION
    ignition_time = ignition_time or IGNITION_TIME_UTC

    start_date = ignition_time.date()
    end_date = (ignition_time + timedelta(hours=n_hours, days=1)).date()
    cache_path = PROCESSED_DIR / f"wind_{station}_{start_date}_{end_date}.csv"

    if cache_path.exists():
        obs = []
        with open(cache_path) as f:
            for row in csv.DictReader(f):
                obs.append(WindObservation(
                    valid_time=datetime.fromisoformat(row["valid_time"]),
                    dir_from_deg=float(row["dir_from_deg"]) if row["dir_from_deg"] else None,
                    speed_mps=float(row["speed_mps"]) if row["speed_mps"] else None,
                ))
        print(f"[wind] loaded {len(obs)} cached observations from {cache_path}")
    else:
        obs = fetch_historical_wind(station, start_date, end_date)
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["valid_time", "dir_from_deg", "speed_mps"])
            for o in obs:
                writer.writerow([o.valid_time.isoformat(), o.dir_from_deg, o.speed_mps])
        print(f"[wind] fetched {len(obs)} observations from IEM ASOS, cached to {cache_path}")
    return obs


def build_substep_params(
    cell_size_m: float, n_hours: int, base_prob: float, k_slope: float, k_wind: float, burnout_hours: float,
    wind_obs: list[WindObservation] = None, start_time: datetime = None, station: str = None,
) -> list[SimParams]:
    """One SimParams per CA sub-step (SUBSTEPS_PER_HOUR per real hour); each
    hour's wind reading is held constant across its sub-steps. burnout_hours
    is in real hours -- converted to sub-step units internally."""
    start_time = start_time or IGNITION_TIME_UTC
    if start_time.tzinfo:
        start_time = start_time.replace(tzinfo=None)
    obs = wind_obs if wind_obs is not None else fetch_wind_series(n_hours, station=station, ignition_time=start_time)
    burnout_steps = max(1, round(burnout_hours * SUBSTEPS_PER_HOUR))

    params = []
    for h in range(n_hours):
        t = start_time + timedelta(hours=h)
        w = wind_at_or_before(obs, t)
        speed = w.speed_mps or 0.0
        dir_to = w.dir_to_deg if w.dir_to_deg is not None else 0.0
        hour_params = SimParams(
            cell_size_m=cell_size_m,
            base_prob=base_prob,
            k_slope=k_slope,
            k_wind=k_wind,
            burnout_steps=burnout_steps,
            wind_speed_mps=speed,
            wind_dir_to_deg=dir_to,
        )
        params.extend([hour_params] * SUBSTEPS_PER_HOUR)
    return params


def cells_to_acres(n_cells: int, cell_size_m: float) -> float:
    return n_cells * (cell_size_m ** 2) / ACRE_M2
