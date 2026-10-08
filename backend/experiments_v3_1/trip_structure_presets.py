"""trip_structure_probe on the five real-data presets (one scenario each). Run from backend/.
SP-level (fleet-blind objective): capacity x3, top-K=all, mixed-crop, binding. End-to-end (full run_ilo_v3): baseline vs
mixed-crop vs capacity x3."""
import sys, copy, dataclasses, time
from collections import defaultdict
import numpy as np
sys.path.insert(0, '.')
import ilo_v3 as I, baselines_v3 as B
from real_data.bihar_preset import load
sys.path.insert(0, 'experiments_v3_1')
from _trip_helpers import add_mixed, orig_gen, gen_mixed   # noqa: E402

KEYS = (sys.argv[1:] or ["bihar_dec2025_feb2026", "karnataka_bengaluru", "up_aligarh", "maharashtra_junnar", "mp_indore"])
print("preset | farmers mandis vehicles | SP base | cap x3 | top-K all | mixed | keys>=90% full | trips on full keys || e2e gain: base | mixed | cap x3")
for key in KEYS:
    f, fl, m = load(key)
    prices = B._as_prices(m, B.FARMGATE_DISCOUNT, None); fg = sum(prices.value_of([x]) for x in f)
    cands, _ = I.generate_candidates(f, fl, m, prices, 0.0)
    chosen, _ = I.solve_set_partition(cands, m); base = sum(c["delta"] for c in chosen)
    used = defaultdict(float)
    for c in chosen:
        for crop, q in c["qty_by_crop"].items():
            used[(c["market"].id, crop)] += q
    cap = {(x.id, cr): x.capacity_kg[cr] for x in m for cr in x.capacity_kg}
    full = {k for k, q in used.items() if q >= 0.9 * cap[k]}
    m3 = [dataclasses.replace(x, capacity_kg={c: v * 3 for c, v in x.capacity_kg.items()}) for x in m]
    c3, _ = I.generate_candidates(f, fl, m3, prices, 0.0); o3 = sum(c["delta"] for c in I.solve_set_partition(c3, m3)[0])
    old = I.CW_TOP_MARKETS; I.CW_TOP_MARKETS = 99
    ck, _ = I.generate_candidates(f, fl, m, prices, 0.0); I.CW_TOP_MARKETS = old
    ok = sum(c["delta"] for c in I.solve_set_partition(ck, m)[0])
    cm = add_mixed(dict(cands), f, fl, m, prices); om = sum(c["delta"] for c in I.solve_set_partition(cm, m)[0])
    e2e = {}
    for name, mk, gen in (("base", m, orig_gen), ("mixed", m, gen_mixed), ("cap3", m3, orig_gen)):
        I.generate_candidates = gen
        res, meta = I.run_ilo_v3(f, copy.deepcopy(fl), mk, return_meta=True)
        I.generate_candidates = orig_gen
        e2e[name] = meta["final_value"] - fg
    pct = lambda a, b: (100 * (a / b - 1)) if b else float("nan")                       # noqa: E731
    print("%-22s | %4d %3d %3d | %8d | %+6.1f%% | %+5.1f%% | %+5.1f%% | %3.0f%% | %3.0f%% || %9d | %+5.1f%% | %+6.1f%%" % (
        key, len(f), len(m), len(fl), base, pct(o3, base), pct(ok, base), pct(om, base),
        100 * len(full) / max(1, len(used)),
        100 * sum(1 for c in chosen if any((c["market"].id, cr) in full for cr in c["qty_by_crop"])) / max(1, len(chosen)),
        e2e["base"], pct(e2e["mixed"], e2e["base"]), pct(e2e["cap3"], e2e["base"])), flush=True)
