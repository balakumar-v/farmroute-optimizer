"""Exact-ish oracle (idea 4). For small n, enumerate EVERY subset of <= KMAX farmers (mixed crops allowed), best route
order by brute force (<=4 stops) or best of 4 heuristic orders (5-6 stops), keep those that beat the farm gate, and
solve the fleet-aware set partition over that COMPLETE column set. Then run the whole ILO pipeline on it.
Compares: heuristic candidate set (V0 / C13) vs complete set -> value lost to column generation.
python oracle.py N SEED  -> appends a json line to oracle.jsonl"""
import sys, os, json, itertools, time
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import common
import ilo_v3 as I
from algorithms_v2 import _nearest_neighbor_order, _two_opt

KMAX = int(os.environ.get("ORACLE_KMAX", "6"))

def oracle_generate(farmers, fleet, markets, prices, margin, consolidate=True, cap_mult=1.0, markets_per_trip=1):
    vtypes = I._fleet_types(fleet); cands = {}; tried = 0
    maxcap = max(v.capacity_kg for v in vtypes)
    for k in range(1, KMAX + 1):
        for sub in itertools.combinations(farmers, k):
            if sum(f.qty_kg for f in sub) > maxcap: continue
            if k <= 4: orders = [list(p) for p in itertools.permutations(sub)]
            else:
                nn = _two_opt(_nearest_neighbor_order(list(sub)))
                rd = sorted(sub, key=lambda f: (f.ready_hr, f.id))
                orders = [nn, nn[::-1], rd, rd[::-1]]
            best = None
            for o in orders:
                tried += 1
                e = I._eval_trip(o, markets, prices, vtypes, margin, None, cap_mult=cap_mult)
                if e is not None and (best is None or e["delta"] > best["delta"]): best = e
            if best is not None and best["delta"] > 1e-6:
                best["source"] = "oracle"; cands[best["ids"]] = best
    return cands, {"oracle_tried": tried}

if __name__ == "__main__":
    n, seed = int(sys.argv[1]), int(sys.argv[2])
    out = {}
    for tag, env in (("heur_V0", {}), ("heur_C13", {"ILO_KEEP_ORDER": 1, "ILO_SIM_SPOIL": 1}),
                     ("oracle_C13", {"ILO_KEEP_ORDER": 1, "ILO_SIM_SPOIL": 1}), ("oracle_V0", {})):
        orig = I.generate_candidates
        if tag.startswith("oracle"): I.generate_candidates = oracle_generate
        t0 = time.time()
        try:
            r = common.run(n, seed, env=env)
        finally:
            I.generate_candidates = orig
        fa = r["meta"]["fleet_aware"]
        out[tag] = dict(gain=r["gain"], sp_obj=fa.get("sp_obj"), lp=fa.get("lp_bound"), cols=fa.get("columns"),
                        cands=r["meta"]["candidates"]["total_kept"], status=fa.get("status"), secs=time.time() - t0)
    out.update(n=n, seed=seed)
    open(os.path.join(os.path.dirname(__file__), "oracle.jsonl"), "a").write(json.dumps(out) + "\n")
    print(json.dumps(out))
