"""Turn the clean data into small GeoJSON files for the web map in docs/data.

Run after plants.py and lines.py: ../.venv/bin/python build_web.py
Geometry is clipped to the map's view box, simplified and rounded so the page loads fast.
"""
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import box, mapping

from plants import WEST

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
CLEAN = ROOT / "data" / "clean"
OUT = ROOT / "docs" / "data"
NE = RAW / "natural_earth"

VIEW = box(-131.0, 38.5, -110.0, 52.5)  # covers everything the map can pan to (maxBounds)
METERS = "EPSG:5070"

# Owner colors on the map: Avangrid plus the four biggest wind, solar and battery
# owners in OR and WA (data/clean/plant_owners.csv). Everyone else is "Other".
TOP_PARENTS = ["Avangrid", "Portland General Electric", "NextEra Energy Resources",
               "Brookfield Renewable", "Puget Sound Energy"]


def ne(name):
    return gpd.read_file(f"zip://{NE / name}.zip").to_crs(4326)


def census(name):
    return gpd.read_file(f"zip://{RAW / name}").to_crs(4326)


def write(gdf, name, tolerance=None, digits=4, keep=None):
    """Clip, simplify and save. Tolerance is in degrees (0.001 is about 100 m)."""
    gdf = gdf.copy()
    if keep is not None:
        gdf = gdf[keep + ["geometry"]]
    gdf["geometry"] = gdf.geometry.intersection(VIEW)
    gdf = gdf[gdf.geometry.notna()]
    gdf = gdf[~gdf.geometry.is_empty]
    if tolerance:
        gdf["geometry"] = gdf.geometry.simplify(tolerance, preserve_topology=True)
    gdf["geometry"] = gdf.geometry.set_precision(10 ** -digits)
    gdf = gdf[~gdf.geometry.is_empty]
    features = []
    for row in gdf.itertuples(index=False):
        props = {k: (None if pd.isna(v) else v) for k, v in row._asdict().items() if k != "geometry"}
        features.append({"type": "Feature", "properties": props, "geometry": mapping(row.geometry)})
    path = OUT / f"{name}.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features},
                               separators=(",", ":")))
    print(f"{name}: {len(features)} features, {path.stat().st_size / 1e6:.2f} MB")


def base():
    land = ne("ne_10m_land").clip(VIEW).union_all()
    write(gpd.GeoDataFrame(geometry=[VIEW.difference(land)], crs=4326), "ocean", 0.005)
    lakes = ne("ne_10m_lakes")
    write(lakes, "lakes", 0.002, keep=["name"])
    rivers = pd.concat([ne("ne_10m_rivers_lake_centerlines"), ne("ne_10m_rivers_north_america")])
    rivers = rivers[rivers["featurecla"].str.contains("River|Lake Centerline", na=False)]
    rivers["main"] = rivers["name"].isin(["Columbia", "Snake", "Willamette"])
    write(rivers, "rivers", 0.002, keep=["name", "main"])
    write(ne("ne_10m_admin_1_states_provinces_lines"), "borders", 0.002, keep=[])

    st = census("cb_2024_us_state_5m.zip")
    orwa = st[st["STUSPS"].isin(["OR", "WA"])]
    write(gpd.GeoDataFrame(geometry=[VIEW.difference(orwa.union_all())], crs=4326), "outside", 0.002)

    # Counties with 2025 population, and the line between west and east counties.
    co = census("cb_2024_us_county_5m.zip")
    co = co[co["STUSPS"].isin(["OR", "WA"])].copy()
    pop = pd.read_csv(RAW / "co-est2025-alldata.csv", encoding="latin-1")
    pop = pop[(pop["SUMLEV"] == 50) & pop["STNAME"].isin(["Oregon", "Washington"])]
    pop["GEOID"] = pop["STATE"].astype(str).str.zfill(2) + pop["COUNTY"].astype(str).str.zfill(3)
    co = co.merge(pop[["GEOID", "POPESTIMATE2025"]], on="GEOID", validate="one_to_one")
    co["side"] = ["West" if n in WEST[s] else "East" for s, n in zip(co["STUSPS"], co["NAME"])]
    co["pop"] = co["POPESTIMATE2025"]
    co["density"] = (co["pop"] / (co.to_crs(METERS).area / 2.59e6)).round(1)  # people per sq mile
    co["name"] = co["NAME"] + " County, " + co["STUSPS"]
    write(co, "counties", 0.002, keep=["name", "side", "pop", "density"])
    split = co[co["side"] == "West"].union_all().boundary.intersection(
        co[co["side"] == "East"].union_all().boundary)
    write(gpd.GeoDataFrame(geometry=[split], crs=4326), "cascade_split", 0.002)
    s = co.groupby("side")["pop"].sum()
    print(f"population west share: {s['West'] / s.sum():.3f}")

    places = ne("ne_10m_populated_places_simple")
    places = places[(places["adm0name"] == "United States of America") &
                    places["adm1name"].isin(["Oregon", "Washington"])]
    places = places.sort_values("pop_max", ascending=False).head(14)
    places["big"] = places["name"].isin(["Portland", "Seattle"])
    write(places, "cities", keep=["name", "pop_max", "big"])


