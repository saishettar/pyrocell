# Methodology

The full build log for pyrocell: how each phase works, what it's
validated against, and the real bugs found along the way. The
[README](../README.md) has the quick summary and setup instructions; this
is the detail behind each line of its Status section.

## Phase 1 -- Data pipeline

Terrain and fuel data come from a single [LANDFIRE Product Service
(LFPS)](https://lfps.usgs.gov) request: elevation, slope, aspect, and
Scott & Burgan FBFM40 fuel-model layers, bundled into one co-registered
GeoTIFF for the requested bounding box -- no manual reprojection needed.
`backend/data_pipeline/fetch_bigsur.py` fetches the Big Sur AOI and writes
a sanity-check plot (`output/soberanes_raw_layers.png`) before any
simulation code runs, so a bad fetch is obvious immediately rather than
discovered three phases later.

One API quirk worth noting: the LFPS docs say `Resample_Resolution` can go
as low as 30m, but the live server rejects anything under 31m.

## Phase 2 -- Core CA model, validated on synthetic conditions

Each unburned cell gets a per-neighbor ignition probability each timestep:

```
p = base_prob * fuel_factor(neighbor's fuel) * slope_factor(direction) * wind_factor(direction)
```

- `fuel_factor`: relative spread rate by FBFM40 class bucket (grass
  fastest, timber litter slowest, non-burnable = 0)
- `slope_factor`: `exp(k_slope * gradient)` -- uphill accelerates,
  downhill decelerates
- `wind_factor`: `exp(k_wind * wind_speed * cos(angle between spread
  direction and downwind direction))` -- the standard simplified wind term
  from CA fire-spread literature (e.g. Alexandridis et al. 2008)

Multiple burning neighbors combine as an independent-trials OR:
`P(ignite) = 1 - prod(1 - p_i)`. Fully vectorized over the grid per
timestep via shifted-array lookups (see `_shift` in `fire_ca.py`) -- no
cell-by-cell Python loops.

Before touching real data, `backend/simulation/toy_conditions.py` runs
three synthetic scenarios (flat/no-wind, sloped terrain, wind from one
direction) and asserts the model behaves physically: symmetric baseline
spread, faster uphill, faster downwind. These checks average over 16
random seeds rather than trusting one run -- a single stochastic
realization is noisy enough (especially early, when only a few cells are
burning) that a lopsided single run doesn't mean the model is biased.

## Phase 3 -- Real historical conditions

Wired the real Soberanes Fire ignition point and real hourly wind into the
Phase 1 grid (`backend/simulation/real_conditions.py`). Two corrections
made along the way:

- **Wikipedia's infobox coordinate for the Soberanes Fire is wrong** -- it
  points about 50km inland, nowhere near Garrapata State Park. Verified
  against the park's actual published location and used that instead.
- **NOAA's own `api.weather.gov` only keeps a rolling window of recent
  station observations**, not historical depth back to 2016. Real hourly
  wind instead comes from the Iowa Environmental Mesonet's ASOS archive
  (`backend/data_pipeline/wind_client.py`), which re-publishes the same
  underlying METAR/ASOS network with decades of history, no auth required.
  One gotcha: IEM's `day2` request parameter is an *exclusive* bound
  (stops at 00:00 UTC on that date) -- fetching without a one-day pad
  silently truncates the wind series and back-fills the missing hours with
  the last known reading instead of erroring.

## Phase 4 -- Calibration and validation (Soberanes)

**Calibration.** `backend/simulation/calibrate.py` fits `base_prob` (the
one free parameter -- `k_slope`/`k_wind`/`burnout_hours` stay fixed, to
keep a three-point fit from overfitting) against real reported Soberanes
acreage milestones from Monterey County news coverage: ~2,000ac at 24h,
~10,000ac at 40h, ~14,897ac at 65h. Best fit: `base_prob=0.046`.

**The speed-ceiling bug.** The first calibration pass saturated well below
the real growth curve no matter how high `base_prob` went. Root cause: a
Moore-neighborhood CA can advance at most one cell per timestep, so at 60m
cells and 1-hour steps the model had a hard ceiling of 60m/hour
(~1.4km/day) -- too slow for real wind-driven fire runs regardless of
ignition probability. Fixed by running `SUBSTEPS_PER_HOUR = 6` CA
sub-steps per real hour, each holding that hour's real wind constant --
raises the effective speed ceiling without needing finer wind data than
actually exists.

**Shape validation.** Compared the calibrated model's output against CAL
FIRE's real final Soberanes perimeter (132,104 acres, from the [FRAP
historical fire perimeters
dataset](https://data.ca.gov/dataset/california-fire-perimeters-all), no
auth needed) via IoU (intersection-over-union): **~24% overlap**,
area-matched to isolate shape agreement from duration mismatch. Two
caveats stated directly rather than buried: only 71% of the real perimeter
falls inside the fetched AOI (the rest extended past the east boundary),
and the real fire took 83 days under active firefighting suppression that
this model doesn't represent at all. So this IoU reflects *natural-spread
shape plausibility*, not a validated physics-accuracy claim -- an honest
framing for a model this simplified.

