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
still the same rough values from Phase 2's toy conditions. Comparing this
run's spread against the real recorded fire perimeter (Phase 4, via IoU) is
what calibration is for.

Usage:
    venv/Scripts/python.exe backend/simulation/real_conditions.py
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pyproj
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data_pipeline"))
from wind_client import fetch_historical_wind, wind_at_or_before  # noqa: E402

from fire_ca import BURNED, BURNING, SimParams, UNBURNED, run_simulation  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
OUTPUT_DIR = ROOT / "output"

IGNITION_LAT = 36.456429
IGNITION_LON = -121.924016
IGNITION_TIME_UTC = datetime(2016, 7, 22, 15, 48, tzinfo=timezone.utc)
SIM_HOURS = 48

WIND_STATION = "MRY"  # Monterey Regional Airport -- nearest ASOS with deep historical archive


def find_bundle_tif() -> Path:
    tifs = list(RAW_DIR.glob("*.tif"))
    if not tifs:
        raise FileNotFoundError(f"no .tif in {RAW_DIR} -- run fetch_bigsur.py first")
    return tifs[0]


def latlon_to_rowcol(lat: float, lon: float, transform, crs) -> tuple[int, int]:
    transformer = pyproj.Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    x, y = transformer.transform(lon, lat)
    row, col = rasterio.transform.rowcol(transform, x, y)
    return int(row), int(col)


def build_hourly_params(cell_size_m: float) -> list[SimParams]:
    start_date = IGNITION_TIME_UTC.date()
    # IEM's day2 bound is exclusive of the day itself (stops at 00:00 UTC on
    # that date), so pad by an extra day to make sure the full SIM_HOURS
    # window actually has real observations rather than silently holding
    # the last known value past the fetched range.
    end_date = (IGNITION_TIME_UTC + timedelta(hours=SIM_HOURS, days=1)).date()
    cache_path = PROCESSED_DIR / f"wind_{WIND_STATION}_{start_date}_{end_date}.csv"

    if cache_path.exists():
        import csv
        obs = []
        from wind_client import WindObservation
        with open(cache_path) as f:
            for row in csv.DictReader(f):
                obs.append(WindObservation(
                    valid_time=datetime.fromisoformat(row["valid_time"]),
                    dir_from_deg=float(row["dir_from_deg"]) if row["dir_from_deg"] else None,
                    speed_mps=float(row["speed_mps"]) if row["speed_mps"] else None,
                ))
        print(f"[wind] loaded {len(obs)} cached observations from {cache_path}")
    else:
        obs = fetch_historical_wind(WIND_STATION, start_date, end_date)
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        import csv
        with open(cache_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["valid_time", "dir_from_deg", "speed_mps"])
            for o in obs:
                writer.writerow([o.valid_time.isoformat(), o.dir_from_deg, o.speed_mps])
        print(f"[wind] fetched {len(obs)} observations from IEM ASOS, cached to {cache_path}")

    params_per_hour = []
    for h in range(SIM_HOURS):
        t = IGNITION_TIME_UTC.replace(tzinfo=None) + timedelta(hours=h)
        w = wind_at_or_before(obs, t)
        speed = w.speed_mps or 0.0
        dir_to = w.dir_to_deg if w.dir_to_deg is not None else 0.0
        params_per_hour.append(SimParams(
            cell_size_m=cell_size_m,
            wind_speed_mps=speed,
            wind_dir_to_deg=dir_to,
        ))
        print(f"  hour {h:2d} ({t}Z): wind {speed:.1f} m/s toward {dir_to:.0f} deg")
    return params_per_hour


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
        crop = snapshots[h][r0:r1, c0:c1]
        ax.imshow(crop, cmap="hot_r", vmin=0, vmax=2)
        ax.plot(ignite_rc[1] - c0, ignite_rc[0] - r0, "b+", markersize=10, markeredgewidth=2)
        ax.set_title(f"hour {h}")
        ax.axis("off")
    fig.suptitle("Soberanes Fire simulation -- real terrain, fuel, and hourly wind (uncalibrated)")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"[real conditions] wrote {out_path}")


def main():
    tif_path = find_bundle_tif()
    with rasterio.open(tif_path) as src:
        elevation_m = src.read(1).astype(np.float32)
        fuel_code = src.read(4).astype(np.float32)
        transform = src.transform
        crs = src.crs
        cell_size_m = abs(transform.a)

    ignite_row, ignite_col = latlon_to_rowcol(IGNITION_LAT, IGNITION_LON, transform, crs)
    print(f"[grid] shape {elevation_m.shape}, cell size {cell_size_m}m")
    print(f"[ignition] ({IGNITION_LAT}, {IGNITION_LON}) -> grid cell (row={ignite_row}, col={ignite_col})")

    h, w = elevation_m.shape
    if not (0 <= ignite_row < h and 0 <= ignite_col < w):
        raise ValueError(
            f"ignition point falls outside the fetched grid ({h}x{w}) -- AOI in fetch_bigsur.py needs to be wider"
        )

    print(f"\n[wind] building {SIM_HOURS}-hour wind time series from station {WIND_STATION}...")
    params_per_hour = build_hourly_params(cell_size_m)

    print(f"\n[sim] running {SIM_HOURS}-hour simulation from real ignition point...")
    snapshots = run_simulation(
        elevation_m=elevation_m,
        fuel_code=fuel_code,
        ignition_points=[(ignite_row, ignite_col)],
        params=params_per_hour,
        n_steps=SIM_HOURS,
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
