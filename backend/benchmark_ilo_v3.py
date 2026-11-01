"""
benchmark_ilo_v3.py -- does ILO v3 beat (or at worst tie) every baseline across scenarios?

Run from backend/:
  python benchmark_ilo_v3.py grid   [--n 30 100 300] [--seeds 2]     win/tie/loss map + property check
  python benchmark_ilo_v3.py robust [--n 100] [--seeds 3]            planner assumes 20% discount, truth differs
  python benchmark_ilo_v3.py margin [--n 100] [--seeds 3]            tune dispatch_margin under that mismatch
  python benchmark_ilo_v3.py bihar                                   the Bihar preset (needs frontend/app.js)

Every value is farmer-side value INCLUDING the farm-gate sale of anything not hauled, same prices and accounting
(return leg charged, spoilage from pickup) for every algorithm. Baselines: farm-gate only, and rational and
behavioural variants of self-haul and neighbour pooling. "ILO v2 (shipped)" is run_ilo_v2 with its legacy
accounting, re-scored under the honest accounting only through the farm-gate fallback (its own cost model still
omits the return leg, so it is optimistic).

The scenario grid varies farmer count, mandi distance (markets pulled toward / pushed away from the farmer area),
farm-gate discount and seed. The farm-gate discount is an ASSUMPTION; the grid covers 5% - 30%.
"""
import argparse
import copy
import statistics
import sys

from algorithms_v2 import run_ilo_v2
from baselines_v3 import (
    DEFAULT_BEHAVIOUR, FarmgatePrices, run_farmgate_baseline_v2, run_neighbour_pooling_v2,
    run_self_haul_v2, summarize_with_farmgate,
)
from ilo_v3 import run_ilo_v3
from logistics_lib_v2 import Market, fresh_capacity, generate_scenario_v2

CENTER = (25.60, 84.90)
TIE_PCT = 0.5


