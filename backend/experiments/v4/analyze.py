"""python analyze.py results.jsonl [baseline_variant]  -> paired table per (family, n)."""
import sys, json, math, statistics as st
from collections import defaultdict

path = sys.argv[1]; base = sys.argv[2] if len(sys.argv) > 2 else "V0_zip"
rows = [json.loads(l) for l in open(path)]
by = defaultdict(dict)
for r in rows:
    by[(r["family"], r["n"])].setdefault(r["variant"], {})[r["seed"]] = r

def tstat(d):
    if len(d) < 2: return float("nan")
    sd = st.stdev(d)
    return float("inf") if sd == 0 and st.mean(d) != 0 else (0.0 if sd == 0 else st.mean(d) / (sd / math.sqrt(len(d))))

for (fam, n), vs in sorted(by.items()):
    if base not in vs: continue
    b = vs[base]
    print(f"\n=== family {fam}  n={n}   paired vs {base}  (gain = value - farm-gate-only; Rs) ===")
    print(f"{'variant':<16}{'seeds':>5}{'mean value':>12}{'mean gain':>10}{'gain %V0':>9}{'dGain mean':>11}{'dGain %':>8}{'t':>6}{'W/L':>6}{'min dG':>8}{'max dG':>8}{'secs':>7}{'sp/sim':>8}")
    for name, d in vs.items():
        seeds = sorted(set(d) & set(b))
        if not seeds: continue
        dg = [d[s]["gain"] - b[s]["gain"] for s in seeds]
        g = [d[s]["gain"] for s in seeds]; g0 = [b[s]["gain"] for s in seeds]
        wl = f"{sum(x > 1 for x in dg)}/{sum(x < -1 for x in dg)}"
        gap = [d[s]["sp_obj"] / d[s]["gain"] for s in seeds if d[s].get("sp_obj") and d[s]["gain"] > 0]
        print(f"{name:<16}{len(seeds):>5}{st.mean(d[s]['value'] for s in seeds):>12,.0f}{st.mean(g):>10,.0f}{100*st.mean(g)/st.mean(g0):>8.1f}%"
              f"{st.mean(dg):>11,.0f}{100*st.mean(dg)/st.mean(g0):>7.1f}%{tstat(dg):>6.1f}{wl:>6}{min(dg):>8,.0f}{max(dg):>8,.0f}"
              f"{st.mean(d[s]['secs'] for s in seeds):>7.1f}{(st.mean(gap) if gap else float('nan')):>8.3f}")
    bb = [(b[s]["value"] - b[s]["best_baseline"]) for s in b]
    print(f"  (V0 lead over best baseline, Rs/seed: mean {st.mean(bb):,.0f};  V0 gain as % of farm-gate value: {100*st.mean(b[s]['gain']/b[s]['fg'] for s in b):.2f}%)")
