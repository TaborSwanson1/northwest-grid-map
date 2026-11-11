"""Trace WECC paths onto the map's lines and place a badge for each one.

Inputs (data/reference):
- wecc_paths.csv: number, name, ratings, revision date and catalog page for each path,
  from WECC's 2026 Path Rating Catalog (public version, V3, April 2026).
- wecc_path_lines.csv: the lines WECC lists as making up each path.

Each listed line is traced through the HIFLD line pieces as the shortest route between
its two substations, using only pieces at the listed voltage. Lines that can't be
traced (a substation outside the map or missing from HIFLD) are reported, not guessed.

Outputs: docs/data/wecc_lines.geojson, docs/data/wecc_badges.geojson,
data/clean/wecc_trace.csv (which listed lines were found).
"""
import heapq
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point, mapping
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "data" / "reference"
CLEAN = ROOT / "data" / "clean"
WEB = ROOT / "docs" / "data"
RAW = ROOT / "data" / "raw"

KV_CLASS = {"500": "500", "345": "345", "230": "220-287", "115": "100-161", "DC": "DC"}
BAD_NODE = ("NOT AVAILABLE", "UNKNOWN")
MAX_KM = 1500  # the DC Intertie is about 1,366 km

RANK = {"DC": 5, "500": 4, "345": 3, "220-287": 2, "100-161": 1}

# Path 8's listed lines are all in Montana, east of the map. Its badge goes at the
# Idaho panhandle, where that power heads toward Spokane.
MANUAL_BADGE = {8: (-116.25, 47.7)}


def matches(name, pattern):
    if pattern.endswith("*"):
        return name.startswith(pattern[:-1])
    return name == pattern


def graph(lines):
    """Adjacency list: substation -> [(neighbor, km, row index)], one graph per voltage class."""
    g = {}
    for i, r in lines.iterrows():
        a, b = r["sub_1"], r["sub_2"]
        if not isinstance(a, str) or not isinstance(b, str):  # OSM-added lines have no endpoints
            continue
        if a.startswith(BAD_NODE) or b.startswith(BAD_NODE):
            continue
        cls = g.setdefault(r["volt_class"], {})
        cls.setdefault(a, []).append((b, r["length_km"], i))
        cls.setdefault(b, []).append((a, r["length_km"], i))
    return g


def trace(g, start_pat, end_pat):
    """Shortest route (by km) from any node matching start to any node matching end."""
    starts = [n for n in g if matches(n, start_pat)]
    ends = {n for n in g if matches(n, end_pat)}
    if not starts or not ends:
        return None
    best = {n: 0.0 for n in starts}
    prev = {}
    heap = [(0.0, n) for n in starts]
    while heap:
        d, n = heapq.heappop(heap)
        if d > best.get(n, float("inf")) or d > MAX_KM:
            continue
        if n in ends:
            rows = []
            while n in prev:
                n, i = prev[n]
                rows.append(i)
            return rows, d
        for m, km, i in g.get(n, []):
            nd = d + km
            if nd < best.get(m, float("inf")):
                best[m] = nd
                prev[m] = (n, i)
                heapq.heappush(heap, (nd, m))
    return None


def badge_point(geom, path, split, borders):
    """Where the path crosses the line it's named for."""
    if path in MANUAL_BADGE:
        return Point(MANUAL_BADGE[path])
    target = split if path in (4, 5) else borders.get(path)
    if target is not None and geom is not None:
        hit = geom.intersection(target)
        pts = [p for p in getattr(hit, "geoms", [hit]) if not p.is_empty]
        if pts:
            return Point(sum(p.centroid.x for p in pts) / len(pts), sum(p.centroid.y for p in pts) / len(pts))
    return geom.representative_point() if geom is not None else None


