"""
benchmark_v2.py
----------------
Two things this measures, matching what was asked for:
  1. Does the redesigned algorithm stay COMPUTATIONALLY efficient as
     farmer/truck/market counts grow? (wall-clock time vs n)
  2. Does it still WIN economically once real fleet constraints, a
     wider service area, and elastic market pricing are in play?
     (net return & % of volume served vs the two baselines)

Baselines got the same two structural fixes (real finite fleet with
multi-trip reuse, fleet-aware pool sizing) so the comparison isn't
just "fixed vs still-broken" -- Integrated Logistics Optimization's edge
is specifically the mixed-crop pooling + LP-optimal, multi-market,
never-trade-at-a-loss allocation, exactly as before.
"""
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # backend/ on the path
import time
import copy
import statistics
import pandas as pd

from logistics_lib_v2 import generate_scenario_v2, fresh_capacity
from algorithms_v2 import (
    run_ilo_v2, run_individual_transport_v2, run_proximity_pooling_v2, summarize,
)

N_VALUES = [50, 100, 300, 600, 1000, 2000, 4000, 6000, 8000, 10000]
TRIALS_PER_N = 5


def n_markets_for(n):
    return max(3, n // 300)


def run_all(seed, n):
    farmers, fleet, markets = generate_scenario_v2(n_farmers=n, n_markets=n_markets_for(n), seed=seed)

    t0 = time.time()
    res_ilo = run_ilo_v2(farmers, copy.deepcopy(fleet), markets)
    t_ilo = time.time() - t0

    t0 = time.time()
    res_ind = run_individual_transport_v2(farmers, copy.deepcopy(fleet), markets, fresh_capacity(markets))
    t_ind = time.time() - t0

    t0 = time.time()
    res_prox = run_proximity_pooling_v2(farmers, copy.deepcopy(fleet), markets, fresh_capacity(markets))
    t_prox = time.time() - t0

    rows = []
    for algo, res, t_elapsed in [("Integrated Logistics Optimization", res_ilo, t_ilo),
                                  ("Individual Transport", res_ind, t_ind),
                                  ("Proximity Pooling", res_prox, t_prox)]:
        s = summarize(res, n, len(fleet))
        s.update({"algorithm": algo, "n_farmers": n, "n_vehicles": len(fleet),
                   "n_markets": len(markets), "seed": seed, "runtime_sec": t_elapsed})
        rows.append(s)
    return rows


def main():
    all_rows = []
    print(f"{'n_farmers':>9} {'trial':>5} {'algorithm':<22} {'net_return':>14} {'served%':>8} {'runtime':>8}")
    for n in N_VALUES:
        for trial in range(TRIALS_PER_N):
            seed = n * 1000 + trial
            rows = run_all(seed, n)
            all_rows.extend(rows)
            for r in rows:
                print(f"{n:>9} {trial:>5} {r['algorithm']:<22} {r['net_return']:>14,.0f} "
                      f"{r['pct_qty_served']:>7.1f}% {r['runtime_sec']:>7.2f}s")

    df = pd.DataFrame(all_rows)
    df.to_csv("results_v2_raw.csv", index=False)

    summary = df.groupby(["n_farmers", "algorithm"]).agg(
        net_return_mean=("net_return", "mean"),
        net_return_std=("net_return", "std"),
        pct_served_mean=("pct_qty_served", "mean"),
        runtime_mean=("runtime_sec", "mean"),
        vehicles_used_mean=("vehicles_used", "mean"),
        n_vehicles=("n_vehicles", "first"),
        pools_formed_mean=("pools_formed", "mean"),
    ).reset_index()
    summary.to_csv("results_v2_summary.csv", index=False)
    print("\n=== Summary (mean over {} trials per n) ===".format(TRIALS_PER_N))
    print(summary.to_string(index=False))

    # -------- charts --------
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 5))
    for algo in ["Integrated Logistics Optimization", "Individual Transport", "Proximity Pooling"]:
        sub = summary[summary.algorithm == algo]
        ax.plot(sub.n_farmers, sub.net_return_mean, marker="o", label=algo)
    ax.axhline(0, color="gray", linewidth=0.8)
    ax.set_xlabel("Number of farmers")
    ax.set_ylabel("Net return (INR)")
    ax.set_title("Net return vs. scale (fleet & markets scaled proportionally)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig("chart_net_return_v2.png", dpi=130)

    fig2, ax2 = plt.subplots(figsize=(8, 5))
    ilo = summary[summary.algorithm == "Integrated Logistics Optimization"]
    ax2.plot(ilo.n_farmers, ilo.runtime_mean, marker="o", color="darkorange")
    ax2.set_xlabel("Number of farmers")
    ax2.set_ylabel("Wall-clock runtime (seconds)")
    ax2.set_title("Integrated Logistics Optimization v2: runtime vs. scale (up to 10,000 farmers)")
    ax2.grid(alpha=0.3)
    fig2.tight_layout()
    fig2.savefig("chart_runtime_scaling_v2.png", dpi=130)

    fig3, ax3 = plt.subplots(figsize=(8, 5))
    for algo in ["Integrated Logistics Optimization", "Individual Transport", "Proximity Pooling"]:
        sub = summary[summary.algorithm == algo]
        ax3.plot(sub.n_farmers, sub.pct_served_mean, marker="o", label=algo)
    ax3.set_xlabel("Number of farmers")
    ax3.set_ylabel("% of produce volume served")
    ax3.set_title("Service coverage vs. scale")
    ax3.legend()
    ax3.grid(alpha=0.3)
    fig3.tight_layout()
    fig3.savefig("chart_service_pct_v2.png", dpi=130)

    print("\nWrote results_v2_raw.csv, results_v2_summary.csv, "
          "chart_net_return_v2.png, chart_runtime_scaling_v2.png, chart_service_pct_v2.png")


if __name__ == "__main__":
    main()
