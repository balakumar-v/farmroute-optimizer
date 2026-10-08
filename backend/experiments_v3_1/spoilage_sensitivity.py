"""Does the spoilage model's parameters change ILO's conclusions? (run from backend/)
For each spoilage variant T the whole pipeline (ILO v3 + baselines) is planned AND scored under T.
Reported per variant, summed over seeds:
  gain          ILO final value minus the farm-gate-only value
  lead_vs_best  ILO final value over the best baseline (self-haul / neighbour / farm-gate, behavioural and rational)
  chosen        how often ILO's own plan (not a fallback baseline) was returned
  jaccard       overlap of farmers hauled with the nominal-spoilage plan
  regret        gain lost by running the NOMINAL plan's pools under T instead of T's own plan (both re-costed the
                same way, so hint/vehicle-assignment artefacts cancel)
"""
import sys, copy, time
sys.path.insert(0, '.')
import logistics_lib_v2 as L, ilo_v3 as I, baselines_v3 as B, algorithms_v2 as A
from logistics_lib_v2 import generate_scenario_v2, spoilage_params
VARIANTS = [("nominal", 1.0, 3.0, 0.6), ("rate x0.5", 0.5, 3.0, 0.6), ("rate x2", 2.0, 3.0, 0.6),
            ("rate x4", 4.0, 3.0, 0.6), ("unrefrig mult 1.5", 1.0, 1.5, 0.6), ("unrefrig mult 6", 1.0, 6.0, 0.6),
            ("rate x2 + mult 6", 2.0, 6.0, 0.6)]
SEEDS = range(1, 5)


def recost(f, fl, m, prices, pools, hints):
    """Execute a plan's pools with ITS vehicles and start hours (pool_hints) under the current spoilage model."""
    out = A.run_our_system_v2(f, copy.deepcopy(fl), m, raw_pools_override=pools, pool_hints=hints,
                              withhold_uneconomic=False, fix_route_duration=True, spoilage_from_pickup=True,
                              charge_return_leg=True)
    by = {x.id: x for x in f}
    return sum(r["net_return"] - prices.value_of([by[i] for i in r["farmer_ids"]]) for r in out if r["vehicle_id"] is not None)


tot = {}
for seed in SEEDS:
    f, fl, m = generate_scenario_v2(n_farmers=80, n_markets=3, seed=seed)
    by = {x.id: x for x in f}
    prices = B._as_prices(m, B.FARMGATE_DISCOUNT, None)
    fg = sum(prices.value_of([x]) for x in f)
    plans = {}
    for name, rs, um, cap in VARIANTS:
        t0 = time.time()
        with spoilage_params(rs, um, cap):
            res, meta = I.run_ilo_v3(f, copy.deepcopy(fl), m, return_meta=True)
        pv = meta["plan_values"]
        own = max(v for k, v in pv.items() if not k.startswith("fallback"))
        base = max(v for k, v in pv.items() if k.startswith("fallback"))
        hauled = {i for r in res if r["vehicle_id"] is not None for i in r["farmer_ids"]}
        trips = [r for r in res if r["vehicle_id"] is not None]
        pools = [[by[i] for i in r["farmer_ids"]] for r in trips]
        hints = {frozenset(r["farmer_ids"]): {"vehicle_id": r["vehicle_id"], "start": r["dispatch_hr"]} for r in trips}
        plans[name] = (pools, hauled, hints)
        a = tot.setdefault(name, dict(gain=0.0, lead=0.0, own=0, n=0, jac=0.0, regret=0.0, trips=0))
        a["gain"] += meta["final_value"] - fg; a["lead"] += meta["final_value"] / base - 1
        a["own"] += meta["chosen"] != "baseline" and not meta["chosen"].startswith("fallback"); a["n"] += 1
        a["trips"] += len(pools)
        nom_h = plans["nominal"][1]
        a["jac"] += len(hauled & nom_h) / max(1, len(hauled | nom_h))
        with spoilage_params(rs, um, cap):
            g_t = recost(f, fl, m, prices, pools, hints)
            g_nom = recost(f, fl, m, prices, plans["nominal"][0], plans["nominal"][2])
        a["regret"] += (g_t - g_nom) / g_t if g_t > 0 else 0.0
        print(seed, name, "gain", round(meta["final_value"] - fg), "chosen", meta["chosen"], "trips", len(pools),
              "regret %.3f" % ((g_t - g_nom) / g_t if g_t > 0 else 0), round(time.time() - t0), "s", flush=True)
print("variant              gain(sum)  lead_vs_best(avg)  own_plan_chosen  trips  jaccard_vs_nominal  regret_of_nominal_plan(avg)")
for name, a in tot.items():
    print("%-20s %9d  %+.2f%%            %d/%d            %3d    %.2f              %+.1f%%" % (
        name, a["gain"], 100 * a["lead"] / a["n"], a["own"], a["n"], a["trips"], a["jac"] / a["n"], 100 * a["regret"] / a["n"]))
