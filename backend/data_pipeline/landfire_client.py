"""
Client for the LANDFIRE Product Service (LFPS) REST API.

LFPS is a real, public, no-signup-required government API operated by USGS.
It bundles LANDFIRE raster layers (fuel model, elevation, slope, aspect, canopy)
for a bounding box into a single multi-band GeoTIFF, already co-registered on
one grid -- which sidesteps a lot of manual reprojection/alignment work.

API reference: https://lfps.usgs.gov/LFProductsServiceUserGuide.pdf
"""
from __future__ import annotations

import re
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

import requests

BASE_URL = "https://lfps.usgs.gov/api/job"

# Layer codes as of LANDFIRE 2020/2023 releases (see LFPS user guide sec. 4).
LAYER_ELEVATION = "LF2020_Elev"
LAYER_SLOPE_DEGREES = "LF2020_SlpD"
LAYER_ASPECT = "LF2020_Asp"
LAYER_FUEL_MODEL_40 = "LF2023_FBFM40"
LAYER_CANOPY_COVER = "LF2023_CC"

DEFAULT_LAYERS = [
    LAYER_ELEVATION,
    LAYER_SLOPE_DEGREES,
    LAYER_ASPECT,
    LAYER_FUEL_MODEL_40,
]


@dataclass
class AreaOfInterest:
    west: float
    south: float
    east: float
    north: float

    def as_param(self) -> str:
        # LFPS wants "W S E N", space separated, WGS84.
        return f"{self.west} {self.south} {self.east} {self.north}"


class LFPSError(RuntimeError):
    pass


def submit_job(
    aoi: AreaOfInterest,
    email: str,
    layers: list[str] = None,
    resample_resolution: int = 30,
) -> str:
    """Submit an LFPS job, return the job queue id."""
    layers = layers or DEFAULT_LAYERS
    params = {
        "Email": email,
        "Layer_List": ";".join(layers),
        "Area_of_Interest": aoi.as_param(),
        "Resample_Resolution": resample_resolution,
        "Include_Layer_List_XML_File": "false",
    }
    resp = requests.get(f"{BASE_URL}/submit", params=params, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    job_id = body.get("jobId")
    if not job_id:
        raise LFPSError(f"submit response missing jobId: {body}")
    return job_id


def poll_job(job_id: str, interval_s: float = 5.0, timeout_s: float = 600.0) -> str:
    """Poll job status until it finishes. Returns the download URL."""
    deadline = time.time() + timeout_s
    last_status = None
    while time.time() < deadline:
        resp = requests.get(f"{BASE_URL}/status", params={"JobId": job_id}, timeout=30)
        resp.raise_for_status()
        body = resp.json()
        status = body.get("status")
        if status != last_status:
            print(f"[LFPS] job {job_id}: {status}")
            last_status = status

        if status == "Succeeded":
            return _extract_download_url(body, job_id)
        if status in ("Failed", "Canceled"):
            raise LFPSError(f"job {job_id} ended with status {status}: {body}")

        time.sleep(interval_s)
    raise LFPSError(f"job {job_id} timed out after {timeout_s}s")


def _extract_download_url(status_body: dict, job_id: str) -> str:
    """The Succeeded response carries the download link in outputFile (fall
    back to scanning messages, in case that field is ever absent)."""
    output_file = status_body.get("outputFile")
    if output_file:
        return output_file
    for msg in status_body.get("messages", []):
        text = msg.get("description", "") if isinstance(msg, dict) else str(msg)
        match = re.search(r"https?://\S+\.zip", text)
        if match:
            return match.group(0)
    raise LFPSError(f"could not find download URL in status response: {status_body}")


def download_and_extract(url: str, dest_dir: Path) -> Path:
    """Download the result zip and extract it. Returns path to the .tif file."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dest_dir / "landfire_bundle.zip"

    resp = requests.get(url, timeout=120, stream=True)
    resp.raise_for_status()
    with open(zip_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 16):
            f.write(chunk)

    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest_dir)

    tif_files = list(dest_dir.glob("*.tif"))
    if not tif_files:
        raise LFPSError(f"no .tif found after extracting {zip_path}")
    return tif_files[0]


def fetch_landfire_bundle(
    aoi: AreaOfInterest,
    email: str,
    dest_dir: Path,
    layers: list[str] = None,
    resample_resolution: int = 30,
) -> Path:
    """End-to-end: submit, poll, download, extract. Returns path to GeoTIFF."""
    job_id = submit_job(aoi, email, layers=layers, resample_resolution=resample_resolution)
    print(f"[LFPS] submitted job {job_id} for AOI {aoi.as_param()}")
    download_url = poll_job(job_id)
    print(f"[LFPS] downloading {download_url}")
    tif_path = download_and_extract(download_url, dest_dir)
    print(f"[LFPS] extracted {tif_path}")
    return tif_path
