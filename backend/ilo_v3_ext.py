"""ilo_v3_ext.py -- experimental extensions to ILO v3, all OFF by default (switched from ilo_v3.py by env vars).
  enrich()  local-search enrichment of candidate trips (ILO_ENRICH=1)           [reconstruction of the prior session's idea]
  colgen()  dual-guided column generation for the fleet set-partition (ILO_COLGEN=rounds)
Nothing here changes accounting; it only adds candidate trips / columns."""
import os
import numpy as np

import ilo_v3 as I
from logistics_lib_v2 import haversine

ENRICH_TOP = int(os.environ.get("ILO_ENRICH_TOP", "60"))
NBRS = int(os.environ.get("ILO_NBRS", "8"))


def _neighbours(farmers, k=NBRS):
    """k nearest same-crop farmers (road-km via haversine(), so matrix-aware) for every farmer."""
    by_crop = {}
    for f in farmers:
        by_crop.setdefault(f.crop, []).append(f)
    out = {}
    for fs in by_crop.values():
        for f in fs:
            d = sorted((haversine(f.lat, f.lng, g.lat, g.lng), g.id) for g in fs if g.id != f.id)
            out[f.id] = [gid for _d, gid in d[:k]]
    return out


def _moves(order, nbr, by_id):
    """Neighbour trips: drop a stop, insert a near farmer at any position, swap a stop for a near farmer."""
    ids = {f.id for f in order}
    if len(order) > 1:
        for i in range(len(order)):
            yield order[:i] + order[i + 1:]
    cand = []
    for f in order:
        for gid in nbr.get(f.id, ()):
            if gid not in ids and gid not in cand:
                cand.append(gid)
    for gid in cand:
        g = by_id[gid]
        for p in range(len(order) + 1):
            yield order[:p] + [g] + order[p:]
        for i in range(len(order)):
            yield order[:i] + [g] + order[i + 1:]


def _local_search(order, market, score_fn, nbr, by_id, passes=3):
    """Steepest-ascent. score_fn(order) -> (score, eval) or None. Returns list of improving states visited."""
    r = score_fn(order)
    if r is None:
        return []
    cur, visited = r[0], []
    for _ in range(passes):
        best = None
        for o2 in _moves(order, nbr, by_id):
            r2 = score_fn(o2)
            if r2 is not None and r2[0] > cur + 1e-6 and (best is None or r2[0] > best[0]):
                best = (r2[0], o2, r2[1])
        if best is None:
            break
        cur, order = best[0], best[1]
        visited.append((order, best[2]))
    return visited


def enrich(cands, farmers, markets, prices, margin, vtypes, offer, stats, passes=3):
    """Local-search the ENRICH_TOP best candidate trips (by gain over farm gate) at their own mandi; every
    improving state is offered back as a candidate."""
    by_id = {f.id: f for f in farmers}
    nbr = _neighbours(farmers)
    seeds = sorted(cands.values(), key=lambda c: -c["delta"])[:ENRICH_TOP]
    for c in seeds:
        m = c["market"]
        def score(o, m=m):
            e = I._eval_trip(o, markets, prices, vtypes, margin, m)
            return None if e is None else (e["delta"], e)
        for order, _e in _local_search(list(c["order"]), m, score, nbr, by_id, passes):
            offer(order, "enrich", forced=m)


def colgen(cols, cands, farmers, fleet, markets, prices, margin, cap_mult, keep_market, rounds):
    """Heuristic column generation for the fleet set partition. Each round: solve the LP over the current columns,
    read duals (farmer rows pi, mandi-capacity rows mu, fleet-cell rows nu), local-search trips to maximise
    reduced profit  delta - sum(pi) - mu.q  (fleet-cell duals applied exactly when columns are expanded), add every
    column with reduced profit > 0, repeat. Returns (cols, log)."""
    vtypes = I._fleet_types(fleet)
    by_id = {f.id: f for f in farmers}
    nbr = _neighbours(farmers)
    have = {(c["ids"], c["cls"], c["start"]) for c in cols}
    seen_orders = {frozenset(c["ids"]) for c in cols}
    log = []
    os.environ["ILO_KEEP_DUALS"] = "1"
    try:
        for r in range(int(rounds)):
            _c, _s, meta = I.solve_fleet_set_partition(cols, markets, fleet, lp_only=True)
            d = meta.get("_duals")
            if d is None:
                break
            pi, mu, nu = d["farmer"], d["market"], d["fleet"]
            log.append({"round": r, "lp_bound": meta.get("lp_bound"), "columns": len(cols)})
            def rp(e):
                return (e["delta"] - sum(pi.get(i, 0.0) for i in e["ids"])
                        - sum(mu.get((e["market"].id, cr), 0.0) * q for cr, q in e["qty_by_crop"].items()))
            seeds = {}
            for c in cols:
                seeds.setdefault(c["ids"], c)
            new_orders = {}
            for c in seeds.values():
                m = c["market"]
                def score(o, m=m):
                    e = I._eval_trip(o, markets, prices, vtypes, margin, m, cap_mult=cap_mult)
                    return None if e is None else (rp(e), e)
                for order, e in _local_search(list(c["order"]), m, score, nbr, by_id, passes=3):
                    ids = frozenset(f.id for f in order)
                    if ids not in seen_orders and rp(e) > 1e-6:
                        new_orders[ids] = e
            # singletons / pairs the LP has priced out are re-tested too: add every near-neighbour pair of uncovered farmers
            if not new_orders:
                break
            fresh = {}
            for ids, e in new_orders.items():
                e["source"] = "colgen"
                fresh[ids] = e
            newcols = I.expand_fleet_columns(fresh, fleet, markets, prices, margin, cap_mult=cap_mult,
                                             keep_market=keep_market)
            added = 0
            for c in newcols:
                key = (c["ids"], c["cls"], c["start"])
                if key in have:
                    continue
                red = (c["delta"] - sum(pi.get(i, 0.0) for i in c["ids"])
                       - sum(mu.get((c["market"].id, cr), 0.0) * q for cr, q in c["qty_by_crop"].items())
                       - sum(nu.get((c["cls"], j), 0.0) for j in range(c["cells"][0], c["cells"][1] + 1)))
                if red > 1e-6:
                    cols.append(c)
                    have.add(key)
                    added += 1
            seen_orders |= set(fresh)
            log[-1]["added"] = added
            if added == 0:
                break
    finally:
        os.environ.pop("ILO_KEEP_DUALS", None)
    return cols, log
