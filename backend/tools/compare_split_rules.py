"""compare_split_rules.py -- how much does the 'cost_aware' split change who gets what, versus the 'kg' split?

Plans are made once (the split rule does not change which trips run, only how each trip's surplus is divided), then
every hauled trip is re-split under both rules. Prints, per scenario: how many hauled farmers move by more than 5%,
mean / max absolute shift in Rs, the correlation between a farmer's pickup detour and what they gain or lose by
switching to cost_aware, and the spread of gains (Gini, minimum gain) under each rule.

  python tools/compare_split_rules.py [--n 40 150] [--seeds 3] [--presets]
Run from backend/.
"""
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # backend/ on the path
import argparse
import copy
import math

import advisor
import payout_rules as PR
from baselines_v3 import FARMGATE_DISCOUNT, FarmgatePrices
from ilo_v3 import run_ilo_v3
from logistics_lib_v2 import generate_scenario_v2


def _corr(xs, ys):
    n = len(xs)
    if n < 3:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy) if sx > 1e-12 and sy > 1e-12 else float("nan")


def compare(farmers, fleet, markets, label):
    res = run_ilo_v3(farmers, copy.deepcopy(fleet), markets)
    prices = FarmgatePrices(markets, FARMGATE_DISCOUNT)
    by_id = {f.id: f for f in farmers}
    veh = {v.id: v for v in fleet}
    kg_pay, ca_pay, detour, gains = {}, {}, {}, {"kg": [], "cost_aware": []}
    for r in res:
        if r["vehicle_id"] is None:
            continue
        order = [by_id[i] for i in r["farmer_ids"]]
        kg = PR.split_trip("kg", order, r, prices)
        ca = PR.split_trip("cost_aware", order, r, prices, veh[r["vehicle_id"]].per_km_cost)
        det, _ = PR.detours(order)
        for f in order:
            kg_pay[f.id], ca_pay[f.id], detour[f.id] = kg[f.id], ca[f.id], det[f.id]
            gains["kg"].append(kg[f.id] - prices.value(f))
            gains["cost_aware"].append(ca[f.id] - prices.value(f))
    n = len(kg_pay)
    if not n:
        print(f"{label}: no hauled farmers")
        return
    shift = {i: ca_pay[i] - kg_pay[i] for i in kg_pay}
    moved = sum(1 for i in kg_pay if abs(shift[i]) > 0.05 * max(kg_pay[i], 1.0))
    ids = list(shift)
    print(f"{label}: hauled {n}  moved>5% {moved} ({100 * moved / n:.0f}%)  mean|shift| Rs{sum(abs(v) for v in shift.values()) / n:,.0f}"
          f"  max|shift| Rs{max(abs(v) for v in shift.values()):,.0f}  corr(detour, shift) {_corr([detour[i] for i in ids], [shift[i] for i in ids]):+.2f}"
          f"  gini kg {advisor._gini(gains['kg']):.3f} -> cost_aware {advisor._gini(gains['cost_aware']):.3f}"
          f"  min gain Rs{min(gains['kg']):,.0f} -> Rs{min(gains['cost_aware']):,.0f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, nargs="+", default=[40, 150])
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--presets", action="store_true", help="also run the real-data presets in frontend/legacy/app.js")
    a = ap.parse_args()
    for n in a.n:
        for seed in range(1, a.seeds + 1):
            fa, fl, mk = generate_scenario_v2(n_farmers=n, n_markets=4, seed=seed)
            compare(fa, fl, mk, f"synthetic n={n} seed={seed}")
    if a.presets:
        from real_data.bihar_preset import load
        for key in ("bihar_dec2025_feb2026",):
            fa, fl, mk = load(key)[:3]
            compare(fa, fl, mk, f"preset {key}")


if __name__ == "__main__":
    main()
