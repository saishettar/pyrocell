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

- [x] Phase 1: data pipeline -- real DEM + fuel data for the Big Sur AOI (LANDFIRE)
- [x] Phase 2: core CA simulation loop, validated on synthetic conditions
- [x] Phase 3: real historical ignition point + hourly wind (2016 Soberanes Fire)
- [x] Phase 4: calibration + validation -- **~24% IoU** against the real Soberanes perimeter
- [x] Phase 5: map-based frontend animation (Leaflet, play/scrub timeline)
- [x] Phase 6: interactive click-to-simulate, live or historical wind
- [x] Phase 7: cross-validated against a second, independent fire (2020 Dolan) -- **~27% mean IoU**, params not refit
- [ ] Phase 8: deploy a live public demo (pending a hosting decision)

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
10-15 minutes end to end (mostly data downloads); after that, restarting
the server is instant.

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

**2. Fetch the real terrain + fuel data (Phase 1)**

```bash
venv/Scripts/python.exe backend/data_pipeline/fetch_bigsur.py --email you@example.com
```

Pulls elevation/slope/aspect/fuel-model layers for the Big Sur AOI from
LANDFIRE (LFPS requires an email to identify the job requester -- no
account, nothing sent to you). Saves `data/processed/soberanes_grid.npz`
and a sanity-check plot at `output/soberanes_raw_layers.png`.

**3. Fetch the real fire perimeter + calibrate (Phase 4)**

```bash
venv/Scripts/python.exe backend/data_pipeline/fetch_perimeter.py   # real CAL FIRE perimeter (ground truth)
venv/Scripts/python.exe backend/simulation/calibrate.py            # fits base_prob against real fire growth, writes data/processed/calibrated_params.txt
```

**4. Pre-render the demo animation frames (Phase 5) and start the server**

```bash
venv/Scripts/python.exe backend/api/generate_frames.py             # renders data/frames/*.png (not checked in -- ~1.6MB, regenerate locally)
venv/Scripts/python.exe -m uvicorn backend.api.main:app --port 8000
```

Then open `http://localhost:8000`. You'll get the full app: the animated
2016 Soberanes Fire demo with the real recorded perimeter toggle, plus
click-to-simulate anywhere in the fetched AOI with live or historical wind
(Phase 6).

**Optional: reproduce the cross-validation (Phase 7)**

```bash
venv/Scripts/python.exe backend/data_pipeline/fetch_dolan.py --email you@example.com
venv/Scripts/python.exe backend/data_pipeline/fetch_perimeter.py --fire-name DOLAN --year 2020
venv/Scripts/python.exe backend/simulation/cross_validate_dolan.py
```

Runs the Soberanes-calibrated params, completely unchanged, against the
2020 Dolan Fire's real terrain/wind/perimeter. Takes a while -- it's a
16-seed screen plus 5 full 21-day simulations on a ~650x785 grid.
