"""Build one row per plant and type for Oregon and Washington from EIA-860 (2025).

Output: data/clean/plants.csv and data/clean/plant_owners.csv

- Type groups the EIA technology names into the icons the map uses.
- Side is east or west of the Cascades, by county (see WEST below).
- Owner MW splits jointly owned generators by percent owned. Generators with
  ownership "S" (single) aren't in the owner file; their owner is the operator.
- Parent comes from data/reference/parents.csv. Owners not listed there keep
  their own name as parent.
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "eia860"
CLEAN = ROOT / "data" / "clean"
REF = ROOT / "data" / "reference"
STATES = ["OR", "WA"]

# Counties west of the Cascade crest. Everything else in OR and WA is east.
WEST = {
    "OR": ["Clatsop", "Columbia", "Tillamook", "Washington", "Multnomah", "Clackamas",
           "Yamhill", "Polk", "Marion", "Lincoln", "Benton", "Linn", "Lane", "Coos",
           "Douglas", "Curry", "Josephine", "Jackson"],
    "WA": ["Clallam", "Jefferson", "Kitsap", "Mason", "Grays Harbor", "Pacific",
           "Wahkiakum", "Cowlitz", "Clark", "Skamania", "Lewis", "Thurston", "Pierce",
           "King", "Snohomish", "Skagit", "Whatcom", "Island", "San Juan"],
}


def side(state, county):
    return "West" if county in WEST[state] else "East"


def type_group(tech):
    if tech == "Conventional Hydroelectric":
        return "Hydro"
    if tech == "Hydroelectric Pumped Storage":
        return "Pumped storage"
    if "Wind" in tech:
        return "Wind"
    if "Solar" in tech:
        return "Solar"
    if "Batter" in tech:
        return "Batteries"
    if "Natural Gas" in tech:
        return "Gas"
    if tech == "Nuclear":
        return "Nuclear"
    if "Coal" in tech:
        return "Coal"
    return "Other"


def load():
    gen = pd.read_excel(RAW / "3_1_Generator_Y2025.xlsx", header=1)
    gen = gen[gen["State"].isin(STATES)].copy()
    plant = pd.read_excel(RAW / "2___Plant_Y2025.xlsx", header=1)
    plant = plant[plant["State"].isin(STATES)][["Plant Code", "County", "Latitude", "Longitude"]]
    owner = pd.read_excel(RAW / "4___Owner_Y2025.xlsx", header=1)
    owner = owner[["Plant Code", "Generator ID", "Owner Name", "Percent Owned"]].copy()
    owner["Percent Owned"] = pd.to_numeric(owner["Percent Owned"], errors="coerce")
    return gen, plant, owner


def main():
    gen, plant, owner = load()
    # The generator file has its own County column; use the plant file's.
    gen = gen.drop(columns="County").merge(plant, on="Plant Code", how="left",
                                           validate="many_to_one")
    assert gen["County"].notna().all(), "every generator should have a county"
    assert gen[["Latitude", "Longitude"]].notna().all().all(), "every plant should have coordinates"
    gen["type"] = gen["Technology"].map(type_group)
    gen["side"] = [side(s, c) for s, c in zip(gen["State"], gen["County"])]
    gen["mw"] = gen["Nameplate Capacity (MW)"]

    # Owner shares for each generator. Single-owner generators belong to the operator.
    own = gen.merge(owner, on=["Plant Code", "Generator ID"], how="left")
    own["Owner Name"] = own["Owner Name"].fillna(own["Utility Name"])
    own["Percent Owned"] = own["Percent Owned"].fillna(1.0)
    shares = own.groupby(["Plant Code", "Generator ID"])["Percent Owned"].sum()
    bad = shares[(shares - 1).abs() > 0.01]
    assert bad.empty, f"owner shares don't add to 100%: {bad.head()}"
    own["owner_mw"] = own["mw"] * own["Percent Owned"]

    parents = pd.read_csv(REF / "parents.csv")
    own = own.merge(parents[["owner_name", "parent"]], left_on="Owner Name",
                    right_on="owner_name", how="left")
    own["parent"] = own["parent"].fillna(own["Owner Name"])

    keys = ["Plant Code", "type"]
    owners = (own.groupby(keys + ["Owner Name", "parent"], as_index=False)["owner_mw"].sum()
              .rename(columns={"Owner Name": "owner", "owner_mw": "mw"}))
    owners["mw"] = owners["mw"].round(1)
    owners = owners.sort_values(keys + ["mw"], ascending=[True, True, False])

    # Plant label for the map: the parent with the biggest share.
    top = (owners.groupby(keys + ["parent"], as_index=False)["mw"].sum()
           .sort_values("mw", ascending=False).drop_duplicates(keys)
           .rename(columns={"parent": "main_parent", "mw": "main_parent_mw"}))

    plants = (gen.groupby(keys, as_index=False)
              .agg(plant_name=("Plant Name", "first"), state=("State", "first"),
                   county=("County", "first"), side=("side", "first"),
                   lat=("Latitude", "first"), lon=("Longitude", "first"),
                   operator=("Utility Name", "first"), mw=("mw", "sum"),
                   generators=("Generator ID", "count"),
                   first_year=("Operating Year", "min"), last_year=("Operating Year", "max")))
    plants = plants.merge(top, on=keys, validate="one_to_one")
    plants["main_parent_share"] = (plants["main_parent_mw"] / plants["mw"]).round(3)
    plants = plants.drop(columns="main_parent_mw").rename(columns={"Plant Code": "plant_code"})
    plants["mw"] = plants["mw"].round(1)
    plants = plants.sort_values("mw", ascending=False)

    # Checks against the generator file.
    assert abs(plants["mw"].sum() - gen["mw"].sum()) < 1
    assert abs(owners["mw"].sum() - gen["mw"].sum()) < 1

    CLEAN.mkdir(parents=True, exist_ok=True)
    plants.to_csv(CLEAN / "plants.csv", index=False)
    owners.rename(columns={"Plant Code": "plant_code"}).to_csv(CLEAN / "plant_owners.csv", index=False)

    print(f"{len(plants)} plant-type rows, {plants['plant_code'].nunique()} plants, "
          f"{plants['mw'].sum():,.0f} MW")
    by = plants.pivot_table(index="type", columns="side", values="mw", aggfunc="sum").fillna(0)
    by["east_share"] = by["East"] / (by["East"] + by["West"])
    print(by.round(2).sort_values("East", ascending=False))
    total = plants.groupby("side")["mw"].sum()
    print("east share of all MW:", round(total["East"] / total.sum(), 3))


if __name__ == "__main__":
    main()
