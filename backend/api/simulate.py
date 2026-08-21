"""
Phase 6: on-demand simulation for an arbitrary point (within the fetched
Big Sur AOI) and start time, chosen by clicking the map.

Wind source depends on whether a historical start time was given:
- historical: real hourly observations from the same IEM/ASOS archive used
  for Soberanes (station MRY -- the only nearby station we've validated;
  a click far from Monterey will use a less locally-representative wind
  reading, and that's stated in the API response, not hidden).
- live (no start time given): NOAA's public forecastHourly API
  (api.weather.gov), which needs no auth beyond a descriptive User-Agent.

Frames are returned as base64 PNG data URIs in the JSON response rather
than written to disk -- keeps this endpoint stateless (no per-request temp
files to clean up, no shared-directory races between concurrent demo
users).
"""
from __future__ import annotations

import base64
import io
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "simulation"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data_pipeline"))
from fire_ca import SimParams, UNBURNED, run_simulation  # noqa: E402
from soberanes_conditions import SUBSTEPS_PER_HOUR, cells_to_acres  # noqa: E402
from wind_client import WindObservation, fetch_historical_wind, wind_at_or_before  # noqa: E402
from generate_frames import render_frame  # noqa: E402

USER_AGENT = "pyrocell-demo (github.com/saishettar/pyrocell)"

MAX_HOURS = 96
MIN_HOURS = 6

COMPASS_TO_DEG = {
    "N": 0, "NNE": 22.5, "NE": 45, "ENE": 67.5, "E": 90, "ESE": 112.5, "SE": 135, "SSE": 157.5,
    "S": 180, "SSW": 202.5, "SW": 225, "WSW": 247.5, "W": 270, "WNW": 292.5, "NW": 315, "NNW": 337.5,
}


class SimulationError(ValueError):
    pass


def fetch_live_wind(lat: float, lon: float) -> list[WindObservation]:
    headers = {"User-Agent": USER_AGENT}
    points_resp = requests.get(f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}", headers=headers, timeout=15)
    points_resp.raise_for_status()
    forecast_url = points_resp.json()["properties"]["forecastHourly"]

    forecast_resp = requests.get(forecast_url, headers=headers, timeout=15)
    forecast_resp.raise_for_status()
    periods = forecast_resp.json()["properties"]["periods"]

    obs = []
    for p in periods:
        start = datetime.fromisoformat(p["startTime"]).astimezone(timezone.utc).replace(tzinfo=None)
        dir_from = COMPASS_TO_DEG.get(p.get("windDirection", ""))
        speeds = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", p.get("windSpeed", ""))]
        speed_mph = sum(speeds) / len(speeds) if speeds else None
        speed_mps = speed_mph * 0.44704 if speed_mph is not None else None
        obs.append(WindObservation(valid_time=start, dir_from_deg=dir_from, speed_mps=speed_mps))
    if not obs:
        raise SimulationError("NOAA forecastHourly returned no periods")
    return obs


def fetch_wind_for_request(
    lat: float, lon: float, start_time: datetime | None, n_hours: int, station: str,
) -> tuple[list[WindObservation], str, datetime]:
    if start_time is not None:
        end_date = (start_time + timedelta(hours=n_hours, days=1)).date()
        obs = fetch_historical_wind(station, start_time.date(), end_date)
        if not obs:
            raise SimulationError(f"no historical wind data for {start_time.date()} at station {station}")
        return obs, f"historical (station {station}, {start_time.date()})", start_time
    else:
        now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0, second=0)
        obs = fetch_live_wind(lat, lon)
        return obs, "live (NOAA forecastHourly)", now


def build_params(cell_size_m, n_hours, start_time, obs, base_prob, k_slope, k_wind, burnout_hours):
    burnout_steps = max(1, round(burnout_hours * SUBSTEPS_PER_HOUR))
    params = []
    for h in range(n_hours):
        t = start_time + timedelta(hours=h)
        w = wind_at_or_before(obs, t)
        speed = w.speed_mps or 0.0
        dir_to = w.dir_to_deg if w.dir_to_deg is not None else 0.0
        hour_params = SimParams(
            cell_size_m=cell_size_m, base_prob=base_prob, k_slope=k_slope, k_wind=k_wind,
            burnout_steps=burnout_steps, wind_speed_mps=speed, wind_dir_to_deg=dir_to,
        )
        params.extend([hour_params] * SUBSTEPS_PER_HOUR)
    return params


def frame_to_data_uri(state: np.ndarray) -> str:
    img = render_frame(state)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def run_click_simulation(
    lat: float, lon: float, n_hours: int, start_time_iso: str | None,
    grid, calibrated_params: dict, wind_station: str, default_seed: int = 7,
) -> dict:
    elevation_m, fuel_code, transform, crs, cell_size_m, latlon_to_rowcol = grid

    if not (MIN_HOURS <= n_hours <= MAX_HOURS):
        raise SimulationError(f"hours must be between {MIN_HOURS} and {MAX_HOURS}")

    row, col = latlon_to_rowcol(lat, lon)
    h, w = elevation_m.shape
    if not (0 <= row < h and 0 <= col < w):
        raise SimulationError("that point is outside the fetched AOI for this fire -- pick a point closer to the coast/Santa Lucia range, or switch fires")

    # A cell being non-burnable itself is fine -- ignitions often start on
    # roads/trails/campsites and spread into nearby vegetation (this is
    # literally how the real Soberanes Fire started, on a trail crossing).
    # Only reject if there's no burnable fuel anywhere in the neighborhood,
    # i.e. the point is genuinely stuck (open water, deep in a town).
    r0, r1 = max(0, row - 2), min(h, row + 3)
    c0, c1 = max(0, col - 2), min(w, col + 3)
    neighborhood = fuel_code[r0:r1, c0:c1]
    if not np.any((neighborhood < 90) | (neighborhood >= 100)):
        raise SimulationError("no burnable vegetation near that point (water, urban, or barren) -- pick a spot closer to vegetation")

    start_time = datetime.fromisoformat(start_time_iso) if start_time_iso else None
    obs, wind_source, effective_start = fetch_wind_for_request(lat, lon, start_time, n_hours, wind_station)

    params_per_substep = build_params(
        cell_size_m, n_hours, effective_start, obs,
        calibrated_params["base_prob"], calibrated_params["k_slope"],
        calibrated_params["k_wind"], calibrated_params["burnout_hours"],
    )
    n_steps = n_hours * SUBSTEPS_PER_HOUR
    snapshots = run_simulation(
        elevation_m=elevation_m, fuel_code=fuel_code,
        ignition_points=[(row, col)], params=params_per_substep, n_steps=n_steps, seed=default_seed,
    )

    frames = []
    hours_meta = []
    for hh in range(n_hours + 1):
        state = snapshots[hh * SUBSTEPS_PER_HOUR]
        frames.append(frame_to_data_uri(state))
        acres = cells_to_acres(int(np.count_nonzero(state != UNBURNED)), cell_size_m)
        hours_meta.append({"hour": hh, "acres": round(acres)})

    return {
        "ignition": {"lat": lat, "lon": lon},
        "n_hours": n_hours,
        "hours": hours_meta,
        "frames": frames,
        "wind_source": wind_source,
        "start_time": effective_start.isoformat(),
    }
