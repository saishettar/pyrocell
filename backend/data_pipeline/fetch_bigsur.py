"""
Phase 1: pull DEM + fuel data for the Soberanes Fire area (Big Sur / Garrapata
State Park, Santa Lucia Range) via LFPS, save as a numpy grid, and plot the raw
slope/fuel maps so we can eyeball that the data looks sane before writing any
simulation code.

Usage:
    venv/Scripts/python.exe backend/data_pipeline/fetch_bigsur.py --email you@example.com
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import rasterio

from landfire_client import AreaOfInterest, fetch_landfire_bundle

# Bounding box covering the Soberanes Fire's full run (started 2016-07-22 near
# Garrapata SP / Palo Colorado Canyon, burned ~132,000 ac south into the Big
# Sur backcountry and east toward Cachagua). WGS84 degrees.
SOBERANES_AOI = AreaOfInterest(west=-121.95, south=36.28, east=-121.55, north=36.60)

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
OUTPUT_DIR = ROOT / "output"

BAND_NAMES = ["elevation_m", "slope_deg", "aspect_deg", "fuel_model_40"]


def load_bundle_as_arrays(tif_path: Path) -> dict[str, np.ndarray]:
    with rasterio.open(tif_path) as src:
        assert src.count == len(BAND_NAMES), (
            f"expected {len(BAND_NAMES)} bands, got {src.count} -- "
            "did the LFPS Layer_List order change?"
        )
        arrays = {name: src.read(i + 1).astype(np.float32) for i, name in enumerate(BAND_NAMES)}
        arrays["_transform"] = src.transform
        arrays["_crs"] = src.crs
        arrays["_nodata"] = src.nodata
    return arrays


def sanity_check_plot(arrays: dict[str, np.ndarray], out_path: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    panels = [
        ("elevation_m", "terrain", "Elevation (m)"),
        ("slope_deg", "viridis", "Slope (deg)"),
        ("aspect_deg", "twilight", "Aspect (deg, 0=N)"),
        ("fuel_model_40", "tab20", "Scott & Burgan FBFM40 fuel class"),
    ]
    for ax, (key, cmap, title) in zip(axes.flat, panels):
        data = arrays[key]
        im = ax.imshow(data, cmap=cmap)
        ax.set_title(title)
        ax.axis("off")
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.suptitle("Soberanes Fire AOI -- raw LANDFIRE layers (Big Sur, CA)")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    print(f"[sanity check] wrote {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True, help="required by LFPS to identify the job requester")
    parser.add_argument("--resolution", type=int, default=60, help="output cell size in meters (LFPS requires >=31; use multiples of 30)")
    args = parser.parse_args()

    tif_path = fetch_landfire_bundle(
        SOBERANES_AOI,
        email=args.email,
        dest_dir=RAW_DIR,
        resample_resolution=args.resolution,
    )

    arrays = load_bundle_as_arrays(tif_path)
    print("[grid] shape:", arrays["elevation_m"].shape, "crs:", arrays["_crs"])

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        PROCESSED_DIR / "soberanes_grid.npz",
        elevation_m=arrays["elevation_m"],
        slope_deg=arrays["slope_deg"],
        aspect_deg=arrays["aspect_deg"],
        fuel_model_40=arrays["fuel_model_40"],
    )
    print(f"[grid] saved {PROCESSED_DIR / 'soberanes_grid.npz'}")

    sanity_check_plot(arrays, OUTPUT_DIR / "soberanes_raw_layers.png")


if __name__ == "__main__":
    main()
