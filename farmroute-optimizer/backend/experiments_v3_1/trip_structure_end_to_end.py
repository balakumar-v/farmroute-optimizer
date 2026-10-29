"""Do the trip_structure_probe results survive the fleet limit and the simulator? (run from backend/)
Full run_ilo_v3 (fleet-aware, safeguard on) with: baseline candidates | + mixed-crop CW trips | mandi capacities x3.
Gain = final value minus the farm-gate-only value."""
import sys, copy, dataclasses, time
from collections import defaultdict
import numpy as np
sys.path.insert(0, '.')
import ilo_v3 as I, baselines_v3 as B
from logistics_lib_v2 import generate_scenario_v2


sys.path.insert(0, 'experiments_v3_1')
from _trip_helpers import add_mixed, orig_gen, gen_mixed   # noqa: E402


tot = defaultdict(lambda: defaultdict(float))
for n, nm in ((150, 3), (150, 8)):
    for seed in (1, 2, 3):
        f, fl, m = generate_scenario_v2(n_farmers=n, n_markets=nm, seed=seed)
        prices = B._as_prices(m, B.FARMGATE_DISCOUNT, None); fg = sum(prices.value_of([x]) for x in f)
        m3 = [dataclasses.replace(x, capacity_kg={c: v * 3 for c, v in x.capacity_kg.items()}) for x in m]
        for name, mk, gen in (("baseline", m, orig_gen), ("mixed-crop", m, gen_mixed), ("capacity x3", m3, orig_gen)):
            I.generate_candidates = gen
            t0 = time.time()
            res, meta = I.run_ilo_v3(f, copy.deepcopy(fl), mk, return_meta=True)
            I.generate_candidates = orig_gen
            g = meta["final_value"] - fg
            tot[(n, nm)][name] += g
            print(n, nm, seed, name, round(g), meta["chosen"], round(time.time() - t0), "s", flush=True)
print("\n n mandis | baseline gain | mixed-crop | capacity x3   (sums over 3 seeds; fleet-aware, full pipeline)")
for (n, nm), d in tot.items():
    b = d["baseline"]
    print("%3d %3d    | %13d | %+6.1f%%    | %+6.1f%%" % (n, nm, b, 100 * (d["mixed-crop"] / b - 1), 100 * (d["capacity x3"] / b - 1)))
