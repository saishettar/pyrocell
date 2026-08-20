"""
Historical hourly wind via the Iowa Environmental Mesonet's ASOS archive.

NOAA/NWS's own api.weather.gov only keeps a rolling window of recent station
observations (days, not years), so it can't answer "what was the wind doing
during the 2016 Soberanes Fire." IEM re-publishes the same underlying
METAR/ASOS network observations with full historical depth back for
decades, no auth required. https://mesonet.agron.iastate.edu/request/asos/

Caveat we're accepting for now: this pulls from the nearest airport ASOS
station (Monterey, ~15-20 km from the Soberanes ignition point), not a
ridge-top RAWS station in the actual burn terrain. Coastal airport wind
under-represents canyon/ridge wind effects (e.g. nighttime katabatic
drainage flow) -- a known simplification, not a bug.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import requests

ASOS_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
KNOTS_TO_MPS = 0.514444


@dataclass
class WindObservation:
    valid_time: datetime  # UTC
    dir_from_deg: float | None   # meteorological convention: direction wind is blowing FROM
    speed_mps: float | None

    @property
    def dir_to_deg(self) -> float | None:
        """Direction the wind blows TOWARD -- what actually pushes fire."""
        if self.dir_from_deg is None:
            return None
        return (self.dir_from_deg + 180.0) % 360.0


def fetch_historical_wind(station: str, start: date, end: date) -> list[WindObservation]:
    """Hourly-ish wind observations for `station` (ASOS/METAR id, e.g. 'MRY')
    between start and end (inclusive), in UTC."""
    params = {
        "station": station,
        "data": "drct,sknt",
        "year1": start.year, "month1": start.month, "day1": start.day,
        "year2": end.year, "month2": end.month, "day2": end.day,
        "tz": "UTC",
        "format": "onlycomma",
        "latlon": "no",
        "elev": "no",
        "missing": "M",
        "trace": "T",
        "direct": "no",
        "report_type": 3,  # hourly routine METAR, skip SPECI one-offs
    }
    resp = requests.get(ASOS_URL, params=params, timeout=30)
    resp.raise_for_status()

    lines = resp.text.strip().splitlines()
    header = lines[0].split(",")
    obs = []
    for line in lines[1:]:
        parts = line.split(",")
        row = dict(zip(header, parts))
        valid = datetime.strptime(row["valid"], "%Y-%m-%d %H:%M")
        drct = None if row["drct"] == "M" else float(row["drct"])
        sknt = None if row["sknt"] == "M" else float(row["sknt"])
        speed_mps = sknt * KNOTS_TO_MPS if sknt is not None else None
        obs.append(WindObservation(valid_time=valid, dir_from_deg=drct, speed_mps=speed_mps))
    return obs


def wind_at_or_before(obs: list[WindObservation], t: datetime) -> WindObservation:
    """Most recent observation at or before time t (hold-last-value)."""
    candidates = [o for o in obs if o.valid_time <= t]
    if not candidates:
        return obs[0]
    return max(candidates, key=lambda o: o.valid_time)
