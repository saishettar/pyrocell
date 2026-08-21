# Wildfire Spread Simulator

A cellular-automaton wildfire spread model driven by real terrain, fuel, and wind data, validated against real historical fires.

## Purpose

Most wildfire-spread demos online are either static maps of past fires or toy cellular automata with made-up parameters. This project ties the two together: a real spread model, driven by real terrain, fuel, and wind data, scored against what the fire actually did instead of an animation that just looks plausible.

- **Calibrated, not guessed.** `base_prob` is fit against the 2016 Soberanes Fire's actual reported growth curve (Phase 4).
- **Cross-validated, not just fit.** The same calibrated parameters, never refit, are run against a second, independent fire (2020 Dolan) to check that the model generalizes instead of curve-fitting one dataset (Phase 7).
- **Scored honestly.** IoU (intersection-over-union) against each fire's real recorded perimeter, with the model's real limitations stated directly: no suppression modeling, a single wind station, simplified physics. Current results: about 24% IoU on Soberanes (calibrated) and about 27% mean IoU on Dolan (cross-validated).
- **Interactive, not a fixed demo.** Click any point inside either fire's fetched area, pick a duration and live or historical wind, and watch a fresh simulation run on real terrain.

## Theoretical basis

The standard model for wildland fire spread is Rothermel's surface fire spread equation (Rothermel, 1972, *A Mathematical Model for Predicting Fire Spread in Wildland Fuels*, USDA Forest Service Research Paper INT-115). It computes rate of spread from fuel bed properties, moisture, wind, and slope, and it's the physics core inside FARSITE and FlamMap, the tools fire agencies actually use.

This project approximates that behavior with a simplified probabilistic cellular automaton instead of implementing the full Rothermel equation set. Each burning cell has a per-neighbor ignition probability driven by slope, wind, fuel type, and fuel moisture, updated every timestep. It's a much coarser model, but it's cheap to vectorize and reason about, and it still captures the same qualitative drivers: fire runs faster uphill, faster downwind, and faster through drier, flashier fuels.

## Validation targets

**2016 Soberanes Fire (calibration target).** Started July 22, 2016 near Garrapata State Park and Palo Colorado Canyon in Big Sur, California, and burned about 132,000 acres. It's well documented, has public Cal Fire and NIFC perimeter data, and its terrain, a steep coastal range with strong diurnal wind patterns, makes slope and wind effects clearly visible. That makes it a good stress test for the model. `base_prob` is fit against this fire's real growth curve in Phase 4.

**2020 Dolan Fire (cross-validation target).** Started August 18, 2020 near Dolan Ridge on the Big Sur south coast and burned about 124,500 acres. It's used purely to check whether the Soberanes calibration generalizes: the exact same parameters, never refit, are run against a different stretch of coastline with different terrain and fuel in Phase 7.

## Status

- [x] Phase 1: data pipeline. Real DEM and fuel data for the Big Sur AOI (LANDFIRE).
- [x] Phase 2: core CA simulation loop, validated on synthetic conditions.
- [x] Phase 3: real historical ignition point and hourly wind (2016 Soberanes Fire).
- [x] Phase 4: calibration and validation. **About 24% IoU** against the real Soberanes perimeter.
- [x] Phase 5: map-based frontend animation (Leaflet, play/scrub timeline).
- [x] Phase 6: interactive click-to-simulate, live or historical wind.
- [x] Phase 7: cross-validated against a second, independent fire (2020 Dolan). **About 27% mean IoU**, parameters not refit.
- [x] Phase 7.5: both fires live in the app. A fire selector switches the map, demo animation, real perimeter, and click-to-simulate area between Soberanes and Dolan.
- [ ] Phase 8: deploy a live public demo, pending a hosting decision.

Everything above is built and running locally (see [Purpose](#purpose)). The one thing left is putting it somewhere with a public URL instead of `localhost`.

## Data sources

| Data | Source |
|---|---|
| Elevation, slope, aspect, fuel model (FBFM40) | [LANDFIRE Product Service (LFPS)](https://lfps.usgs.gov), one bundled, co-registered GeoTIFF |
| Wind | NOAA/NWS API |
| Real fire perimeters | Cal Fire GIS / NIFC |

## Documentation

- [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md): the full build log. How the CA model works, how it was calibrated against real fire data, the cross-validation against a second fire, and the real bugs found and fixed at each phase.

## Quick start

There's no hosted live demo yet. This repo is public, so the way to see it running is to clone it and run the pipeline locally. Everything below uses free, no-signup government or open data (LANDFIRE, NOAA, IEM, CAL FIRE): no API keys, no billing, no accounts to create. The first run takes about 15 to 20 minutes end to end for both fires, mostly data downloads and frame rendering. After that, restarting the server is instant.

**1. Clone the repo and set up a virtual environment**

```bash
git clone https://github.com/saishettar/pyrocell.git
cd pyrocell
python -m venv venv
venv/Scripts/python.exe -m pip install -r requirements.txt   # venv/bin/python on macOS/Linux
```

Windows note: use a python.org CPython install, not an MSYS2/mingw64 Python. rasterio and GDAL only ship prebuilt wheels for the standard win_amd64 tags, so an MSYS2 interpreter falls back to source builds and fails on missing CA certs. macOS and Linux with a normal system Python should be fine.

**2. Fetch the real terrain and fuel data for both fires (Phase 1 and Phase 7)**

```bash
venv/Scripts/python.exe backend/data_pipeline/fetch_bigsur.py --email you@example.com
venv/Scripts/python.exe backend/data_pipeline/fetch_dolan.py --email you@example.com
```

This pulls elevation, slope, aspect, and fuel-model layers from LANDFIRE for each fire's area. LFPS requires an email to identify the job requester, but that's all it's for; there's no account and nothing is sent to you. It also writes a sanity-check plot for each fire (`output/soberanes_raw_layers.png`, `output/dolan_raw_layers.png`).

**3. Fetch the real fire perimeters and calibrate (Phase 4)**

```bash
venv/Scripts/python.exe backend/data_pipeline/fetch_perimeter.py                          # real CAL FIRE Soberanes perimeter (ground truth)
venv/Scripts/python.exe backend/data_pipeline/fetch_perimeter.py --fire-name DOLAN --year 2020
venv/Scripts/python.exe backend/simulation/calibrate.py                                   # fits base_prob against Soberanes' real fire growth, writes data/processed/calibrated_params.txt
```

**4. Pre-render both fires' demo animations (Phase 5 and 7.5) and start the server**

```bash
venv/Scripts/python.exe backend/api/generate_frames.py --fire soberanes   # renders data/frames/soberanes/*.png (not checked in, regenerate locally)
venv/Scripts/python.exe backend/api/generate_frames.py --fire dolan       # renders data/frames/dolan/*.png
venv/Scripts/python.exe -m uvicorn backend.api.main:app --port 8000
```

Then open `http://localhost:8000`. A dropdown at the top switches between the two fires, each with its own animated demo, real recorded perimeter toggle, and click-to-simulate feature (Phase 6) with live or historical wind, restricted to that fire's fetched area.

**Optional: reproduce the Phase 7 cross-validation numbers**

```bash
venv/Scripts/python.exe backend/simulation/cross_validate_dolan.py
```

This re-derives the mean IoU and escape-rate numbers reported in the README and `docs/METHODOLOGY.md`. It runs a 16-seed screen plus 5 full 21-day simulations, so it takes a while, and it isn't needed just to see Dolan in the app; step 4 already covers that with one representative seed.
