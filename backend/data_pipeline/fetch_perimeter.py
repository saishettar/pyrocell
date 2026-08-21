"""
Fetch a real historical fire perimeter (ground truth for validation) from
CAL FIRE FRAP's public ArcGIS FeatureServer -- no auth, no bulk statewide
download needed, just a filtered query.

Usage:
    venv/Scripts/python.exe backend/data_pipeline/fetch_perimeter.py                          # Soberanes 2016 (default)
    venv/Scripts/python.exe backend/data_pipeline/fetch_perimeter.py --fire-name DOLAN --year 2020
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import requests

FEATURE_SERVER = (
    "https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/arcgis/rest/services/"
    "California_Historic_Fire_Perimeters/FeatureServer/0/query"
)

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
    parser = argparse.ArgumentParser()
    parser.add_argument("--fire-name", default="SOBERANES", help="FIRE_NAME in the CAL FIRE FRAP dataset")
    parser.add_argument("--year", type=int, default=2016)
    args = parser.parse_args()

    print(f"[perimeter] querying CAL FIRE FRAP for {args.fire_name} {args.year}...")
    data = fetch_perimeter(args.fire_name, args.year)
    props = data["features"][0]["properties"]
    print(f"[perimeter] found: {props['FIRE_NAME']} {props['YEAR_']}, {props['GIS_ACRES']:,.0f} acres, "
          f"alarm={props['ALARM_DATE']} cont={props['CONT_DATE']}")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RAW_DIR / f"{args.fire_name.lower()}_perimeter.geojson"
    with open(out_path, "w") as f:
        json.dump(data, f)
    print(f"[perimeter] saved {out_path}")


if __name__ == "__main__":
    main()