def plants():
    p = pd.read_csv(CLEAN / "plants.csv")
    o = pd.read_csv(CLEAN / "plant_owners.csv")
    owners = (o.sort_values("mw", ascending=False).groupby(["plant_code", "type"])
              .apply(lambda d: "; ".join(f"{r.parent} ({r.mw / d.mw.sum():.0%})" if len(d) > 1
                                         else r.parent for r in d.itertuples()),
                     include_groups=False).rename("owners"))
    p = p.merge(owners, left_on=["plant_code", "type"], right_index=True)
    p["group"] = p["main_parent"].where(p["main_parent"].isin(TOP_PARENTS), "Other")
    p["mw"] = p["mw"].round(0)
    p["year"] = p["first_year"].astype("Int64").astype(str)
    p.loc[p["first_year"] != p["last_year"], "year"] = (
        p["first_year"].astype("Int64").astype(str) + " to " + p["last_year"].astype("Int64").astype(str))
    g = gpd.GeoDataFrame(p, geometry=gpd.points_from_xy(p["lon"], p["lat"]), crs=4326)
    g = g.rename(columns={"plant_name": "name"}).sort_values("mw")  # big plants draw on top
    write(g, "plants", keep=["name", "type", "mw", "group", "owners", "operator", "year",
                             "county", "state", "side"])
    print(g.groupby("group")["mw"].sum().round(0).to_dict())


def grid():
    lines = gpd.read_file(CLEAN / "lines.geojson")
    lines = lines.rename(columns={"volt_class": "vc", "current": "cur", "source": "src"})
    lines["kv"] = lines["kv"].round(0)
    write(lines, "lines", 0.0005, keep=["name", "vc", "cur", "kv", "owner", "sub_1", "sub_2", "src"])

    # Where the DC Intertie leaves Oregon, for the "to Los Angeles" label.
    st = census("cb_2024_us_state_5m.zip")
    oregon = st[st["STUSPS"] == "OR"].union_all()
    dc = lines[lines["cur"] == "DC"].union_all()
    exit_pt = dc.intersection(oregon.boundary)
    exit_pt = min(getattr(exit_pt, "geoms", [exit_pt]), key=lambda pt: pt.y)
    print(f"DC Intertie leaves Oregon at {exit_pt.x:.3f}, {exit_pt.y:.3f}")
    write(gpd.GeoDataFrame({"label": ["To Los Angeles: 846 miles, 3,220 MW"]},
                           geometry=[exit_pt], crs=4326), "dc_exit")

    subs = gpd.read_file(CLEAN / "substations.geojson")
    subs = subs[subs["kv"] >= 230].copy()
    subs["kv"] = subs["kv"].round(0)
    write(subs, "substations", keep=["name", "operator", "kv"])


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    base()
    plants()
    grid()
