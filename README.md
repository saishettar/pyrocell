# Wildfire Spread Simulator

A cellular-automaton wildfire spread model driven by real terrain, fuel, and
wind data, validated against a real historical fire.

## Theoretical basis

The gold-standard model for wildland fire spread is Rothermel's surface fire
spread equation (Rothermel, 1972, *A Mathematical Model for Predicting Fire
Spread in Wildland Fuels*, USDA Forest Service Research Paper INT-115), which
computes rate of spread from fuel bed properties, moisture, wind, and slope.
It's the physics core inside FARSITE and FlamMap, the tools fire agencies
actually use.

This project approximates that behavior with a simplified probabilistic
cellular automaton rather than implementing the full Rothermel equation set:
each burning cell has a per-neighbor ignition probability driven by slope,
wind, fuel type, and fuel moisture, updated each timestep. It's a much
coarser model, but cheap to vectorize and reason about, while still
capturing the same qualitative drivers (fire runs faster uphill, downwind,
and through drier/flashier fuels).

## Validation target: 2016 Soberanes Fire

Started 2016-07-22 near Garrapata State Park / Palo Colorado Canyon (Big
Sur, CA), burned ~132,000 acres. Chosen because it's well documented, has
public Cal Fire/NIFC perimeter data, and the terrain (steep coastal range,
strong diurnal wind patterns) makes slope/wind effects clearly visible --
a good stress test for the model.

## Status

- [x] Phase 1: data pipeline (DEM + fuel data for the Big Sur AOI) -- see `output/soberanes_raw_layers.png`
- [x] Phase 2: core CA simulation loop, validated on toy conditions (`backend/simulation/`) -- symmetric baseline, faster uphill, faster downwind, all confirmed with multi-seed statistical checks, not just eyeballing
- [x] Phase 3: real historical conditions -- real ignition point (Soberanes Canyon, corrected from Wikipedia's wrong infobox coordinate), real hourly wind from NOAA/IEM ASOS archive for 2016-07-22 through 2016-07-24 (`backend/simulation/real_conditions.py`, see `output/phase3_real_conditions.png`)
- [x] Phase 4: calibration + validation (`backend/simulation/calibrate.py`, `validate_perimeter.py`)
  - Calibrated `base_prob` against 3 real reported acreage milestones (2,000ac@24h, 10,000ac@40h, 14,897ac@65h -- Monterey County news coverage) instead of guessing. Best fit: `base_prob=0.046` (`output/phase4_calibration.png`).
  - Along the way, found and fixed a real structural bug: a Moore-neighborhood CA has a hard speed ceiling of `cell_size / timestep` (60m/hour here) -- no amount of probability tuning could exceed that, which is why the first calibration pass saturated well below the real growth curve. Fixed by running 6 CA sub-steps per real hour (`SUBSTEPS_PER_HOUR`), each using that hour's real wind.
  - Validated shape against CAL FIRE's official final perimeter (132,104 acres, IRWIN ID `EB4671D6-...`) via IoU: **~24% overlap** (area-matched comparison, isolating shape agreement from duration mismatch). Caveats stated plainly, not buried: only 71% of the real perimeter falls inside our fetched AOI (the rest extended past our east boundary), and the real fire took 83 days under active suppression that this model doesn't attempt to represent -- so this IoU reflects natural-spread shape plausibility, not a validated physics accuracy claim. See `output/phase4_perimeter_validation.png`.
- [x] Phase 5: map-based frontend animation -- real Leaflet map (OpenStreetMap basemap) with a play/scrub timeline over the calibrated 7-day simulation, real recorded perimeter as a toggleable overlay for visual comparison (`backend/api/`, `frontend/`)
- [x] Phase 6a: interactive click-to-simulate -- click any point in the fetched AOI, pick a duration (24-96h) and an optional historical date (blank = live current wind from NOAA `forecastHourly`), run on demand (`POST /api/simulate`, `backend/api/simulate.py`). Historical dates reuse the same IEM/ASOS archive as Soberanes; live conditions hit `api.weather.gov`. Verified in-browser for both wind sources -- a live run near Big Sur's inland side stalled at 15 acres under tonight's calm wind, while historical Soberanes conditions reproduce the Phase 4 calibration curve exactly, which is the expected contrast.
- [ ] Phase 6b: deploy a live public demo (pending a hosting decision)

## End goal

A deployed web app: click a point on a Big Sur map, set a start time, hit
simulate, and watch an hour-by-hour animated fire perimeter grow across
real terrain -- with a toggle to overlay the actual recorded perimeter of a
historical fire so the model's accuracy is visible, not just claimed. The
headline number for the README/resume is the IoU (intersection-over-union)
between simulated and real burned area, the same role R²/RMSE played in a
past tire-degradation modeling project.

## Data sources

| Data | Source |
|---|---|
| Elevation, slope, aspect, fuel model (FBFM40) | [LANDFIRE Product Service (LFPS)](https://lfps.usgs.gov) -- one bundled, co-registered GeoTIFF |
| Wind | NOAA/NWS API |
| Real fire perimeters | Cal Fire GIS / NIFC |

## Setup

```bash
python -m venv venv
venv/Scripts/python.exe -m pip install -r requirements.txt
```

Windows note: use a python.org CPython install (not an MSYS2/mingw64
Python) -- rasterio/GDAL only ship prebuilt wheels for standard win_amd64
tags, so an MSYS2 interpreter falls back to source builds and fails on
missing CA certs.

## Phase 1: fetch data

```bash
venv/Scripts/python.exe backend/data_pipeline/fetch_bigsur.py --email you@example.com
```

Pulls elevation/slope/aspect/fuel-model layers for the Soberanes Fire AOI
via LFPS, saves them as `data/processed/soberanes_grid.npz`, and writes a
sanity-check plot to `output/soberanes_raw_layers.png`.

## Phase 5: run the map animation

```bash
venv/Scripts/python.exe backend/data_pipeline/fetch_perimeter.py   # real CAL FIRE perimeter, needed once
venv/Scripts/python.exe backend/simulation/calibrate.py            # writes data/processed/calibrated_params.txt
venv/Scripts/python.exe backend/api/generate_frames.py             # pre-renders data/frames/*.png (not committed, regenerate locally)
venv/Scripts/python.exe -m uvicorn backend.api.main:app --port 8000
```

Then open `http://localhost:8000`. `data/frames/` isn't checked in (1.6MB of
generated PNGs) -- run `generate_frames.py` locally to produce it.
