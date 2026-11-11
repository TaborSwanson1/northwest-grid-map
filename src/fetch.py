"""Download every raw file the map uses and save it untouched in data/raw.

Run from src: ../.venv/bin/python fetch.py
Files that already exist are skipped. Pass --force to download again.
"""
import io
import json
import sys
import time
import zipfile
from pathlib import Path

import requests

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
UA = {"User-Agent": "northwest-grid-map/0.1 (public data research project)"}
FORCE = "--force" in sys.argv

# Box around Oregon and Washington with a little margin, in lon/lat.
BBOX = {"xmin": -125.0, "ymin": 41.9, "xmax": -116.4, "ymax": 49.1}

EIA860 = "https://www.eia.gov/electricity/data/eia860/xls/eia8602025.zip"
CENSUS_POP = ("https://www2.census.gov/programs-surveys/popest/datasets/"
              "2020-2025/counties/totals/co-est2025-alldata.csv")
CENSUS_STATES = "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_state_5m.zip"
CENSUS_COUNTIES = "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_county_5m.zip"
# HIFLD transmission lines, archived copy on ArcGIS Online (US government data, no longer updated).
HIFLD_LINES = ("https://services2.arcgis.com/FiaPA4ga0iQKduv3/arcgis/rest/services/"
               "US_Electric_Power_Transmission_Lines/FeatureServer/0/query")
OVERPASS = "https://overpass-api.de/api/interpreter"
# Natural Earth (public domain): land, water and cities for the base map.
NE_URL = "https://naciscdn.org/naturalearth/10m/{kind}/{name}.zip"
NATURAL_EARTH = {
    "ne_10m_land": "physical",
    "ne_10m_lakes": "physical",
    "ne_10m_rivers_lake_centerlines": "physical",
    "ne_10m_rivers_north_america": "physical",
    "ne_10m_populated_places_simple": "cultural",
    "ne_10m_admin_1_states_provinces_lines": "cultural",
}


def need(path):
    if path.exists() and not FORCE:
        print(f"skip {path.relative_to(RAW)}")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    return True


def get(url, **kw):
    r = requests.get(url, headers=UA, timeout=300, **kw)
    r.raise_for_status()
    return r


def save_bytes(path, url):
    if need(path):
        path.write_bytes(get(url).content)
        print(f"saved {path.relative_to(RAW)}")


def eia860():
    out = RAW / "eia860"
    if not need(out / "3_1_Generator_Y2025.xlsx"):
        return
    z = zipfile.ZipFile(io.BytesIO(get(EIA860).content))
    for name in ["2___Plant_Y2025.xlsx", "3_1_Generator_Y2025.xlsx", "4___Owner_Y2025.xlsx"]:
        (out / name).write_bytes(z.read(name))
    print("saved eia860 plant, generator and owner files")


def hifld_lines():
    path = RAW / "hifld_lines.geojson"
    if not need(path):
        return
    features, offset = [], 0
    while True:
        params = {
            "where": "1=1",
            "geometry": json.dumps({**BBOX, "spatialReference": {"wkid": 4326}}),
            "geometryType": "esriGeometryEnvelope",
            "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "*",
            "outSR": 4326,
            "resultOffset": offset,
            "resultRecordCount": 1000,
            "f": "geojson",
        }
        page = get(HIFLD_LINES, params=params).json()
        batch = page.get("features", [])
        features += batch
        print(f"  hifld lines: {len(features)}")
        if len(batch) < 1000:
            break
        offset += 1000
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    print(f"saved {path.relative_to(RAW)} ({len(features)} lines)")


def overpass(path, query):
    if not need(path):
        return
    for attempt in range(3):
        r = requests.post(OVERPASS, data={"data": query}, headers=UA, timeout=400)
        if r.status_code == 200:
            path.write_bytes(r.content)
            print(f"saved {path.relative_to(RAW)}")
            return
        print(f"  overpass {r.status_code}, retrying")
        time.sleep(30)
    r.raise_for_status()


AREA = '(area["ISO3166-2"="US-OR"];area["ISO3166-2"="US-WA"];)->.a;'

# OpenStreetMap: every power line in OR and WA with geometry, for checking HIFLD.
OSM_LINES = f'[out:json][timeout:300];{AREA}way["power"="line"](area.a);out tags geom;'
# OpenStreetMap: every substation in OR and WA, with a center point.
OSM_SUBS = f'[out:json][timeout:300];{AREA}nwr["power"="substation"](area.a);out tags center;'


# Elevation tiles (AWS Terrain Tiles, Terrarium encoding) for the poster's hillshade.
TERRAIN_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
TERRAIN_ZOOM = 8
TERRAIN_BOX = (-125.4, 41.6, -116.0, 49.4)  # lon/lat, a bit past OR and WA


def tile_xy(lon, lat, z):
    """Web Mercator tile that contains a lon/lat point."""
    import math
    n = 2 ** z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


def terrain():
    z = TERRAIN_ZOOM
    x0, y0 = tile_xy(TERRAIN_BOX[0], TERRAIN_BOX[3], z)
    x1, y1 = tile_xy(TERRAIN_BOX[2], TERRAIN_BOX[1], z)
    todo = [(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]
    got = 0
    for x, y in todo:
        path = RAW / "terrain" / str(z) / f"{x}_{y}.png"
        if path.exists() and not FORCE:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(get(TERRAIN_URL.format(z=z, x=x, y=y)).content)
        got += 1
    print(f"terrain z{z}: {len(todo)} tiles ({got} downloaded)")


if __name__ == "__main__":
    eia860()
    terrain()
    save_bytes(RAW / "co-est2025-alldata.csv", CENSUS_POP)
    save_bytes(RAW / "cb_2024_us_state_5m.zip", CENSUS_STATES)
    save_bytes(RAW / "cb_2024_us_county_5m.zip", CENSUS_COUNTIES)
    for name, kind in NATURAL_EARTH.items():
        save_bytes(RAW / "natural_earth" / f"{name}.zip", NE_URL.format(kind=kind, name=name))
    hifld_lines()
    overpass(RAW / "osm_lines.json", OSM_LINES)
    overpass(RAW / "osm_substations.json", OSM_SUBS)
