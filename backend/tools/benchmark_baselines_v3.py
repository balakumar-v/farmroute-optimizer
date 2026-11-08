"""
benchmark_baselines_v3.py
--------------------------
ILO v2 vs the LEGACY baselines vs the BEHAVIOURAL and RATIONAL baselines (baselines_v3.py), on the project's synthetic
scenarios. Every number is farmer-side value INCLUDING the farm-gate sale of anything the plan did not haul
(net_return_incl_farmgate), so algorithms that haul less are not penalised with Rs 0 for the rest.

Run from backend/:   python benchmark_baselines_v3.py [--n 50 300 1000] [--seeds 3]

Three views are printed:
  A. realistic accounting  (baselines: return leg charged, spoilage from pickup)
  B. like-for-like         (baselines copy ILO's accounting: no return leg, absolute-clock spoilage)
  C. farm-gate discount sensitivity (the 20% default is an ASSUMPTION)
ILO itself is identical in all views; only the baselines' accounting / the discount change.
"""
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # backend/ on the path
import argparse
import copy
import statistics

from algorithms_v2 import (
    run_ilo_v2, run_individual_transport_v2, run_proximity_pooling_v2,
)
from baselines_v3 import (
    FARMGATE_DISCOUNT, run_farmgate_baseline_v2, run_neighbour_pooling_v2, run_self_haul_v2,
    summarize_with_farmgate,
)
from logistics_lib_v2 import fresh_capacity, generate_scenario_v2


def one_scenario(n, seed, discount, match):
    farmers, fleet, markets = generate_scenario_v2(n_farmers=n, n_markets=max(3, n // 300), seed=seed)
    fs = len(fleet)
    S = lambda res: summarize_with_farmgate(res, farmers, markets, fs, discount)   # noqa: E731
    out = {
        "ILO": S(run_ilo_v2(farmers, copy.deepcopy(fleet), markets)),
        "legacy Individual": S(run_individual_transport_v2(farmers, copy.deepcopy(fleet), markets, fresh_capacity(markets))),
        "legacy Proximity": S(run_proximity_pooling_v2(farmers, copy.deepcopy(fleet), markets, fresh_capacity(markets))),
        "Farm-gate only": S(run_farmgate_baseline_v2(farmers, markets)),
        "Self-haul (behavioural)": S(run_self_haul_v2(farmers, fleet, markets, fresh_capacity(markets), discount, match)),
        "Neighbour (behavioural)": S(run_neighbour_pooling_v2(farmers, fleet, markets, fresh_capacity(markets), discount,
                                                             match_ilo_accounting=match)),
        "Self-haul (rational)": S(run_self_haul_v2(farmers, fleet, markets, fresh_capacity(markets), discount, match,
                                                   behaviour=None)),
        "Neighbour (rational)": S(run_neighbour_pooling_v2(farmers, fleet, markets, fresh_capacity(markets), discount,
                                                          match_ilo_accounting=match, behaviour=None)),
    }
    return out


def table(ns, seeds, discount, match, title):
    print(f"\n=== {title} | farm-gate discount {discount:.0%} | mean over {seeds} seeds ===")
    print(f"{'n':>5} {'algorithm':<19} {'value incl farm-gate':>21} {'of which hauled net':>20} {'spot trips':>10} {'FPO veh used':>12}")
    for n in ns:
        runs = [one_scenario(n, n * 1000 + k, discount, match) for k in range(seeds)]
        best_real = None
        for algo in runs[0]:
            v = statistics.mean(r[algo]["net_return_incl_farmgate"] for r in runs)
            h = statistics.mean(r[algo]["net_return"] for r in runs)
            st = statistics.mean(r[algo]["spot_trips"] for r in runs)
            vu = statistics.mean(r[algo]["vehicles_used"] for r in runs)
            print(f"{n:>5} {algo:<19} {v:>21,.0f} {h:>20,.0f} {st:>10.0f} {vu:>12.0f}")
            if algo not in ("ILO", "legacy Individual", "legacy Proximity"):
                best_real = v if best_real is None else max(best_real, v)
        ilo = statistics.mean(r["ILO"]["net_return_incl_farmgate"] for r in runs)
        print(f"{'':>5} ILO vs best realistic baseline: {100 * (ilo / best_real - 1):+.1f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, nargs="+", default=[50, 300, 1000])
    ap.add_argument("--seeds", type=int, default=3)
    a = ap.parse_args()
    table(a.n, a.seeds, FARMGATE_DISCOUNT, False, "A. REALISTIC accounting")
    table(a.n, a.seeds, FARMGATE_DISCOUNT, True, "B. LIKE-FOR-LIKE with ILO's accounting")
    for d in (0.10, 0.30):
        table(a.n, a.seeds, d, False, "C. SENSITIVITY")


if __name__ == "__main__":
    main()
