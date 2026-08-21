"""
Per-fire configuration, so the pipeline can run against more than one real
historical fire without duplicating every script. Soberanes is the fire the
model was calibrated against; Dolan is used purely for cross-validation --
the calibrated params are never refit to it (see cross_validate_dolan.py).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class FireConfig:
    slug: str  # used for data/raw/<slug>/ and file naming
    cal_fire_name: str  # FIRE_NAME in the CAL FIRE FRAP perimeters dataset
    cal_fire_year: int
    aoi_west: float
    aoi_south: float
    aoi_east: float
    aoi_north: float
    ignition_lat: float
    ignition_lon: float
    ignition_time_utc: datetime
    wind_station: str  # nearest ASOS station with deep IEM archive coverage


SOBERANES = FireConfig(
    slug="soberanes",
    cal_fire_name="SOBERANES",
    cal_fire_year=2016,
    aoi_west=-121.95, aoi_south=36.28, aoi_east=-121.55, aoi_north=36.60,
    ignition_lat=36.456429, ignition_lon=-121.924016,
    # 2016-07-22, reported 8:48am PDT
    ignition_time_utc=datetime(2016, 7, 22, 15, 48, tzinfo=timezone.utc),
    wind_station="MRY",  # Monterey Regional Airport, ~15-20km from ignition
)

DOLAN = FireConfig(
    slug="dolan",
    cal_fire_name="DOLAN",
    cal_fire_year=2020,
    # Real final perimeter spans roughly lon -121.68..-121.26, lat 35.94..36.21;
    # this AOI covers that with margin.
    aoi_west=-121.72, aoi_south=35.90, aoi_east=-121.20, aoi_north=36.25,
    ignition_lat=36.123, ignition_lon=-121.602,
    # 2020-08-18, reported ~8:15pm PDT
    ignition_time_utc=datetime(2020, 8, 19, 3, 15, tzinfo=timezone.utc),
    # Same station as Soberanes -- ~56km away (vs ~18km for Soberanes), the
    # nearest ASOS with deep IEM archive coverage even so, since there's no
    # airport directly on this stretch of the Big Sur coast. Real limitation,
    # stated here rather than hidden.
    wind_station="MRY",
)
