"""
milp_benchmark.py
------------------
Small-instance benchmark: exact Integrated MILP vs. ILO (the heuristic,
formerly "Our System"). Deliberately tiny (n=5,6,7) -- see
docs/MILP_GROUND_TRUTH.md for why this is the honestly-supportable range for
the current candidate-enumeration implementation, and what "gap" means
precisely when the solver doesn't reach proven optimality in time.
"""
import time
import copy
import pandas as pd

from logistics_lib_v2 import generate_scenario_v2
from integrated_milp import build_and_solve_milp
from algorithms_v2 import run_ilo_v2, summarize

N_VALUES = [5, 6, 7]
TRIALS_PER_N = 3
TIME_LIMIT = 45


def main():
    rows = []
    for n in N_VALUES:
        for trial in range(TRIALS_PER_N):
            seed = n * 1000 + trial
            farmers, fleet, markets = generate_scenario_v2(n_farmers=n, n_markets=2, seed=seed)

            t0 = time.time()
            milp_res = build_and_solve_milp(farmers, fleet, markets, time_limit=TIME_LIMIT)
            t_milp = time.time() - t0

            ilo_res = run_ilo_v2(farmers, copy.deepcopy(fleet), markets)
            ilo_summary = summarize(ilo_res, n, len(fleet))

            proven = milp_res["status"] == "optimal"
            ratio = (ilo_summary["net_return"] / milp_res["net_return"]
                     if milp_res["net_return"] and milp_res["net_return"] > 0 else None)
            rows.append({
                "n_farmers": n, "seed": seed,
                "milp_status": milp_res["status"], "milp_proven_optimal": proven,
                "milp_net_return": milp_res["net_return"], "milp_mip_gap": milp_res["mip_gap"],
                "milp_runtime_sec": t_milp, "milp_n_candidates": milp_res["n_candidates"],
                "ilo_net_return": ilo_summary["net_return"],
                "ilo_over_milp_pct": ratio * 100 if ratio is not None else None,
            })
            gap_str = "proven_optimal" if proven else f"gap={milp_res['mip_gap']:.3f}"
            print(f"n={n} seed={seed}: MILP={milp_res['net_return']:.1f} ({gap_str}, {t_milp:.1f}s)  "
                  f"ILO={ilo_summary['net_return']:.1f}  "
                  f"ILO/MILP={(ratio*100 if ratio else float('nan')):.1f}%")

    df = pd.DataFrame(rows)
    df.to_csv("milp_vs_ilo_results.csv", index=False)
    print("\nWrote milp_vs_ilo_results.csv")
    proven_df = df[df.milp_proven_optimal]
    if len(proven_df):
        print(f"\nProven-optimal instances: {len(proven_df)}/{len(df)}")
        print(f"ILO/MILP ratio on proven-optimal instances: "
              f"mean={proven_df.ilo_over_milp_pct.mean():.1f}%  "
              f"min={proven_df.ilo_over_milp_pct.min():.1f}%  "
              f"max={proven_df.ilo_over_milp_pct.max():.1f}%")


if __name__ == "__main__":
    main()
