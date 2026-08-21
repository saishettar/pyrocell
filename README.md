# Wildfire Spread Simulator

A cellular-automaton wildfire spread model driven by real terrain, fuel, and
wind data, validated against real historical fires.

## Purpose

This exists to demonstrate applied computational modeling and validation
discipline, not just to animate a fire on a map -- the same shape as a
past tire-degradation modeling project: a real, working tool with a
defensible accuracy number behind it, not a black box. Concretely:

- **Calibrated**, not guessed -- `base_prob` is fit against the real 2016
  Soberanes Fire's actual reported growth curve (Phase 4).
- **Cross-validated**, not just fit -- the same calibrated params, never
  refit, are run against a second, independent fire (2020 Dolan) to check
  the model generalizes rather than curve-fitting one dataset (Phase 7).
- **Scored honestly** -- IoU (intersection-over-union) against each fire's
  real recorded perimeter, with the model's real limitations (no
  suppression modeling, single wind station, simplified physics) stated
  directly rather than buried. Currently: **~24% IoU** (Soberanes,
  calibrated) and **~27% mean IoU** (Dolan, cross-validated).
- **Interactive**, not a fixed demo -- click any point in either fire's
  fetched area, pick a duration and live-or-historical wind, and watch a
  fresh simulation run on real terrain.

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

## Validation targets

**2016 Soberanes Fire** (calibration target) -- started 2016-07-22 near
Garrapata State Park / Palo Colorado Canyon (Big Sur, CA), burned ~132,000
acres. Chosen because it's well documented, has public Cal Fire/NIFC
perimeter data, and the terrain (steep coastal range, strong diurnal wind
patterns) makes slope/wind effects clearly visible -- a good stress test
for the model. `base_prob` is fit against this fire's real growth curve
(Phase 4).

**2020 Dolan Fire** (cross-validation target) -- started 2020-08-18 near
Dolan Ridge, Big Sur south coast, burned ~124,500 acres. Used purely to
check whether the Soberanes calibration generalizes: run with the exact
same params, never refit, against a different stretch of coastline with
different terrain and fuel (Phase 7).

## Status

- [x] Phase 1: data pipeline -- real DEM + fuel data for the Big Sur AOI (LANDFIRE)
- [x] Phase 2: core CA simulation loop, validated on synthetic conditions
- [x] Phase 3: real historical ignition point + hourly wind (2016 Soberanes Fire)
- [x] Phase 4: calibration + validation -- **~24% IoU** against the real Soberanes perimeter
- [x] Phase 5: map-based frontend animation (Leaflet, play/scrub timeline)
- [x] Phase 6: interactive click-to-simulate, live or historical wind
- [x] Phase 7: cross-validated against a second, independent fire (2020 Dolan) -- **~27% mean IoU**, params not refit
- [x] Phase 7.5: both fires live in the app -- a fire selector switches the map, demo animation, real perimeter, and click-to-simulate AOI between Soberanes and Dolan
- [ ] Phase 8: deploy a live public demo (pending a hosting decision)

Everything above is built and running locally (see [Purpose](#purpose)) --
the one thing left is putting it somewhere with a public URL instead of
`localhost` (Phase 8).

## Data sources

| Data | Source |
|---|---|
| Elevation, slope, aspect, fuel model (FBFM40) | [LANDFIRE Product Service (LFPS)](https://lfps.usgs.gov) -- one bundled, co-registered GeoTIFF |
| Wind | NOAA/NWS API |
| Real fire perimeters | Cal Fire GIS / NIFC |

## Documentation

- [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) -- the full build log: how
  the CA model works, how it was calibrated against real fire data, the
  cross-validation against a second fire, and the real bugs found (and
  fixed) at each phase.

## Quick Start

There's no hosted live demo yet -- this repo is public, so the way to see
it running is to clone it and run the pipeline locally. Everything below
is free, no-signup government/open data (LANDFIRE, NOAA, IEM, CAL FIRE) --
no API keys, no billing, no accounts to create. First run takes maybe
15-20 minutes end to end for both fires (mostly data downloads and frame
rendering); after that, restarting the server is instant.

**1. Clone and set up a virtualenv**

```bash
git clone https://github.com/saishettar/pyrocell.git
cd pyrocell
python -m venv venv
venv/Scripts/python.exe -m pip install -r requirements.txt   # venv/bin/python on macOS/Linux
```

Windows note: use a python.org CPython install (not an MSYS2/mingw64
Python) -- rasterio/GDAL only ship prebuilt wheels for standard win_amd64
tags, so an MSYS2 interpreter falls back to source builds and fails on
missing CA certs. macOS/Linux with a normal system Python should be fine.

**2. Fetch the real terrain + fuel data for both fires (Phase 1 + 7)**

```bash
venv/Scripts/python.exe backend/data_pipeline/fetch_bigsur.py --email you@example.com
venv/Scripts/python.exe backend/data_pipeline/fetch_dolan.py --email you@example.com
```

Pulls elevation/slope/aspect/fuel-model layers from LANDFIRE for each
fire's AOI (LFPS requires an email to identify the job requester -- no
account, nothing sent to you), plus a sanity-check plot for each
(`output/soberanes_raw_layers.png`, `output/dolan_raw_layers.png`).

**3. Fetch the real fire perimeters + calibrate (Phase 4)**

```bash
venv/Scripts/python.exe backend/data_pipeline/fetch_perimeter.py                          # real CAL FIRE Soberanes perimeter (ground truth)
venv/Scripts/python.exe backend/data_pipeline/fetch_perimeter.py --fire-name DOLAN --year 2020
venv/Scripts/python.exe backend/simulation/calibrate.py                                   # fits base_prob against Soberanes' real fire growth, writes data/processed/calibrated_params.txt
```

**4. Pre-render both fires' demo animations (Phase 5/7.5) and start the server**

```bash
venv/Scripts/python.exe backend/api/generate_frames.py --fire soberanes   # renders data/frames/soberanes/*.png (not checked in, regenerate locally)
venv/Scripts/python.exe backend/api/generate_frames.py --fire dolan       # renders data/frames/dolan/*.png
venv/Scripts/python.exe -m uvicorn backend.api.main:app --port 8000
```

Then open `http://localhost:8000`. A dropdown at the top switches between
the two fires -- each with its own animated demo, real recorded perimeter
toggle, and click-to-simulate (Phase 6) with live or historical wind,
restricted to that fire's fetched AOI.

**Optional: reproduce the Phase 7 cross-validation numbers**

```bash
venv/Scripts/python.exe backend/simulation/cross_validate_dolan.py
```

Re-derives the ~27% mean-IoU / escape-rate numbers reported in the README
and `docs/METHODOLOGY.md` -- a 16-seed screen plus 5 full 21-day
simulations, so it takes a while. Not needed just to see Dolan in the app;
step 4 already covers that with one representative seed.