def main():
    lines = gpd.read_file(CLEAN / "lines.geojson")
    paths = pd.read_csv(REF / "wecc_paths.csv", dtype=str)
    wanted = pd.read_csv(REF / "wecc_path_lines.csv", dtype=str)
    g = graph(lines)

    traced, report = {}, []
    for r in wanted.itertuples():
        cls = KV_CLASS[r.kv]
        found = trace(g.get(cls, {}), r.from_sub, r.to_sub)
        report.append({"path": r.path, "line": r.catalog_text, "found": found is not None,
                       "pieces": len(found[0]) if found else 0, "km": round(found[1], 1) if found else None})
        if found:
            for i in found[0]:
                traced.setdefault(i, set()).add(int(r.path))
    # Path 66: HIFLD has "NOT AVAILABLE" in place of Malin and Captain Jack on these lines,
    # so they can't be traced by name. WECC defines the path as the three 500 kV AC lines
    # into California (Malin-Round Mountain 1 and 2, Captain Jack-Olinda). Exactly three
    # 500 kV lines cross the Oregon-California border, so tag those.
    border_ca = LineString([(-124.3, 42.0), (-120.0, 42.0)])
    coi = lines[(lines["volt_class"] == "500") & lines.intersects(border_ca)]
    assert len(coi) == 3, f"expected 3 COI lines across the OR-CA border, found {len(coi)}"
    for i in coi.index:
        traced.setdefault(i, set()).add(66)
    for rec in report:
        if rec["path"] == "66":
            rec.update(found=True, pieces=len(coi) if "2 lines" in rec["line"] else 1,
                       km=None)
    rep = pd.DataFrame(report)
    rep.to_csv(CLEAN / "wecc_trace.csv", index=False)
    print(rep.to_string(index=False))

    # One feature per traced line piece, tagged with its path.
    feats = []
    meta = paths.set_index("path")
    for i, ps in traced.items():
        for p in sorted(ps):
            m = meta.loc[str(p)]
            geom = lines.geometry[i].simplify(0.0005)
            feats.append({"type": "Feature", "geometry": mapping(geom),
                          "properties": {"path": p, "group": m["group"]}})
    WEB.joinpath("wecc_lines.geojson").write_text(json.dumps(
        {"type": "FeatureCollection", "features": feats}, separators=(",", ":")))

    # Reference lines for badge placement.
    split = gpd.read_file(WEB / "cascade_split.geojson").union_all()
    st = gpd.read_file(f"zip://{RAW / 'cb_2024_us_state_5m.zip'}").to_crs(4326).set_index("STUSPS")
    orwa = unary_union([st.geometry["OR"], st.geometry["WA"]])
    borders = {3: LineString([(-124, 49.0), (-116, 49.0)]),
               14: orwa.boundary.intersection(st.geometry["ID"].buffer(0.01)),
               65: orwa.boundary.intersection(st.geometry["NV"].buffer(0.01)),
               66: orwa.boundary.intersection(st.geometry["CA"].buffer(0.01))}

    badges = []
    for r in paths.itertuples():
        p = int(r.path)
        rows = [i for i, ps in traced.items() if p in ps]
        # Place the badge on the highest-voltage lines, so Path 3 sits on the 500 kV
        # crossing at Custer rather than halfway to the 230 kV one at Boundary.
        if rows:
            top = max(RANK[lines.at[i, "volt_class"]] for i in rows)
            rows = [i for i in rows if RANK[lines.at[i, "volt_class"]] == top]
        geom = unary_union([lines.geometry[i] for i in rows]) if rows else None
        pt = badge_point(geom, p, split, borders)
        assert pt is not None, f"no badge spot for path {p}"
        lines_listed = wanted[wanted["path"] == r.path]["catalog_text"].tolist()
        found = rep[rep["path"] == r.path]["found"]
        props = {k: getattr(r, k) for k in ["name", "group", "dir_a", "mw_a", "dir_b", "mw_b",
                                            "revised", "catalog_page", "why"]}
        props.update({"path": p, "lines": "|".join(lines_listed),
                      "traced": f"{int(found.sum())} of {len(found)}"})
        badges.append({"type": "Feature", "geometry": mapping(pt), "properties": props})
        print(f"Path {p}: badge at {pt.x:.2f}, {pt.y:.2f}; traced {props['traced']} listed lines")
    WEB.joinpath("wecc_badges.geojson").write_text(json.dumps(
        {"type": "FeatureCollection", "features": badges}, separators=(",", ":")))


if __name__ == "__main__":
    main()
