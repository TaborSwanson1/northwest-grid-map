"""Add population and electricity facts to the map's cities: docs/data/cities.geojson.

Run after build_web.py. Cities don't report their own power use, so each city gets the
facts for the utility that serves most of it (data/reference/city_utilities.csv).
The utility's numbers cover its whole service area in that state, not just the city.

- Population: Census 2025 estimates for the incorporated city.
- Customers, sales, residential price: EIA-861 2025, sales to ultimate customers.
- Peak demand: EIA-861 2025 operational data. For utilities in more than one state
  (PacifiCorp, Avista) EIA reports one system-wide peak, and the card says so.
- Outage minutes: EIA-861 2025 reliability, SAIDI without major event days.
Each city-utility match is checked against EIA's service territory list (the utility
must serve the city's county), and the script stops if one fails.
"""
import json
from pathlib import Path

import pandas as pd

from plants import WEST

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
E861 = RAW / "eia861"
WEB = ROOT / "docs" / "data"
REF = ROOT / "data" / "reference"
STATE_NAME = {"OR": "Oregon", "WA": "Washington"}


def num(x):
    v = pd.to_numeric(x, errors="coerce")
    return None if pd.isna(v) else float(v)


def main():
    ref = pd.read_csv(REF / "city_utilities.csv")

    # Check each match against EIA's service territory list.
    terr = pd.read_excel(E861 / "Service_Territory_2025.xlsx")
    served = set(zip(terr["Utility Number"], terr["State"], terr["County"]))
    for r in ref.itertuples():
        assert (r.utility_number, r.state, r.county) in served, \
            f"{r.utility} isn't listed as serving {r.county} County, {r.state}"
    print(f"all {len(ref)} city-utility matches serve the city's county")

    # Sales: bundled (part A) plus delivery-only (part C) customers in that state.
    s = pd.read_excel(E861 / "Sales_Ult_Cust_2025.xlsx", header=2)
    s = s[s["Part"].isin(["A", "C"])]
    s = s.rename(columns={"Thousand Dollars": "res_rev", "Megawatthours": "res_mwh", "Count": "res_cust",
                          "Megawatthours.4": "mwh", "Count.4": "cust"})
    for c in ["res_rev", "res_mwh", "res_cust", "mwh", "cust"]:
        s[c] = pd.to_numeric(s[c], errors="coerce")
    bundled = s[s["Part"] == "A"].groupby(["Utility Number", "State"])[["res_rev", "res_mwh"]].sum()
    total = s.groupby(["Utility Number", "State"])[["mwh", "cust", "res_mwh"]].sum()
    states_per_utility = s.groupby("Utility Number")["State"].nunique()

    op = pd.read_excel(E861 / "Operational_Data_2025.xlsx", header=2)
    op = op.groupby("Utility Number")[["Summer Peak Demand", "Winter Peak Demand"]].max()

    rel = pd.read_excel(E861 / "Reliability_2025.xlsx", header=2)
    rel = rel.iloc[:, [1, 3, 8]]
    rel.columns = ["Utility Number", "State", "saidi"]
    rel["saidi"] = pd.to_numeric(rel["saidi"], errors="coerce")
    rel = rel.groupby(["Utility Number", "State"])["saidi"].first()

    pops = []
    for fips in ("41", "53"):
        p = pd.read_csv(RAW / f"sub-est2025_{fips}.csv", encoding="latin-1")
        pops.append(p[p["SUMLEV"] == 162])  # incorporated places
    pop = pd.concat(pops)
    pop = pop.set_index(["STNAME", "NAME"])["POPESTIMATE2025"]

    cities = json.loads((WEB / "cities.geojson").read_text())
    for f in cities["features"]:
        props = f["properties"]
        r = ref[ref["city"] == props["name"]]
        assert len(r) == 1, f"no utility listed for {props['name']}"
        r = r.iloc[0]
        key = (r.utility_number, r.state)
        t, b = total.loc[key], bundled.loc[key]
        multi = states_per_utility[r.utility_number] > 1
        peak = op.loc[r.utility_number]
        city_pop = pop.get((STATE_NAME[r.state], f"{r.city} city"))
        assert city_pop is not None, f"no Census population for {r.city}"
        props.update({
            "state": r.state,
            "side": "West" if r.county in WEST[r.state] else "East",
            "city_pop": int(city_pop),
            "utility": r.utility,
            "utility_note": r.note if isinstance(r.note, str) else "",
            "customers": int(t["cust"]),
            "sales_twh": round(t["mwh"] / 1e6, 1),
            "res_share": round(t["res_mwh"] / t["mwh"], 2),
            "res_cents": round(b["res_rev"] * 1000 / (b["res_mwh"] * 1000) * 100, 1),
            "summer_peak": num(peak["Summer Peak Demand"]),
            "winter_peak": num(peak["Winter Peak Demand"]),
            "peak_system_wide": bool(multi),
            "saidi": num(rel.get(key)),
        })
        print(f"{r.city:10s} {r.utility:30s} pop {int(city_pop):>8,} cust {int(t['cust']):>9,} "
              f"{t['mwh'] / 1e6:5.1f} TWh  res {props['res_cents']:5.1f}c  "
              f"peak S {props['summer_peak']} W {props['winter_peak']}{' (system)' if multi else ''}  "
              f"SAIDI {props['saidi']}")
    (WEB / "cities.geojson").write_text(json.dumps(cities, separators=(",", ":")))


if __name__ == "__main__":
    main()
