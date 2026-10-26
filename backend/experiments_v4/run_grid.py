"""python run_grid.py OUT.jsonl FAMILY N SEEDS(comma) VARIANT[,VARIANT...]   -- resumable; skips finished keys."""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(__file__))
import common
from variants import VARIANTS

out, fam, n, seeds, names = sys.argv[1], sys.argv[2], int(sys.argv[3]), [int(s) for s in sys.argv[4].split(",")], sys.argv[5].split(",")
done = set()
if os.path.exists(out):
    for l in open(out):
        r = json.loads(l); done.add((r["family"], r["n"], r["seed"], r["variant"]))
for seed in seeds:
    for name in names:
        if (fam, n, seed, name) in done:
            continue
        t0 = time.time()
        r = (common.run_preset(fam[2:], seed, env=VARIANTS[name]) if fam.startswith("P:")
             else common.run(n, seed, env=VARIANTS[name], family=fam))
        m = r["meta"]; fa = m.get("fleet_aware", {}); pv = m["plan_values"]
        rec = dict(family=fam, n=n, seed=seed, variant=name, value=r["value"], fg=r["fg"], gain=r["gain"], secs=r["secs"],
                   chosen=r["chosen"], sp_obj=fa.get("sp_obj"), lp=fa.get("lp_bound"), fl_status=fa.get("status"),
                   cols=fa.get("columns"), cands=m["candidates"]["total_kept"] if "candidates" in m else None,
                   best_baseline=max(v for k, v in pv.items() if k.startswith("fallback:")),
                   plan_values={k: round(v, 1) for k, v in pv.items()}, ratio=r["ratio"],
                   colgen=m.get("colgen"))
        with open(out, "a") as f:
            f.write(json.dumps(rec) + "\n")
        print(f"{fam}{n} s{seed} {name}: gain {r['gain']:.0f} secs {r['secs']:.1f}", file=sys.stderr, flush=True)
