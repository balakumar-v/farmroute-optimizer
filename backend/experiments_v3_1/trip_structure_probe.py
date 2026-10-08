"""Is a richer trip structure worth building? (run from backend/) Four cheap probes on ILO v3's candidate set,
all measured as the fleet-blind set-partition objective (total gain over the farm gate; no code in ilo_v3 changed):
  capacity x3   re-generate candidates and re-solve with every mandi-crop capacity tripled. Upper bound on what
                splitting loads across mandis (multi-mandi trips) could ever add.
  top-K = all   remove the "each farmer sees only their 3 best mandis" cut (needs more mandis than 3 to matter).
  mixed-crop    add Clarke-Wright trips that mix crops of the same refrigeration class (today: one crop per route).
  binding       share of chosen (mandi, crop) pairs filled to >= 90% of capacity, and of chosen trips sitting on them.
"""
import sys, copy, dataclasses, time
from collections import defaultdict
import numpy as np
sys.path.insert(0, '.')
import ilo_v3 as I, baselines_v3 as B
from logistics_lib_v2 import generate_scenario_v2


def solve(cands, markets):
    chosen, _ = I.solve_set_partition(cands, markets)
    return chosen, sum(c["delta"] for c in chosen)


sys.path.insert(0, 'experiments_v3_1')
from _trip_helpers import add_mixed   # noqa: E402


def with_mixed(cands, farmers, fleet, markets, prices):
    before = len(cands)
    out = add_mixed(dict(cands), farmers, fleet, markets, prices)
    return out, len(out) - before


rows = {}
for n in (80, 150, 300):
    for nm in (3, 8):
        acc = defaultdict(list)
        for seed in (1, 2, 3):
            t0 = time.time()
            f, fl, m = generate_scenario_v2(n_farmers=n, n_markets=nm, seed=seed)
            prices = B._as_prices(m, B.FARMGATE_DISCOUNT, None)
            cands, _ = I.generate_candidates(f, fl, m, prices, 0.0)
            chosen, base = solve(cands, m)
            # binding
            used = defaultdict(float)
            for c in chosen:
                for crop, q in c["qty_by_crop"].items():
                    used[(c["market"].id, crop)] += q
            cap = {(x.id, crop): x.capacity_kg[crop] for x in m for crop in x.capacity_kg}
            full = {k for k, q in used.items() if q >= 0.9 * cap[k]}
            acc["keys_full"].append(len(full) / max(1, len(used)))
            acc["trips_on_full"].append(sum(1 for c in chosen if any((c["market"].id, cr) in full for cr in c["qty_by_crop"])) / max(1, len(chosen)))
            acc["multi_crop_chosen"].append(sum(1 for c in chosen if len(c["qty_by_crop"]) > 1) / max(1, len(chosen)))
            acc["base"].append(base)
            # capacity x3
            m3 = [dataclasses.replace(x, capacity_kg={c: v * 3 for c, v in x.capacity_kg.items()}) for x in m]
            c3, _ = I.generate_candidates(f, fl, m3, prices, 0.0)
            acc["cap3"].append(solve(c3, m3)[1] / base - 1)
            # top-K all
            old = I.CW_TOP_MARKETS; I.CW_TOP_MARKETS = 99
            ck, _ = I.generate_candidates(f, fl, m, prices, 0.0); I.CW_TOP_MARKETS = old
            acc["topk"].append(solve(ck, m)[1] / base - 1)
            # mixed crop
            cm, added = with_mixed(cands, f, fl, m, prices)
            ch_m, obj_m = solve(cm, m)
            acc["mixed"].append(obj_m / base - 1)
            acc["mixed_added"].append(added)
            acc["mixed_chosen"].append(sum(1 for c in ch_m if c["source"] == "cw_mixed"))
            print(n, nm, seed, "base %d" % base, "cap3 %+.1f%%" % (100 * acc["cap3"][-1]), "topk %+.1f%%" % (100 * acc["topk"][-1]),
                  "mixed %+.1f%% (added %d, chosen %d)" % (100 * acc["mixed"][-1], added, acc["mixed_chosen"][-1]), round(time.time() - t0), "s", flush=True)
        rows[(n, nm)] = acc
print("\n n  mandis | base gain | cap x3 | top-K all | mixed-crop | keys>=90% full | trips on full keys | multi-crop trips already chosen")
for (n, nm), a in rows.items():
    print("%3d %3d   | %9d | %+5.1f%% | %+5.1f%%    | %+5.1f%%    | %4.0f%%          | %4.0f%%               | %4.0f%%" % (
        n, nm, np.mean(a["base"]), 100 * np.mean(a["cap3"]), 100 * np.mean(a["topk"]), 100 * np.mean(a["mixed"]),
        100 * np.mean(a["keys_full"]), 100 * np.mean(a["trips_on_full"]), 100 * np.mean(a["multi_crop_chosen"])))
