"""Clean transmission lines (HIFLD) and substations (OpenStreetMap) for Oregon and Washington.

Outputs in data/clean:
- lines.geojson: every HIFLD line in the map box, with voltage class, AC or DC,
  owner, and the voltage OpenStreetMap shows along the same route.
- osm_500kv_not_in_hifld.geojson: 500 kV routes in OpenStreetMap with no HIFLD
  line nearby. These are candidates for lines built after HIFLD's last check (2018).
- substations.geojson: OpenStreetMap substations with their highest voltage.

How the cross-check works: put a point every 500 m along each HIFLD line, find the
nearest OpenStreetMap line within 150 m, and take the most common voltage among
those matches. A line counts as matched when at least half its points find one.
"""
import json
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
CLEAN = ROOT / "data" / "clean"
METERS = "EPSG:5070"  # equal-area projection in meters, for distances
STEP = 500       # meters between sample points
NEAR = 150       # meters: how close an OSM line has to be to count as the same route

CLASS_ORDER = ["UNDER 100", "100-161", "220-287", "345", "500", "DC", "NOT AVAILABLE"]


def states():
    path = RAW / "cb_2024_us_state_5m.zip"
    st = gpd.read_file(f"zip://{path}")
    return st[st["STUSPS"].isin(["OR", "WA"])].to_crs(4326)


def osm_kv(tag):
    """Highest voltage in an OSM voltage tag, in kV. '500000;230000' -> 500."""
    if not tag:
        return np.nan
    vals = []
    for part in str(tag).replace(",", ";").split(";"):
        part = part.strip().lstrip("±")
        if part.isdigit():
            vals.append(int(part) / 1000)
    return max(vals) if vals else np.nan


def osm_class(kv, dc):
    if dc:
        return "DC"
    if np.isnan(kv):
        return "NOT AVAILABLE"
    if kv < 100:
        return "UNDER 100"
    if kv <= 161:
        return "100-161"
    if kv <= 287:
        return "220-287"
    if kv <= 345:
        return "345"
    return "500"


def load_osm_lines():
    elements = json.loads((RAW / "osm_lines.json").read_text())["elements"]
    rows = []
    for e in elements:
        pts = [(g["lon"], g["lat"]) for g in e.get("geometry", []) if g]
        if len(pts) < 2:
            continue
        t = e["tags"]
        kv = osm_kv(t.get("voltage"))
        dc = t.get("frequency") == "0"
        rows.append({"osm_id": e["id"], "osm_kv": kv, "osm_class": osm_class(kv, dc),
                     "osm_name": t.get("name"), "osm_operator": t.get("operator"),
                     "geometry": LineString(pts)})
    return gpd.GeoDataFrame(rows, crs=4326)


