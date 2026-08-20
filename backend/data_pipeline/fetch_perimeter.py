"""
Fetch the real historical fire perimeter (ground truth for Phase 4
validation) from CAL FIRE FRAP's public ArcGIS FeatureServer -- no auth,
no bulk statewide download needed, just a filtered query.

Usage:
    venv/Scripts/python.exe backend/data_pipeline/fetch_perimeter.py
"""
from __future__ import annotations

from pathlib import Path

import requests

FEATURE_SERVER = (
    "https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/arcgis/rest/services/"
    "California_Historic_Fire_Perimeters/FeatureServer/0/query"
)

FIRE_NAME = "SOBERANES"
FIRE_YEAR = 2016

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"


def fetch_perimeter(fire_name: str, year: int) -> dict:
    params = {
        "where": f"FIRE_NAME='{fire_name}' AND YEAR_={year}",
        "outFields": "*",
        "f": "geojson",
        "outSR": 4326,
    }
    resp = requests.get(FEATURE_SERVER, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("features"):
        raise ValueError(f"no perimeter found for {fire_name} {year}")
    return data


def main():
    print(f"[perimeter] querying CAL FIRE FRAP for {FIRE_NAME} {FIRE_YEAR}...")
    data = fetch_perimeter(FIRE_NAME, FIRE_YEAR)
    props = data["features"][0]["properties"]
    print(f"[perimeter] found: {props['FIRE_NAME']} {props['YEAR_']}, {props['GIS_ACRES']:,.0f} acres, "
          f"alarm={props['ALARM_DATE']} cont={props['CONT_DATE']}")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RAW_DIR / "soberanes_perimeter.geojson"
    import json
    with open(out_path, "w") as f:
        json.dump(data, f)
    print(f"[perimeter] saved {out_path}")


if __name__ == "__main__":
    main()
