"""Hard vs soft mandi capacity (run from backend/). The scoring world has SOFT capacity: every mandi-crop keeps taking
volume up to 3x a normal day's arrivals at the falling price (1 + q/V)^-eta (eta = price-impact defaults x scale).
Planners: fixed prices + hard cap (today's default) | price impact + hard cap | price impact + soft cap (matches the world).
All are scored with true_price_impact = the soft world; gain = final value minus the farm-gate-only value.
Also prints the same planners in a HARD-cap world, to show what the cap assumption alone is worth."""
import sys, copy, time
from collections import defaultdict
sys.path.insert(0, '.')
import ilo_v3 as I, baselines_v3 as B
from price_impact import PriceImpact
from logistics_lib_v2 import generate_scenario_v2
from real_data.bihar_preset import load

SCEN = [("bihar", lambda: load("bihar_dec2025_feb2026")), ("bengaluru", lambda: load("karnataka_bengaluru")),
        ("aligarh", lambda: load("up_aligarh"))] + [("synth150x3 s%d" % s, (lambda s=s: generate_scenario_v2(n_farmers=150, n_markets=3, seed=s))) for s in (1, 2)]
tot = defaultdict(float)
for sname, mk in SCEN:
    f, fl, m = mk()
    prices = B._as_prices(m, B.FARMGATE_DISCOUNT, None); fg = sum(prices.value_of([x]) for x in f)
    for scale in (1.0, 3.5):
        for wname, mult in (("soft world", 3.0), ("hard world", None)):
            truth = PriceImpact(scale=scale, capacity_multiple=mult)
            for pname, belief in (("fixed+hard", None), ("impact+hard", PriceImpact(scale=scale)),
                                  ("impact+soft", PriceImpact(scale=scale, capacity_multiple=3.0))):
                if wname == "hard world" and pname == "impact+soft":
                    continue
                t0 = time.time()
                res, meta = I.run_ilo_v3(f, copy.deepcopy(fl), m, return_meta=True, price_impact=belief, true_price_impact=truth)
                g = meta["final_value"] - fg
                tot[(sname, scale, wname, pname)] = g
                print(sname, "eta x%.1f" % scale, wname, pname, round(g), meta["chosen"], round(time.time() - t0), "s", flush=True)
print("\nscenario | eta | world | gain: fixed+hard | impact+hard | impact+soft  (soft-aware vs fixed+hard)")
for sname, _ in SCEN:
    for scale in (1.0, 3.5):
        for wname in ("soft world", "hard world"):
            a = tot[(sname, scale, wname, "fixed+hard")]; b = tot[(sname, scale, wname, "impact+hard")]
            c = tot.get((sname, scale, wname, "impact+soft"))
            print("%-14s x%.1f %-10s %9d %9d %s" % (sname, scale, wname, a, b,
                  ("%9d  (%+.1f%% vs fixed+hard, %+.1f%% vs impact+hard)" % (c, 100 * (c / a - 1), 100 * (c / b - 1))) if c is not None else "-"))