def sample_points(gdf, id_col):
    """Points every STEP meters along each line, tagged with the line's id."""
    rows = []
    for i, geom in zip(gdf[id_col], gdf.geometry):
        n = max(int(geom.length // STEP), 1)
        for d in np.linspace(0, geom.length, n + 1):
            rows.append({id_col: i, "geometry": geom.interpolate(d)})
    return gpd.GeoDataFrame(rows, crs=gdf.crs)


def cross_check(hifld_m, osm_m):
    pts = sample_points(hifld_m, "line_id")
    hit = gpd.sjoin_nearest(pts, osm_m[["osm_class", "osm_kv", "geometry"]],
                            max_distance=NEAR, how="left")
    hit = hit[~hit.index.duplicated()]  # ties: keep one match per point
    total = hit.groupby("line_id").size()
    matched = hit.dropna(subset=["osm_class"])
    share = (matched.groupby("line_id").size() / total).fillna(0)
    mode = matched.groupby("line_id")["osm_class"].agg(lambda s: s.mode().iloc[0])
    out = pd.DataFrame({"osm_match_share": share.round(2), "osm_class": mode})
    out.loc[out["osm_match_share"] < 0.5, "osm_class"] = None
    return out


def lines():
    h = gpd.read_file(RAW / "hifld_lines.geojson")
    h = h.explode(index_parts=False).reset_index(drop=True)
    h["line_id"] = h["ID"].astype(str) + "_" + h.groupby("ID").cumcount().astype(str)
    h["volt_class"] = h["VOLT_CLASS"]
    h["kv"] = h["VOLTAGE"].where(h["VOLTAGE"] > 0)
    h["current"] = np.where(h["volt_class"] == "DC", "DC", "AC")
    h["fix"] = ""

    st = states()
    h["in_or_wa"] = h.intersects(st.union_all())

    osm = load_osm_lines()
    h_m, osm_m = h.to_crs(METERS), osm.to_crs(METERS)
    check = cross_check(h_m, osm_m)
    h = h.merge(check, left_on="line_id", right_index=True, how="left")
    h["osm_match_share"] = h["osm_match_share"].fillna(0)

    # Fix: HIFLD lines tagged DC that OpenStreetMap shows as AC on the same route.
    bad_dc = (h["volt_class"] == "DC") & h["osm_class"].notna() & (h["osm_class"] != "DC")
    for i in h.index[bad_dc]:
        h.loc[i, "fix"] = f"HIFLD says DC {h.loc[i, 'kv']:.0f} kV; OSM shows {h.loc[i, 'osm_class']} AC"
        h.loc[i, "volt_class"] = h.loc[i, "osm_class"]
        h.loc[i, "current"] = "AC"
    # Pacific DC Intertie: HIFLD's 1,000 kV is +500 and -500 kV added together.
    pdci = (h["volt_class"] == "DC") & (h["kv"] == 1000)
    h.loc[pdci, "kv"] = 500
    h.loc[pdci, "fix"] = "HIFLD lists 1,000 kV (pole to pole); labeled ±500 kV DC"
    h["name"] = np.where(pdci, "Pacific DC Intertie (Celilo to Sylmar)", "")

    keep = ["line_id", "name", "volt_class", "kv", "current", "OWNER", "SUB_1", "SUB_2",
            "STATUS", "in_or_wa", "osm_class", "osm_match_share", "fix", "geometry"]
    h = h[keep].rename(columns={"OWNER": "owner", "SUB_1": "sub_1", "SUB_2": "sub_2",
                                "STATUS": "status"})
    h["source"] = "HIFLD"
    h["length_km"] = (h.to_crs(METERS).length / 1000).round(1)

    # Report.
    w = h[h["in_or_wa"]]
    print(f"{len(h)} line pieces in the box, {len(w)} touch OR or WA")
    km = w.groupby("volt_class")["length_km"].sum().reindex(CLASS_ORDER).dropna().round(0)
    print("km by class (touching OR or WA):", km.to_dict())
    m = w[w["osm_class"].notna()]
    agree = (m["osm_class"] == m["volt_class"])
    print(f"matched to OSM: {len(m)} of {len(w)} ({len(m)/len(w):.0%}); "
          f"same voltage class: {agree.mean():.0%}")
    print(pd.crosstab(m["volt_class"], m["osm_class"]).to_string())
    print("fixes:", h.loc[h["fix"] != "", ["line_id", "owner", "fix"]].to_string())

    # OSM 500 kV and DC routes with no HIFLD line of the same class nearby.
    hv = h_m.merge(h[["line_id", "volt_class"]].rename(columns={"volt_class": "vc"}), on="line_id")
    hv = hv[hv["vc"].isin(["500", "DC"])]
    big = osm_m[osm_m["osm_class"].isin(["500", "DC"])].copy()
    pts = sample_points(big, "osm_id")
    near = gpd.sjoin_nearest(pts, hv[["geometry"]], max_distance=300, how="left")
    near = near[~near.index.duplicated()]
    miss_share = near.groupby("osm_id")["index_right"].apply(lambda s: s.isna().mean())
    gap = big[big["osm_id"].isin(miss_share[miss_share > 0.5].index)].to_crs(4326)
    gap["length_km"] = (gap.to_crs(METERS).length / 1000).round(1)
    gap.to_file(CLEAN / "osm_500kv_not_in_hifld.geojson", driver="GeoJSON")
    print(f"OSM 500 kV/DC pieces with no HIFLD match: {len(gap)}, {gap['length_km'].sum():.0f} km")
    print(gap.groupby(["osm_name", "osm_operator"], dropna=False)["length_km"].sum()
          .sort_values(ascending=False).head(12).round(1).to_string())

    # Add the real gaps to the map from OSM. Skip test lines and tiny unnamed pieces.
    name = gap["osm_name"].fillna("")
    real = gap[~name.str.contains("Test|Experimental") & ((name != "") | (gap["length_km"] > 1))]
    add = gpd.GeoDataFrame({
        "line_id": "osm_" + real["osm_id"].astype(str),
        "name": real["osm_name"].str.replace("​", "").str.strip(),
        "volt_class": real["osm_class"], "kv": real["osm_kv"],
        "current": np.where(real["osm_class"] == "DC", "DC", "AC"),
        "owner": real["osm_operator"].fillna("Bonneville Power Administration (per OSM name)"),
        "sub_1": None, "sub_2": None, "status": "IN SERVICE (OSM)", "in_or_wa": True,
        "osm_class": real["osm_class"], "osm_match_share": 1.0,
        "fix": "Not in HIFLD; added from OpenStreetMap", "source": "OpenStreetMap",
        "length_km": real["length_km"], "geometry": real.geometry}, crs=4326)
    out = pd.concat([h, add], ignore_index=True)
    out.to_file(CLEAN / "lines.geojson", driver="GeoJSON")
    print(f"added {len(add)} OSM pieces ({add['length_km'].sum():.0f} km): "
          f"{sorted(set(add['name'].dropna()))}")


def substations():
    elements = json.loads((RAW / "osm_substations.json").read_text())["elements"]
    rows = []
    for e in elements:
        c = e.get("center") or {"lat": e.get("lat"), "lon": e.get("lon")}
        if c.get("lat") is None:
            continue
        t = e["tags"]
        rows.append({"osm_id": f"{e['type']}/{e['id']}", "name": t.get("name"),
                     "operator": t.get("operator"), "voltage_tag": t.get("voltage"),
                     "kv": osm_kv(t.get("voltage")), "substation": t.get("substation"),
                     "geometry": Point(c["lon"], c["lat"])})
    s = gpd.GeoDataFrame(rows, crs=4326)
    s.to_file(CLEAN / "substations.geojson", driver="GeoJSON")
    print(f"{len(s)} substations; with voltage: {s['kv'].notna().sum()}; "
          f"500 kV: {(s['kv'] >= 500).sum()}; 230 to 345 kV: {s['kv'].between(230, 345).sum()}")
    print(s[s["kv"] >= 500].sort_values("name")[["name", "operator"]].to_string())


if __name__ == "__main__":
    CLEAN.mkdir(parents=True, exist_ok=True)
    lines()
    substations()