def scaled_scenario(n, seed, dist_scale):
    farmers, fleet, markets = generate_scenario_v2(n_farmers=n, n_markets=max(3, n // 300 + 2), seed=seed)
    ms = [Market(id=m.id, lat=CENTER[0] + dist_scale * (m.lat - CENTER[0]),
                 lng=CENTER[1] + dist_scale * (m.lng - CENTER[1]), price=m.price, capacity_kg=m.capacity_kg)
          for m in markets]
    return farmers, fleet, ms


def baseline_values(farmers, fleet, markets, prices):
    fs = len(fleet)
    S = lambda r: summarize_with_farmgate(r, farmers, markets, fs, prices=prices)["net_return_incl_farmgate"]  # noqa: E731
    mk = lambda: fresh_capacity(markets)                                                                       # noqa: E731
    out = {"farm-gate only": S(run_farmgate_baseline_v2(farmers, markets))}
    for tag, beh in (("rational", None), ("behavioural", DEFAULT_BEHAVIOUR)):
        out[f"self-haul ({tag})"] = S(run_self_haul_v2(farmers, fleet, markets, mk(), prices=prices, behaviour=beh))
        out[f"neighbour ({tag})"] = S(run_neighbour_pooling_v2(farmers, fleet, markets, mk(), prices=prices, behaviour=beh))
    return out


def classify(v, best):
    pct = 100 * (v / best - 1) if best else 0.0
    return ("win" if pct > TIE_PCT else "tie" if pct >= -TIE_PCT else "loss"), pct


def run_cell(n, seed, dist_scale, d_plan, d_true, margin=None, with_v2=True):
    farmers, fleet, markets = scaled_scenario(n, seed, dist_scale)
    fs = len(fleet)
    p_true = FarmgatePrices(markets, d_true)
    base = baseline_values(farmers, fleet, markets, p_true)
    kwargs = {} if margin is None else {"dispatch_margin": margin}
    res, meta = run_ilo_v3(farmers, fleet, markets, discount=d_plan, return_meta=True, **kwargs)
    v3 = summarize_with_farmgate(res, farmers, markets, fs, prices=p_true)["net_return_incl_farmgate"]
    own = None
    if d_plan == d_true:
        own = max(v for k, v in meta["plan_values"].items() if not k.startswith("fallback:"))
    v2 = None
    if with_v2:
        v2 = summarize_with_farmgate(run_ilo_v2(farmers, copy.deepcopy(fleet), markets), farmers, markets, fs,
                                     prices=p_true)["net_return_incl_farmgate"]
    return {"base": base, "v3": v3, "v3_own": own, "v2": v2, "meta": meta}


def cmd_grid(a):
    rows = []
    for n in a.n:
        for dist in (0.4, 1.0, 2.5):
            for d in (0.05, 0.15, 0.30):
                for k in range(a.seeds):
                    r = run_cell(n, n * 1000 + k, dist, d, d)
                    best_name = max(r["base"], key=r["base"].get)
                    best = r["base"][best_name]
                    cls, pct = classify(r["v3"], best)
                    cls_own, pct_own = classify(r["v3_own"], best)
                    cls_v2, pct_v2 = classify(r["v2"], best)
                    rows.append(dict(n=n, dist=dist, d=d, seed=k, best_name=best_name, pct=pct, cls=cls,
                                     pct_own=pct_own, cls_own=cls_own, pct_v2=pct_v2, cls_v2=cls_v2,
                                     prop=r["v3"] >= best - 1e-6, fb=r["meta"]["safeguard_used"]))
                    print(f"n={n:<4} dist x{dist:<3} disc {d:.0%} seed {k}: v3 {pct:+6.1f}% [{cls}]  "
                          f"own(no safeguard) {pct_own:+6.1f}% [{cls_own}]  v2 {pct_v2:+6.1f}%  vs {best_name}",
                          flush=True)
    print("\n=== PROPERTY: v3 >= best baseline in every cell:", all(r["prop"] for r in rows),
          f"({sum(r['prop'] for r in rows)}/{len(rows)}) ===")
    for label, key in (("ILO v3 (with safeguard)", "cls"), ("ILO v3 own plans only, no safeguard", "cls_own"),
                       ("ILO v2 as shipped", "cls_v2")):
        c = {k: sum(r[key] == k for r in rows) for k in ("win", "tie", "loss")}
        print(f"{label:<38} win {c['win']:>3}  tie {c['tie']:>3}  loss {c['loss']:>3}   (tie band +/-{TIE_PCT}%)")
    print(f"safeguard fallback returned in {sum(r['fb'] for r in rows)}/{len(rows)} cells")
    print("\nMean % vs best baseline by discount x mandi distance (v3 with safeguard | own plans only | v2 shipped):")
    for d in (0.05, 0.15, 0.30):
        for dist in (0.4, 1.0, 2.5):
            sel = [r for r in rows if r["d"] == d and r["dist"] == dist]
            m = lambda k: statistics.mean(r[k] for r in sel)                                                  # noqa: E731
            print(f"  discount {d:>4.0%}  mandi distance x{dist:<3}: {m('pct'):+6.1f}% | {m('pct_own'):+6.1f}% | {m('pct_v2'):+6.1f}%")


def cmd_robust(a, margins=(None,)):
    print("Planner assumes a 20% farm-gate discount; the TRUTH is 10 / 20 / 30%. Baselines know the true price.")
    for margin in margins:
        label = "default margin" if margin is None else f"margin {margin:.0%}"
        for d_true in a.true:
            pcts = []
            for n in a.n:
                for dist in (0.4, 1.0, 2.5):
                    for k in range(a.seeds):
                        r = run_cell(n, n * 1000 + k, dist, 0.20, d_true, margin, with_v2=False)
                        pcts.append(100 * (r["v3"] / max(r["base"].values()) - 1))
            print(f"  [{label}] true discount {d_true:.0%}: mean {statistics.mean(pcts):+6.2f}%  worst {min(pcts):+6.2f}%  "
                  f"share of cells below best baseline: {sum(p < -TIE_PCT for p in pcts) / len(pcts):.0%}", flush=True)


def cmd_bihar(a):
    """The Bihar preset (one scenario, so no win/loss statistics): ILO v2, v3 ablations and every baseline."""
    from real_data.bihar_preset import load
    farmers, fleet, markets = load()
    fs = len(fleet)
    for d in (0.10, 0.20, 0.30):
        prices = FarmgatePrices(markets, d)
        base = baseline_values(farmers, fleet, markets, prices)
        best = max(base.values())
        print(f"\n[Bihar | farm-gate discount {d:.0%}] best baseline {max(base, key=base.get)} = {best:,.0f}")
        for k, v in base.items():
            print(f"   {k:<26} {v:>10,.0f}")
        variants = {"ILO v2 (legacy)": None,
                    "ILO v3 Phase 1 only": dict(set_partition=False, safeguard=False),
                    "ILO v3 no consolidation": dict(consolidate=False, safeguard=False),
                    "ILO v3 full": {}}
        for label, kw in variants.items():
            res = (run_ilo_v2(farmers, copy.deepcopy(fleet), markets) if kw is None
                   else run_ilo_v3(farmers, fleet, markets, prices=prices, **kw))
            v = summarize_with_farmgate(res, farmers, markets, fs, prices=prices)["net_return_incl_farmgate"]
            print(f"   {label:<26} {v:>10,.0f}   {100 * (v / best - 1):+6.1f}% vs best baseline")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["grid", "robust", "margin", "bihar"])
    ap.add_argument("--n", type=int, nargs="+", default=[30, 100, 300])
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--true", type=float, nargs="+", default=[0.10, 0.20, 0.30], help="true discounts for robust/margin")
    ap.add_argument("--margins", type=float, nargs="+", default=[0.0, 0.03, 0.08])
    a = ap.parse_args()
    if a.cmd == "grid":
        cmd_grid(a)
    elif a.cmd == "robust":
        cmd_robust(a)
    elif a.cmd == "margin":
        cmd_robust(a, margins=tuple(a.margins))
    else:
        cmd_bihar(a)
