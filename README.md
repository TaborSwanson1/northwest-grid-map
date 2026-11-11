# Power Over the Cascades

**Finding:** 76% of Oregon and Washington's power plant capacity is east of the Cascades, and 81% of their people live west of them. Two WECC transmission paths carry the power over the mountains, rated at 10,700 MW and 7,200 MW.

**[Open the interactive map](https://taborswanson1.github.io/northwest-grid-map/)**: zoom in, filter by plant type or voltage, and click any plant, line, path or city for details.

![Poster](charts/poster.png)

## The question

Where does the Northwest make its power, where does it use it, and what connects the two? This is the second part of my [grid bottleneck project](https://github.com/TaborSwanson1/grid-bottleneck), which looked at data center demand and how long it takes to connect new power. This part zooms in on one region and the wires themselves.

## What I found

**1. The power is east and the people are west.** Of 50,752 MW of power plant capacity in the two states, 38,669 MW is east of the Cascades. Of 12.3 million people, 9.9 million live west of them.

| Type | East | West | Share east |
|---|---|---|---|
| Hydro | 24,821 MW | 5,001 MW | 83% |
| Wind | 7,426 MW | 142 MW | 98% |
| Gas | 3,416 MW | 4,982 MW | 41% |
| Solar | 1,320 MW | 243 MW | 84% |
| Nuclear | 1,200 MW | 0 | 100% |
| Batteries | 31 MW | 496 MW | 6% |

Gas and batteries are the exception. Most of them sit on the west side, near the cities.

**2. Two paths do most of the crossing.** WECC, the group that runs reliability for the western grid, groups the lines over the Cascades into two paths. Path 4 (West of Cascades North) feeds Seattle and Puget Sound and is rated at 10,700 MW. Path 5 (West of Cascades South) feeds Portland and the Willamette Valley and is rated at 7,200 MW. That's 17,900 MW of east-to-west capacity. The map traces 8 of the 8 lines WECC lists for Path 4 and 11 of the 12 for Path 5.

**3. Some of it keeps going to California.** The Pacific DC Intertie (Path 65) runs 846 miles from Celilo, near The Dalles, to Sylmar, near Los Angeles, and is rated at 3,220 MW north to south. The California-Oregon Intertie (Path 66) is three 500 kV AC lines into Northern California, rated at 4,800 MW north to south.

**4. Avangrid is the biggest wind and solar owner in the two states.** It owns 2,286 MW, or 24% of all wind, solar and battery capacity in Oregon and Washington. All of it is east of the Cascades, in Sherman, Gilliam, Klickitat, Wasco and Crook counties. Most sits near the Columbia, on the east side of Path 5.

| Parent company | Wind, solar and batteries |
|---|---|
| Avangrid | 2,286 MW |
| Portland General Electric | 1,110 MW |
| NextEra Energy Resources | 1,082 MW |
| Brookfield Renewable | 845 MW |
| Puget Sound Energy | 774 MW |

NextEra owns its projects through five different companies (Stateline, Vansycle II, Wheatridge, Wheatridge East and the Sundial battery). Adding them up moves it from sixth to third.

**5. The west side peaks in winter.** Seattle City Light, Puget Sound Energy and Snohomish PUD all hit their highest demand in winter, likely from electric heat. Portland General Electric and Benton PUD peak in summer. Each city card on the map shows its utility's peak and the season it hits.

## Data

| What | Source | Script |
|---|---|---|
| Power plants, owners | EIA-860, 2025 | `plants.py` |
| Parent companies | One source per row in `data/reference/parents.csv` | `plants.py` |
| Transmission lines | HIFLD, archived copy (US government data, last checked 2014 to 2018) | `lines.py` |
| Newer lines, substations, cross-check | OpenStreetMap contributors, ODbL | `lines.py` |
| Transmission paths and ratings | WECC 2026 Path Rating Catalog, public version (V3, April 2026) | `wecc.py` |
| Utility customers, sales, peaks, outages | EIA-861, 2025 | `cities.py` |
| Population | Census Bureau county and city estimates, 2025 | `build_web.py`, `cities.py` |
| Boundaries | Census Bureau cartographic boundary files, 2024 | `build_web.py` |
| Land, water, cities | Natural Earth | `build_web.py` |
| Terrain | AWS Terrain Tiles | `poster.py`, web map |

## Method

- **East or west** is by county. The 18 Oregon and 19 Washington counties west of the Cascade crest count as west. This puts Bonneville Dam (Multnomah County) on the west side and The Dalles and John Day dams on the east side.
- **Owners** come from EIA-860's owner file. Jointly owned plants are split by percent owned. Each project company is tied to its parent with a source. On the map, a plant takes the color of the parent with the biggest share.
- **Lines** come from HIFLD. I checked every line against OpenStreetMap by putting a point every 500 m along it and finding the nearest OpenStreetMap line within 150 m. 85% of HIFLD lines in the two states match a route, and 74% of those have the same voltage. At 500 kV, 144 of 158 matched pieces agree. The other 14 are short pieces at the Grand Coulee and Chief Joseph switchyards, where 500 and 230 kV lines run side by side.
- **Fixes:** four Tacoma Power lines that HIFLD calls DC are 230 kV AC in OpenStreetMap, so I recoded them. BPA's Big Eddy to Knight 500 kV line is missing from HIFLD, so I added it from OpenStreetMap.
- **WECC paths** are traced as the shortest route between the two substations of each line WECC lists, using only lines at that voltage. Path 66 is the exception. HIFLD has "NOT AVAILABLE" where Malin should be, so I tagged the three 500 kV lines that cross into California, which matches WECC's definition.
- **City cards** use the utility that serves most of each city. Every match is checked against EIA-861's list of counties each utility serves.

## Limits

- **Capacity isn't output.** These are nameplate ratings. Wind and hydro run well below nameplate most of the time, so a split by actual generation (EIA-923) would look different.
- **Path ratings are limits, not flows.** A rating is the most a path can carry under study conditions. It doesn't say how full the lines are on a given day.
- **The county split is rough.** The Cascade crest doesn't follow county lines, and Hood River and Skamania counties sit right in the Gorge.
- **HIFLD was last checked in 2018.** I added the one 500 kV line I found missing, but smaller lines built since then may not be on the map.
- **Population stands in for use.** I don't have electricity use by county.
- **City numbers are utility numbers.** Cities don't report their own power use. Each card covers the utility's whole service area in that state, so Portland and Salem show the same PGE figures. PacifiCorp and Avista report one peak for their whole multi-state system.
- **Some owners are unresolved.** Windy Flats, Washington Wind and White Creek stay under their project names because sources disagree on the parent. Arlington Wind is matched to EDP Renewables by county and size only.
- **Some path lines aren't traced.** Path 14 shows 1 of its 5 listed lines (the 500 kV one). Path 8's lines are all in Montana, off the map, so its badge marks where that power heads in.

## How to run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cd src
../.venv/bin/python fetch.py     # downloads raw data into data/raw
../.venv/bin/python plants.py    # data/clean/plants.csv, plant_owners.csv
../.venv/bin/python lines.py     # data/clean/lines.geojson, substations.geojson
../.venv/bin/python build_web.py # docs/data, the layers the web map loads
../.venv/bin/python wecc.py      # WECC paths traced onto the lines, plus badges
../.venv/bin/python cities.py    # city cards: population and each city's utility
../.venv/bin/python poster.py    # charts/poster.png
```

The web map is `docs/index.html`. To view it locally, serve the folder (`python3 -m http.server --directory docs`) and open the address it prints.

Daily notes are in `log.md`.

## Credits

Power plants and utility data: EIA. Transmission lines: HIFLD and © OpenStreetMap contributors (ODbL). Path ratings: WECC. Population and boundaries: US Census Bureau. Base map: Natural Earth. Terrain: AWS Terrain Tiles. Map library: MapLibre GL JS.
