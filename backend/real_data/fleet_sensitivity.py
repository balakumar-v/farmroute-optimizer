"""
fleet_sensitivity.py
--------------------
Fleet size is an ASSUMPTION (no public data), and results depend on it strongly. This
reloads the same real markets + the same synthetic farmers at several fleet sizes, runs
/plan/compute each time, and prints one comparison table (and optional CSV) for your report.

  python real_data/fleet_sensitivity.py                      # multipliers 1 2 3 5, API on :8000
  python real_data/fleet_sensitivity.py --multipliers 1 2 4 --csv fleet_sensitivity.csv

WARNING: it POSTs /reset for every row, so it wipes whatever is currently loaded. Re-run
load_real_scenario.py afterwards to leave the app on the fleet size you choose.
Note: the model charges nothing for idle vehicles, so a bigger fleet never costs extra here.
"""
import argparse
import csv
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # backend/
from load_real_scenario import make_farmers_and_fleet, select_markets  # noqa: E402
from common import REAL_MARKETS_JSON  # noqa: E402

ALGOS = (("integrated_logistics_optimization", "ILO"), ("individual_transport", "Individual"),
         ("proximity_pooling", "Proximity"))


def load(c, chosen, farmers, comp):
    c.post("/reset").raise_for_status()
    for m in chosen:
        c.post("/markets", json={"lat": m["lat"], "lng": m["lng"], "price": m["price"],
                                 "capacity_kg": m["capacity_kg"]}).raise_for_status()
    for f in farmers:
        c.post("/farmers", json={"lat": f.lat, "lng": f.lng, "crop": f.crop, "qty_kg": round(f.qty_kg, 1),
                                 "ready_hr": round(f.ready_hr, 2), "deadline_hr": round(f.deadline_hr, 2)}
               ).raise_for_status()
    for t, n in comp.items():
        if n:
            c.post("/vehicles", json={"type_name": t, "count": n}).raise_for_status()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--json", default=str(REAL_MARKETS_JSON))
    ap.add_argument("--anchor", default="25.60,84.90")
    ap.add_argument("--n-farmers", type=int, default=120, help="requested; only farmers whose crop is quoted are kept")
    ap.add_argument("--max-markets", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--multipliers", type=int, nargs="+", default=[1, 2, 3, 5])
    ap.add_argument("--csv", default=None)
    args = ap.parse_args(argv)

    data = json.loads(Path(args.json).read_text())
    anchor = tuple(float(x) for x in args.anchor.split(","))
    chosen = select_markets(data["markets"], anchor, args.max_markets)
    if not chosen:
        sys.exit("No usable markets in the JSON.")

    rows = []
    with httpx.Client(base_url=args.api, timeout=120) as c:
        for mult in args.multipliers:
            farmers, comp = make_farmers_and_fleet(chosen, anchor, args.n_farmers, args.seed, mult)
            if not farmers:
                sys.exit("No synthetic farmer grows a crop that the chosen markets quote.")
            load(c, chosen, farmers, comp)
            r = c.post("/plan/compute", json={})
            r.raise_for_status()
            res = r.json()
            ilo = res["integrated_logistics_optimization"]["summary"]
            row = {"fleet_multiplier": mult, "vehicles": sum(comp.values()), "farmers": len(farmers),
                   "ILO_net_rs": round(ilo["net_return"]), "ILO_net_per_farmer_rs": round(ilo["net_return_per_farmer"]),
                   "ILO_pct_served": round(ilo["pct_qty_served"], 1), "ILO_vehicles_used": ilo["vehicles_used"],
                   "ILO_no_truck_kg": round(ilo["total_unserved_no_vehicle_kg"]), "ILO_unsold_kg": round(ilo["total_unsold_kg"]),
                   "ILO_spoilage_kg": round(ilo["total_spoilage_kg"])}
            for key, name in ALGOS[1:]:
                s = res[key]["summary"]
                row[f"{name}_net_rs"] = round(s["net_return"])
                row[f"{name}_pct_served"] = round(s["pct_qty_served"], 1)
            rows.append(row)

    hdr = f"{'fleet x':>7} {'veh':>4} | {'ILO net':>9} {'served':>7} {'no-truck kg':>11} {'unsold kg':>9} | {'Indiv net':>9} {'served':>7} | {'Prox net':>9} {'served':>7}"
    print(hdr + "\n" + "-" * len(hdr))
    for r in rows:
        print(f"{r['fleet_multiplier']:>7} {r['vehicles']:>4} | {r['ILO_net_rs']:>9,} {r['ILO_pct_served']:>6}% "
              f"{r['ILO_no_truck_kg']:>11,} {r['ILO_unsold_kg']:>9,} | {r['Individual_net_rs']:>9,} "
              f"{r['Individual_pct_served']:>6}% | {r['Proximity_net_rs']:>9,} {r['Proximity_pct_served']:>6}%")
    print(f"\n{rows[0]['farmers']} synthetic farmers; real markets from {args.json}. Last row is left loaded in the API.")
    if args.csv:
        with open(args.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print("CSV ->", args.csv)


if __name__ == "__main__":
    main()