## Phase 5 -- Map-based frontend

`backend/api/generate_frames.py` pre-renders the calibrated simulation as
transparent hourly PNG map overlays server-side, rather than shipping raw
grid data to the browser for client-side geospatial rendering -- keeps the
frontend to vanilla Leaflet plus a slider. A thin FastAPI server
(`backend/api/main.py`) serves the frames, metadata, and the real CAL FIRE
perimeter as a toggleable overlay.

Bug caught during in-browser verification: the map first loaded at zoom 17
(street level) instead of fitting the ~35km AOI. `fitBounds` was running
before the container's layout had committed, computing against a
zero-size map. Fixed with an explicit `invalidateSize()` first.

## Phase 6 -- Click-to-simulate

`POST /api/simulate` (`backend/api/simulate.py`) runs the calibrated model
on demand for any clicked point within the fetched AOI, 24-96 hours, with
either historical wind (same IEM archive as Soberanes) or live current
wind (NOAA's `forecastHourly` API, 16-point compass parsing, mph-to-m/s
conversion). Frames come back as base64 PNG data URIs in the JSON response
rather than written to disk, keeping the endpoint stateless.

Bug caught during verification: the ignition-point validation originally
rejected a click if the exact pixel was non-burnable fuel -- which
rejected the Soberanes ignition point itself, since its precise coordinate
sits on a road (fuel code 91) crossing burnable vegetation. That's
literally how the real fire started and spread: an ignition on a
trail/road, then into the surrounding fuel. Fixed to only reject a click
if there's no burnable fuel anywhere in its neighborhood.

## Phase 7 -- Cross-validation against a second fire (2020 Dolan Fire)

The question Phase 4's calibration couldn't answer on its own: did fitting
`base_prob` to Soberanes just curve-fit one dataset, or does it
generalize? `fire_config.py` adds a `FireConfig` abstraction (AOI,
ignition point/time, wind station) so the pipeline can run against a
second, independent fire without duplicating every script; the shared
grid/wind-loading functions in `soberanes_conditions.py` took optional
overrides so every *existing* call site keeps its exact old behavior by
default.

**A single-seed run looked broken.** Burning cells hit zero at hour 14 and
a 21-day run never recovered. This turned out to be a real model property,
not a bug: `BURNED` is a terminal state, so a probabilistic CA with a
finite burnout window can stochastically self-extinguish before it
"catches" -- the same way some real small ignitions fizzle out without
becoming a big fire. A 16-seed screen at 48h confirmed it: 15/16 seeds
escape and grow normally; that one seed (7, the default used everywhere
else in this project) was simply the unlucky draw.
`cross_validate_dolan.py` now screens many seeds cheaply, then runs a
handful to full duration and reports the IoU distribution across escaped
runs -- the same Monte-Carlo-over-eyeballing discipline as the Phase 2
toy checks.

**Result:** among escaped seeds (5 run to the full 21-day duration), IoU
against the real Dolan perimeter averaged **0.27 (range 0.25-0.31)** --
comparable to, even slightly above, Soberanes' own ~0.24 validation
number, using parameters that were never touched for Dolan. That's the
actual evidence the calibration generalizes rather than curve-fitting one
fire.

**A second real bug, only exposed by the new AOI.** `fuel_spread_rate`'s
fallback used to default any unrecognized fuel code to 0.3 (moderately
burnable) instead of non-burnable -- silently treating LANDFIRE nodata
(-9999, e.g. open ocean past its coverage extent) as real fuel. This never
surfaced against Soberanes' AOI, whose ocean cells are real LANDFIRE water
code 98, not nodata. It did surface against Dolan's AOI, which reaches
~11% true nodata (open water beyond LANDFIRE's coverage). Fixed to default
unrecognized codes to non-burnable; doesn't change any previously
published Soberanes results, since that code path was never hit there.

Each fire's raw GeoTIFF now lives in its own `data/raw/<fire>/` subdir to
avoid glob collisions between fires; perimeter GeoJSONs stay flat in
`data/raw/` with fire-specific filenames.

## Phase 7.5 -- Both fires live in the app

Phase 7's cross-validation only existed as a standalone script producing
static plots -- Dolan wasn't actually viewable in the running app.
`generate_frames.py` and `main.py` were generalized to hold both fires'
grids and pre-rendered demo frames simultaneously (`data/frames/<fire>/`),
and the frontend gained a fire selector that swaps the map bounds, demo
animation, real perimeter overlay, and click-to-simulate AOI together.

One thing worth calling out explicitly: Dolan's demo animation uses a
fixed seed (8) chosen because Phase 7 confirmed it escapes stochastic
extinction and lands close to the mean IoU across escaped runs -- not
cherry-picked for a better-looking result, just a representative,
non-extinct one. `generate_frames.py --seed` can override it.
