"""Static poster of the map for LinkedIn and the README: charts/poster.png (2160 x 2700, 4:5).

Run after build_web.py and fetch.py (needs the terrain tiles):
    ../.venv/bin/python poster.py
Uses the same layers and colors as the web map in docs/.
"""
import json
import math
from pathlib import Path

import geopandas as gpd
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.path import Path as MPath
from PIL import Image
from shapely.geometry import box

matplotlib.use("Agg")
plt.rcParams["font.family"] = "Arial"

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "docs" / "data"
TILES = ROOT / "data" / "raw" / "terrain" / "8"
OUT = ROOT / "charts"
MERC = "EPSG:3857"
R = 6378137.0

# Map extent in lon/lat. Wider than OR and WA so the coast and borders have room.
EXTENT = (-126.3, 41.75, -115.5, 49.15)

LAND = np.array([244, 241, 234]) / 255
OCEAN = "#cfe0ea"
RIVER = "#8fb6cf"
INK = "#1f2328"
MUTED = "#5b636d"
DC = "#7b2cbf"
LINE500 = "#2b2d42"
SPLIT = "#a0522d"
PATH_WEST = "#b4471f"  # WECC paths over the Cascades, same as the web map
OWNERS = [  # same as docs/index.html
    ("Other", "#8c8f94", "Everyone else"),
    ("Puget Sound Energy", "#d2ad57", "Puget Sound Energy"),
    ("Brookfield Renewable", "#5fb0b3", "Brookfield"),
    ("NextEra Energy Resources", "#86b06d", "NextEra"),
    ("Portland General Electric", "#6f93c4", "Portland General"),
    ("Avangrid", "#e0482b", "Avangrid"),
]
KIND = {"Wind": "wind", "Hydro": "hydro", "Pumped storage": "hydro", "Solar": "solar",
        "Gas": "gas", "Batteries": "battery", "Nuclear": "nuclear", "Coal": "other", "Other": "other"}


# ---------- Icons as matplotlib marker paths (same shapes as the web map)
def _circle(cx, cy, r, n=24):
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.c_[cx + r * np.cos(a), cy + r * np.sin(a)]


