"""
Cross-validation fire #2: pull DEM + fuel data for the 2020 Dolan Fire area
(Big Sur south coast, Dolan Ridge / Los Padres NF) via LFPS. Mirrors
fetch_bigsur.py but for a different AOI/fire -- kept as a separate script
rather than parameterizing fetch_bigsur.py, since each fire's AOI and plot
are one-off enough that a thin duplicate is clearer than a config-driven
abstraction here.

Usage:
    venv/Scripts/python.exe backend/data_pipeline/fetch_dolan.py --email you@example.com
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import rasterio

from landfire_client import AreaOfInterest, fetch_landfire_bundle

# Real final Dolan perimeter spans roughly lon -121.68..-121.26, lat
# 35.94..36.21 (CAL FIRE FRAP); this AOI covers that with margin.
DOLAN_AOI = AreaOfInterest(west=-121.72, south=35.90, east=-121.20, north=36.25)

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw" / "dolan"
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
    nodata = arrays["_nodata"]
    for ax, (key, cmap, title) in zip(axes.flat, panels):
        data = arrays[key]
        data = np.ma.masked_equal(data, nodata) if nodata is not None else data
        cmap_obj = plt.get_cmap(cmap).copy()
        cmap_obj.set_bad("black")
        im = ax.imshow(data, cmap=cmap_obj)
        ax.set_title(title)
        ax.axis("off")
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.suptitle("Dolan Fire AOI -- raw LANDFIRE layers (Big Sur south coast, CA)")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    print(f"[sanity check] wrote {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True, help="required by LFPS to identify the job requester")
    parser.add_argument("--resolution", type=int, default=60, help="output cell size in meters (LFPS requires >=31)")
    args = parser.parse_args()

    tif_path = fetch_landfire_bundle(
        DOLAN_AOI,
        email=args.email,
        dest_dir=RAW_DIR,
        resample_resolution=args.resolution,
    )

    arrays = load_bundle_as_arrays(tif_path)
    print("[grid] shape:", arrays["elevation_m"].shape, "crs:", arrays["_crs"])

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        PROCESSED_DIR / "dolan_grid.npz",
        elevation_m=arrays["elevation_m"],
        slope_deg=arrays["slope_deg"],
        aspect_deg=arrays["aspect_deg"],
        fuel_model_40=arrays["fuel_model_40"],
    )
    print(f"[grid] saved {PROCESSED_DIR / 'dolan_grid.npz'}")

    sanity_check_plot(arrays, OUTPUT_DIR / "dolan_raw_layers.png")


if __name__ == "__main__":
    main()
