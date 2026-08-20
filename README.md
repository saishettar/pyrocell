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
- [ ] Phase 4: validation against real fire perimeter (IoU) -- also where SimParams (base_prob, k_slope, k_wind) get calibrated instead of guessed
- [ ] Phase 5: map-based frontend animation (Leaflet/Mapbox, play/scrub timeline)
- [ ] Phase 6: interactive click-to-simulate + deploy live demo

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