def _rect(x0, y0, x1, y1):
    return np.array([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def _rotate(pts, angle):
    c, s = math.cos(angle), math.sin(angle)
    return pts @ np.array([[c, s], [-s, c]])


def icon(kind):
    polys = []
    if kind == "wind":
        hub = (0, 0.18)
        polys.append(_rect(-0.07, -0.5, 0.07, hub[1]))
        blade = np.array([(-0.1, 0), (0.1, 0), (0.035, 0.48), (-0.035, 0.48)])
        for i in range(3):
            polys.append(_rotate(blade, i * 2 * np.pi / 3) + hub)
        polys.append(_circle(*hub, 0.12))
    elif kind == "hydro":
        a = np.linspace(math.radians(-25), math.radians(205), 30)
        arc = np.c_[0.36 * np.cos(a), -0.12 - 0.36 * np.sin(a)][::-1]
        polys.append(np.vstack([[(0, 0.5)], arc[::-1]]))
    elif kind == "solar":
        polys.append(_circle(0, 0, 0.24))
        ray = np.array([(-0.08, 0.3), (0.08, 0.3), (0, 0.5)])
        for i in range(8):
            polys.append(_rotate(ray, i * np.pi / 4))
    elif kind == "gas":
        t = np.linspace(0, 2 * np.pi, 40)
        x = 0.32 * np.sin(t) * (1 - 0.25 * np.cos(t))
        y = -0.1 - 0.38 * np.cos(t) + 0.12 * (1 - np.cos(t)) ** 2
        polys.append(np.c_[x, y])
    elif kind == "battery":
        polys.append(_rect(-0.4, -0.22, 0.3, 0.22))
        polys.append(_rect(0.3, -0.1, 0.4, 0.1))
    elif kind == "nuclear":
        for i in range(3):
            a0 = math.pi / 2 + i * 2 * math.pi / 3
            a = np.linspace(a0 - 0.5, a0 + 0.5, 12)
            polys.append(np.vstack([[(0, 0)], np.c_[0.45 * np.cos(a), 0.45 * np.sin(a)]]))
        polys.append(_circle(0, 0, 0.1))
    else:
        polys.append(_rect(-0.3, -0.3, 0.3, 0.3))
    return MPath.make_compound_path(*[MPath(np.vstack([p, p[:1]]), closed=True) for p in polys])


ICONS = {k: icon(k) for k in set(KIND.values())}


# ---------- Projection helpers
def merc(lon, lat):
    return R * math.radians(lon), R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def tile_bounds(x, y, z=8):
    n = 2 ** z
    lon0, lon1 = x / n * 360 - 180, (x + 1) / n * 360 - 180
    lat0 = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    lat1 = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lon0, lat0, lon1, lat1


def hillshade():
    """Mosaic the Terrarium tiles and shade them. Returns an RGB image and its Mercator extent."""
    tiles = {tuple(map(int, p.stem.split("_"))): p for p in TILES.glob("*.png")}
    xs, ys = sorted({x for x, _ in tiles}), sorted({y for _, y in tiles})
    mosaic = np.zeros((256 * len(ys), 256 * len(xs)), dtype=np.float32)
    for (x, y), p in tiles.items():
        rgb = np.asarray(Image.open(p).convert("RGB"), dtype=np.float32)
        elev = rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768
        i, j = ys.index(y), xs.index(x)
        mosaic[i * 256:(i + 1) * 256, j * 256:(j + 1) * 256] = elev
    mosaic = np.maximum(mosaic, 0)  # flatten the sea floor; the ocean layer covers it anyway

    west, south, _, _ = tile_bounds(xs[0], ys[-1])
    _, _, east, north = tile_bounds(xs[-1], ys[0])
    x0, y0 = merc(west, south)
    x1, y1 = merc(east, north)
    # Ground distance per pixel shrinks with latitude on a Mercator grid.
    px = (x1 - x0) / mosaic.shape[1]
    lats = np.degrees(np.arctan(np.sinh(np.linspace(y1, y0, mosaic.shape[0]) / R)))
    ground = px * np.cos(np.radians(lats))[:, None]
    dzdy, dzdx = np.gradient(mosaic * 1.6)  # 1.6x vertical exaggeration
    dzdx, dzdy = dzdx / ground, dzdy / ground
    az, alt = math.radians(315), math.radians(45)
    slope = np.arctan(np.hypot(dzdx, dzdy))
    aspect = np.arctan2(-dzdx, dzdy)
    shade = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    shade = np.clip(shade, 0, 1)
    flat = np.sin(alt)
    tone = 1 + 0.55 * (shade - flat)  # 1 on flat ground, darker on shadowed slopes
    rgb = np.clip(LAND[None, None, :] * tone[..., None], 0, 1)
    return rgb, (x0, x1, y0, y1)


def load(name):
    return gpd.read_file(WEB / f"{name}.geojson").to_crs(MERC)


def main():
    OUT.mkdir(exist_ok=True)
    W, H = 10.8, 13.5
    fig = plt.figure(figsize=(W, H), dpi=200, facecolor="white")

    # ---------- Headline
    fig.text(0.05, 0.955, "The Northwest makes its power east of the Cascades",
             fontsize=27, fontweight="bold", color=INK, va="top")
    fig.text(0.05, 0.918, "and uses it west of them.", fontsize=27, fontweight="bold", color=INK, va="top")
    fig.text(0.05, 0.878,
             "Power plants by owner, with the two WECC paths that carry power over the mountains",
             fontsize=12.5, color=MUTED, va="top")

    # ---------- Map
    ax = fig.add_axes([0.0, 0.215, 1.0, 0.65])
    ax.set_axis_off()
    x0, y0 = merc(EXTENT[0], EXTENT[1])
    x1, y1 = merc(EXTENT[2], EXTENT[3])
    view = gpd.GeoSeries([box(EXTENT[0], EXTENT[1], EXTENT[2], EXTENT[3])], crs=4326).to_crs(MERC).iloc[0]

    rgb, ext = hillshade()
    ax.imshow(rgb, extent=ext, origin="upper", interpolation="bilinear", zorder=0)
    load("ocean").clip(view).plot(ax=ax, color=OCEAN, zorder=1, linewidth=0)
    load("lakes").clip(view).plot(ax=ax, color=OCEAN, zorder=1, linewidth=0)
    rivers = load("rivers").clip(view)
    rivers[~rivers["main"]].plot(ax=ax, color=RIVER, linewidth=0.6, zorder=2)
    rivers[rivers["main"]].plot(ax=ax, color=RIVER, linewidth=1.8, zorder=2)
    load("outside").clip(view).plot(ax=ax, color="white", alpha=0.5, zorder=3, linewidth=0)
    load("borders").clip(view).plot(ax=ax, color="#8a8f96", linewidth=0.8, linestyle=(0, (4, 3)), zorder=3)
    load("cascade_split").plot(ax=ax, color=SPLIT, linewidth=1.6, linestyle=(0, (1, 2.2)), zorder=4, alpha=0.85)

    lines = load("lines")
    lines[(lines["cur"] == "AC") & (lines["vc"] == "500")].plot(ax=ax, color=LINE500, linewidth=1.5,
                                                                 zorder=5, alpha=0.85)
    lines[lines["cur"] == "DC"].plot(ax=ax, color=DC, linewidth=2.6, linestyle=(0, (3, 1.6)), zorder=6)

    # WECC Paths 4 and 5 (West of Cascades North and South): a glow under their lines,
    # and a badge with the name and rating where each crosses the county line.
    wl = load("wecc_lines")
    wl[wl["path"].isin([4, 5])].plot(ax=ax, color=PATH_WEST, linewidth=7, alpha=0.32, zorder=4.6,
                                     capstyle="round", joinstyle="round")
    badges = load("wecc_badges")
    for b in badges[badges["path"].isin([4, 5])].itertuples():
        ax.scatter(b.geometry.x, b.geometry.y, s=330, color=PATH_WEST, edgecolors="white",
                   linewidths=1.8, zorder=11)
        ax.text(b.geometry.x, b.geometry.y, str(b.path), fontsize=10.5, fontweight="bold",
                color="white", ha="center", va="center", zorder=12)
        ax.text(b.geometry.x + 26000, b.geometry.y, f"Path {b.path}: {b.name}\n{b.mw_a} MW east to west",
                fontsize=10.5, fontweight="bold", color=PATH_WEST, va="center", zorder=12, linespacing=1.3,
                bbox=dict(facecolor="white", alpha=0.85, edgecolor="none", pad=2.5))

    # Big faded side labels.
    for lon, lat, t in [(-123.55, 42.75, "WEST"), (-118.6, 43.35, "EAST")]:
        ax.text(*merc(lon, lat), t, fontsize=40, fontweight="bold", color=SPLIT, alpha=0.22,
                ha="center", va="center", zorder=4)
    ax.text(*merc(-121.72, 46.55), "CASCADE RANGE", rotation=82, fontsize=10, color="#6b5b45",
            ha="center", va="center", zorder=4, alpha=0.9)

    # Plants: 10 MW and up, small and gray first so big and colored ones sit on top.
    plants = load("plants")
    plants = plants[plants["mw"] >= 10].copy()
    plants["kind"] = plants["type"].map(KIND)
    order = {k: i for i, (k, _, _) in enumerate(OWNERS)}
    plants["rank"] = plants["group"].map(order)
    plants = plants.sort_values(["rank", "mw"])
    colors = dict((k, c) for k, c, _ in OWNERS)
    for row in plants.itertuples():
        size = 45 + 13 * math.sqrt(row.mw)
        ax.scatter(row.geometry.x, row.geometry.y, marker=ICONS[row.kind], s=size,
                   color=colors[row.group], edgecolors="white", linewidths=0.3,
                   alpha=0.7 if row.group == "Other" else 1, zorder=7 + row.rank / 10)

    # DC Intertie: arrow off the bottom of the map.
    exit_pt = load("dc_exit").geometry.iloc[0]
    ax.text(exit_pt.x + 30000, exit_pt.y + 22000, "To Los Angeles\n846 miles, 3,220 MW",
            fontsize=12, fontweight="bold", color=DC, va="center", zorder=9,
            bbox=dict(facecolor="white", alpha=0.75, edgecolor="none", pad=2))

    cities = load("cities")
    show = ["Seattle", "Portland", "Spokane", "Tacoma", "Salem", "Eugene", "Yakima", "Kennewick", "Medford"]
    for row in cities[cities["name"].isin(show)].itertuples():
        big = row.name in ("Seattle", "Portland")
        ax.scatter(row.geometry.x, row.geometry.y, s=48 if big else 18, color=INK, edgecolors="white",
                   linewidths=1, zorder=10)
        ax.text(row.geometry.x + 9000, row.geometry.y, row.name, fontsize=15 if big else 10.5,
                fontweight="bold", color=INK, va="center", zorder=10,
                path_effects=[matplotlib.patheffects.withStroke(linewidth=3, foreground="white")])

    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")

    # ---------- Stats
    counties = pd.DataFrame([f["properties"] for f in json.loads((WEB / "counties.geojson").read_text())["features"]])
    pop = counties.groupby("side")["pop"].sum()
    plants_all = pd.DataFrame([f["properties"] for f in json.loads((WEB / "plants.geojson").read_text())["features"]])
    cap = plants_all.groupby("side")["mw"].sum()
    west_pop, west_cap = pop["West"] / pop.sum(), cap["West"] / cap.sum()
    for x, side, p, c in [(0.05, "West of the Cascades", west_pop, west_cap),
                          (0.53, "East of the Cascades", 1 - west_pop, 1 - west_cap)]:
        fig.text(x, 0.198, side.upper(), fontsize=12, fontweight="bold", color=SPLIT, va="top")
        fig.text(x, 0.172, f"{p:.0%}", fontsize=34, fontweight="bold", color=INK, va="top")
        fig.text(x + 0.12, 0.163, "of people", fontsize=13, color=MUTED, va="top")
        fig.text(x, 0.128, f"{c:.0%}", fontsize=34, fontweight="bold", color=INK, va="top")
        fig.text(x + 0.12, 0.119, "of power plant capacity", fontsize=13, color=MUTED, va="top")

    # ---------- Legend
    lg = fig.add_axes([0.05, 0.05, 0.9, 0.04])
    lg.set_axis_off()
    lg.set_xlim(0, 1)
    lg.set_ylim(0, 1)
    xx = 0.0
    for key, color, label in reversed(OWNERS):
        lg.scatter(xx + 0.008, 0.8, marker="o", s=90, color=color, edgecolors="white", linewidths=0.4)
        lg.text(xx + 0.022, 0.8, label, fontsize=10.5, va="center", color=INK,
                fontweight="bold" if key == "Avangrid" else "normal")
        xx += 0.03 + 0.0085 * len(label)
    xx = 0.0
    for kind, label in [("wind", "Wind"), ("hydro", "Hydro"), ("solar", "Solar"), ("gas", "Gas"),
                        ("battery", "Batteries"), ("nuclear", "Nuclear")]:
        lg.scatter(xx + 0.008, 0.15, marker=ICONS[kind], s=150, color="#55595f", edgecolors="white", linewidths=0.2)
        lg.text(xx + 0.022, 0.15, label, fontsize=10.5, va="center", color=INK)
        xx += 0.035 + 0.0085 * len(label)
    lg.add_line(Line2D([xx + 0.0, xx + 0.04], [0.12, 0.15], color=LINE500, lw=1.6))
    lg.text(xx + 0.047, 0.15, "500 kV AC", fontsize=10.5, va="center")
    xx += 0.13
    lg.add_line(Line2D([xx, xx + 0.04], [0.15, 0.15], color=DC, lw=2.4, linestyle=(0, (3, 1.6))))
    lg.text(xx + 0.047, 0.15, "DC", fontsize=10.5, va="center")
    xx += 0.09
    lg.add_line(Line2D([xx, xx + 0.04], [0.15, 0.15], color=PATH_WEST, lw=7, alpha=0.4, solid_capstyle="round"))
    lg.text(xx + 0.047, 0.15, "WECC path", fontsize=10.5, va="center")

    fig.text(0.05, 0.008,
             "Plants 10 MW and up, sized by nameplate capacity, colored by the parent owner of the biggest share. "
             "Sides of the Cascades are by county.\nSources: EIA-860 (2025), HIFLD and OpenStreetMap lines, "
             "Census 2025 estimates, BPA, WECC 2026 Path Rating Catalog, Natural Earth, AWS Terrain Tiles.\ngithub.com/TaborSwanson1/northwest-grid-map",
             fontsize=8.5, color=MUTED, va="bottom", linespacing=1.4)

    out = OUT / "poster.png"
    fig.savefig(out, dpi=200, facecolor="white")
    print(f"saved {out} ({west_pop:.1%} of people west, {1 - west_cap:.1%} of capacity east)")


if __name__ == "__main__":
    import matplotlib.patheffects  # noqa: F401  (used for city label halos)
    main()
