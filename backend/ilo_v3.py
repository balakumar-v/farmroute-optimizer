"""
ilo_v3.py -- ILO v3: a value-based planner that never does worse than the baselines it is compared with.

Why: on realistic accounting (return leg charged, spoilage from pickup, produce not hauled valued at the farm
gate), ILO v2 lost to simply selling at the farm gate. It dispatched anything with net return > Rs 0 instead of
anything that beats the farm gate, pooled by 12 km geography *before* choosing a market (so many trips drove
100+ km separately to the same mandi), and its scorecard ignored the value of what it did not haul.

PIPELINE (each step is a switch so it can be ablated; see benchmark_ilo_v3.py)
  Phase 1  Honest objective. One number everywhere: net return of hauled trips + farm-gate value of whatever is
           not hauled. Four fixes in run_our_system_v2: farm-gate-aware dispatch, route-duration fix,
           spoilage from pickup, return leg charged.                                   -> "plan A"
  Phase 2  Pool consolidation. Per (mandi, crop), a Clarke-Wright savings pass merges farmers/clusters into
           full trucks that make ONE haul to that mandi (closed loop mandi -> stops -> mandi, exactly the cost the
           accounting charges). Every intermediate merge is kept as a candidate trip.
  Phase 3  Set partitioning with the baselines inside the option set. Candidate trips = single-farmer trips,
           ILO's own pools, neighbour groups, Phase-2 routes, each scored standalone against the farm-gate value
           of its members. An exact 0/1 program (scipy/HiGHS) picks disjoint trips maximising total gain, with
           mandi capacity as a constraint; the real planner then runs on those pools (fleet times, market LP,
           economic dispatch) -> "plan B". Finally the best of {A, B, farm-gate only, rational and behavioural
           self-haul / neighbour pooling} under the SAME accounting is returned (`safeguard`), so a heuristic
           miss cannot lose to a baseline. meta["chosen"] says which plan was returned.
  Phase 4  Farmer-level no-loss. Any dispatched trip that earns less than its members' farm-gate value is
           dropped; the surplus of every remaining trip is split so each farmer gets at least their own
           farm-gate value (`per_farmer_value_gain_sharing`). The legacy pro-rata `per_farmer_net` is kept and the
           number of farmers it would have left worse off is reported.
  Phase 5  Price input and risk margin. Farm-gate prices come from FarmgatePrices (per-crop observed price,
           per-farmer price_fn e.g. by region, or median mandi x (1 - discount) as the fallback). `dispatch_margin`
           makes a trip beat the farm gate by that fraction, a buffer against the price being wrong.

WHAT THE GUARANTEE IS (and is not): returned value >= the best baseline, measured with the same prices and
accounting the planner was given. It is not a promise about real farmers, and it is only as good as the
farm-gate price input: if the true doorstep price differs from the one supplied, either side can be off.
"""
import copy
import time
from collections import defaultdict

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

from algorithms_v2 import (
    EARTH_R_KM, _bin_pack_fleet_aware, _geo_clusters, _nearest_neighbor_order, _refrig_eps_km,
    _route_distance, _simulate_end_time, _split_by_time_window, _timeline_from, _two_opt,
    _withheld_result, fleet_capacity_cycle, run_our_system_v2,
)
from baselines_v3 import (
    DEFAULT_BEHAVIOUR, FARMGATE_DISCOUNT, FarmgatePrices, _as_prices, _neighbour_groups,
    run_farmgate_baseline_v2, run_neighbour_pooling_v2, run_self_haul_v2, summarize_with_farmgate,
)
from logistics_lib_v2 import AVG_SPEED_KMPH, fresh_capacity, haversine, spoilage_fraction

DEFAULT_DISPATCH_MARGIN = 0.0     # tuned in benchmark_ilo_v3.py (--margin-sweep); see ALGORITHM doc
CW_ALL_PAIRS_MAX = 400            # above this many eligible farmers per (mandi, crop) use k-nearest pairs
CW_KNN = 25
CW_TOP_MARKETS = 3                # a farmer is eligible for a mandi only if it is among their 3 best by net/kg
SP_TIME_LIMIT_S = 30.0
_EPS = 1e-6


# ----------------------------------------------------------------------
# Standalone trip evaluation (candidate scoring)
# ----------------------------------------------------------------------
def _fleet_types(fleet):
    """One representative vehicle per (capacity, refrigerated) spec, cheapest first."""
    best = {}
    for v in fleet:
        key = (v.capacity_kg, v.refrigerated)
        if key not in best or v.fixed_cost < best[key].fixed_cost:
            best[key] = v
    return sorted(best.values(), key=lambda v: (v.capacity_kg, v.fixed_cost))


def _pick_vehicle(vtypes, qty, needs_refrig):
    fit = [v for v in vtypes if v.capacity_kg >= qty]
    if not fit:
        return None
    if needs_refrig:
        ref = [v for v in fit if v.refrigerated]
        if ref:
            fit = ref
    return fit[0]


def _cheap_order(pool):
    """Fast routing for candidate scoring: nearest-neighbour + 2-opt, falling back to ready-time order if
    that breaks a deadline. (The real planner re-routes the chosen pools with order_route.)"""
    if len(pool) <= 1:
        return list(pool)
    order = _two_opt(_nearest_neighbor_order(list(pool))) if len(pool) > 2 else _nearest_neighbor_order(list(pool))
    if _simulate_end_time(order, True)[0]:
        return order
    order = sorted(pool, key=lambda f: (f.ready_hr, f.id))
    return order if _simulate_end_time(order, True)[0] else None


def _eval_trip(order, markets, prices, vtypes, margin, forced_market=None):
    """Best single-mandi plan for hiring one FPO vehicle to take `order` (in that sequence); None if infeasible.
    Returns the gain over selling everything at the farm gate (`delta`) and what is needed to constrain mandi
    capacity in the set-partitioning model."""
    if not _simulate_end_time(order, True)[0]:
        return None
    start = min(f.ready_hr for f in order)
    pickups, t_leave = _timeline_from(order, start)
    if t_leave > min(f.deadline_hr for f in order):
        return None
    qty = sum(f.qty_kg for f in order)
    veh = _pick_vehicle(vtypes, qty, any(f.needs_refrigeration for f in order))
    if veh is None:
        return None
    route_km = _route_distance(order)
    crops = {f.crop for f in order}
    last, first = order[-1], order[0]
    fg = prices.value_of(order)
    best = None
    for m in ([forced_market] if forced_market is not None else markets):
        if not all(c in m.price and c in m.capacity_kg for c in crops):
            continue
        leg = haversine(last.lat, last.lng, m.lat, m.lng)
        back = haversine(m.lat, m.lng, first.lat, first.lng)
        cost = veh.fixed_cost + veh.per_km_cost * (route_km + leg + back)
        t_arr = t_leave + leg / AVG_SPEED_KMPH
        qty_c = defaultdict(float)
        for f in order:
            qty_c[f.crop] += f.qty_kg
        frac = {c: min(1.0, m.capacity_kg[c] / q) if q else 0.0 for c, q in qty_c.items()}
        rev = sum(f.qty_kg * frac[f.crop] * m.price[f.crop]
                  * (1 - spoilage_fraction(f.crop, veh.refrigerated, t_arr - pickups[i]))
                  for i, f in enumerate(order))
        net = rev - cost
        if best is None or net > best["net"]:
            best = {"order": order, "market": m, "net": net, "qty_by_crop": dict(qty_c), "vehicle": veh}
    if best is None:
        return None
    best["fg"] = fg
    best["delta"] = best["net"] - fg * (1.0 + margin)
    best["ids"] = frozenset(f.id for f in order)
    return best


# ----------------------------------------------------------------------
# Phase 2: Clarke-Wright consolidation per (mandi, crop)
# ----------------------------------------------------------------------
def _vec_haversine(lat1, lng1, lat2, lng2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dl = np.radians(lng2 - lng1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * EARTH_R_KM * np.arcsin(np.sqrt(np.minimum(1.0, a)))


def _eligible_for_market(farmers, market, markets, per_km_ref, q_ref):
    """Farmers (all one crop) for whom `market` is within their CW_TOP_MARKETS best by estimated net per kg."""
    out = []
    for f in farmers:
        scored = []
        for m in markets:
            if f.crop in m.price and f.crop in m.capacity_kg:
                d = haversine(f.lat, f.lng, m.lat, m.lng)
                spoil = spoilage_fraction(f.crop, False, d / AVG_SPEED_KMPH)
                scored.append((m.price[f.crop] * (1 - spoil) - per_km_ref * 2 * d / max(q_ref, 1.0), m.id))
        scored.sort(reverse=True)
        if market.id in {mid for _s, mid in scored[:CW_TOP_MARKETS]}:
            out.append(f)
    return out


def _cw_routes(F, market, qmax):
    """Clarke-Wright savings with the mandi as depot. Yields the ordered stop list after EVERY merge (so the
    best-sized load, not just the final route, is a candidate). Closed loop mandi -> stops -> mandi."""
    n = len(F)
    if n < 2:
        return
    lat = np.array([f.lat for f in F])
    lng = np.array([f.lng for f in F])
    D = _vec_haversine(lat, lng, market.lat, market.lng)
    if n <= CW_ALL_PAIRS_MAX:
        ii, jj = np.triu_indices(n, k=1)
    else:
        from sklearn.neighbors import BallTree
        tree = BallTree(np.radians(np.c_[lat, lng]), metric="haversine")
        _d, idx = tree.query(np.radians(np.c_[lat, lng]), k=min(CW_KNN + 1, n))
        pairs = {(min(i, j), max(i, j)) for i in range(n) for j in idx[i] if i != j}
        ii = np.array([p[0] for p in pairs])
        jj = np.array([p[1] for p in pairs])
    dij = _vec_haversine(lat[ii], lng[ii], lat[jj], lng[jj])
    sav = D[ii] + D[jj] - dij
    keep = sav > 0
    ii, jj, sav = ii[keep], jj[keep], sav[keep]
    seq = np.argsort(-sav, kind="stable")
    route_of = list(range(n))
    routes = {i: [i] for i in range(n)}
    rqty = {i: F[i].qty_kg for i in range(n)}
    for k in seq:
        i, j = int(ii[k]), int(jj[k])
        ri, rj = route_of[i], route_of[j]
        if ri == rj:
            continue
        A, B = routes[ri], routes[rj]
        if i not in (A[0], A[-1]) or j not in (B[0], B[-1]):
            continue
        if rqty[ri] + rqty[rj] > qmax:
            continue
        A2 = A if A[-1] == i else A[::-1]
        B2 = B if B[0] == j else B[::-1]
        merged = A2 + B2
        order = [F[x] for x in merged]
        if not _simulate_end_time(order, True)[0]:
            continue
        routes[ri] = merged
        rqty[ri] = rqty[ri] + rqty[rj]
        for x in B:
            route_of[x] = ri
        del routes[rj], rqty[rj]
        yield order


# ----------------------------------------------------------------------
# Candidate generation + set partitioning
# ----------------------------------------------------------------------
def _ilo_pools(farmers, fleet):
    """ILO v2's own pools (geographic clusters -> time windows -> fleet-aware bin packing)."""
    slots = fleet_capacity_cycle(fleet)
    scarcity = {"refrig": (lambda f: f.needs_refrigeration, _refrig_eps_km(farmers, fleet))}
    out = []
    for gc in _geo_clusters(farmers, scarcity_eps=scarcity):
        for tg in _split_by_time_window(gc):
            out.extend(_bin_pack_fleet_aware(tg, slots))
    return out


def generate_candidates(farmers, fleet, markets, prices, margin, consolidate=True):
    """Dict ids(frozenset) -> best scored trip. Only trips that beat the farm gate (delta > 0) are kept."""
    vtypes = _fleet_types(fleet)
    cands = {}
    stats = defaultdict(int)

    def offer(order, source, forced=None):
        if order is None:
            return
        stats[source + "_tried"] += 1
        c = _eval_trip(order, markets, prices, vtypes, margin, forced)
        if c is None or c["delta"] <= _EPS:
            return
        key = c["ids"]
        if key not in cands or c["delta"] > cands[key]["delta"] + _EPS:
            if key not in cands:
                stats[source + "_kept"] += 1
            c["source"] = source
            cands[key] = c

    for f in farmers:
        offer([f], "single")
    for pool in _ilo_pools(farmers, fleet):
        offer(_cheap_order(pool), "ilo_pool")
    for g in _neighbour_groups(farmers, check_windows=True):
        offer(_cheap_order(g), "neighbour_group")
    if consolidate and farmers:
        per_km_ref = float(np.mean([v.per_km_cost for v in fleet])) if fleet else 20.0
        q_ref = float(np.median([v.capacity_kg for v in fleet])) * 0.8 if fleet else 1000.0
        qmax_any = max((v.capacity_kg for v in fleet), default=0.0)
        qmax_ref = max((v.capacity_kg for v in fleet if v.refrigerated), default=qmax_any)
        crops = sorted({f.crop for f in farmers})
        for m in markets:
            for crop in crops:
                if crop not in m.price or crop not in m.capacity_kg:
                    continue
                Fc = [f for f in farmers if f.crop == crop]
                F = _eligible_for_market(Fc, m, markets, per_km_ref, q_ref)
                if len(F) < 2:
                    continue
                qmax = qmax_ref if F[0].needs_refrigeration else qmax_any
                for order in _cw_routes(F, m, qmax):
                    offer(order, "cw_route", forced=m)
    return cands, dict(stats)


def solve_set_partition(cands, markets):
    """Pick disjoint trips maximising total gain over the farm gate, subject to mandi capacity per crop.
    Exact 0/1 program (HiGHS); greedy fallback if the solver fails. Returns (chosen list, status)."""
    items = list(cands.values())
    if not items:
        return [], "no_candidates"
    fids = sorted({i for c in items for i in c["ids"]})
    frow = {i: r for r, i in enumerate(fids)}
    mk_rows = {}
    for c in items:
        for crop in c["qty_by_crop"]:
            mk_rows.setdefault((c["market"].id, crop), len(fids) + len(mk_rows))
    A = lil_matrix((len(fids) + len(mk_rows), len(items)))
    ub = np.ones(len(fids) + len(mk_rows))
    cap_of = {m.id: m.capacity_kg for m in markets}
    for (mid, crop), r in mk_rows.items():
        ub[r] = cap_of[mid][crop]
    for col, c in enumerate(items):
        for i in c["ids"]:
            A[frow[i], col] = 1.0
        for crop, q in c["qty_by_crop"].items():
            A[mk_rows[(c["market"].id, crop)], col] = q
    obj = -np.array([c["delta"] for c in items])
    try:
        res = milp(obj, constraints=LinearConstraint(A.tocsr(), -np.inf, ub), integrality=np.ones(len(items)),
                   bounds=Bounds(0, 1), options={"time_limit": SP_TIME_LIMIT_S, "mip_rel_gap": 1e-4})
        if res.x is not None and res.status in (0, 1):
            return [items[k] for k in range(len(items)) if res.x[k] > 0.5], (
                "optimal" if res.status == 0 else "time_limit_best_found")
    except Exception:                                               # pragma: no cover - solver failure
        pass
    used, cap_left, chosen = set(), {k: v for k, v in ((k, ub[r]) for k, r in mk_rows.items())}, []
    for c in sorted(items, key=lambda c: -c["delta"]):             # pragma: no cover - fallback
        if c["ids"] & used:
            continue
        if any(c["qty_by_crop"][cr] > cap_left[(c["market"].id, cr)] + _EPS for cr in c["qty_by_crop"]):
            continue
        chosen.append(c)
        used |= c["ids"]
        for cr, q in c["qty_by_crop"].items():
            cap_left[(c["market"].id, cr)] -= q
    return chosen, "greedy_fallback"


# ----------------------------------------------------------------------
# Phase 4: repair + gain sharing
# ----------------------------------------------------------------------
def _repair_and_share(results, farmers, prices):
    """Drop any dispatched trip that earns less than its members' farm-gate value; then split each remaining
    trip's surplus so every farmer gets at least their own farm-gate value."""
    by_id = {f.id: f for f in farmers}
    out, dropped, worse_prorata = [], 0, 0
    for r in results:
        if r["vehicle_id"] is None:
            out.append(r)
            continue
        members = [by_id[i] for i in r["farmer_ids"]]
        fg = prices.value_of(members)
        if r["net_return"] < fg - _EPS:
            dropped += 1
            out.append(_withheld_result(members))
            continue
        r = dict(r)
        qty = sum(f.qty_kg for f in members)
        surplus = r["net_return"] - fg
        r["per_farmer_value_gain_sharing"] = {f.id: prices.value(f) + surplus * f.qty_kg / qty for f in members}
        worse_prorata += sum(1 for f in members if r["per_farmer_net"].get(f.id, 0.0) < prices.value(f) - _EPS)
        out.append(r)
    return out, {"trips_dropped_below_farmgate": dropped, "farmers_worse_off_under_prorata_split": worse_prorata}


# ----------------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------------
def _trace_json(trace, results):
    """JSON-ready per-pool market allocations for the visualization adapter, keyed by the pool's index in
    `results` (as strings, like main.py stores them). Only pools that are still dispatched are kept, so a trip
    dropped by the repair step never contributes received-kg to a market."""
    return {str(i): {"crop_allocations": dict(pt.crop_allocations)}
            for i, pt in trace.items() if i < len(results) and results[i]["vehicle_id"] is not None}


def _flag_farmgate(results):
    """Pools the planner deliberately did not haul (withheld: hauling them loses to the doorstep price) are
    farm-gate sales. Flag them so the UI shows them as such, not as failures. Pools that wanted a truck and did
    not get one (unserved_no_vehicle_kg) keep their meaning and are NOT flagged."""
    for r in results:
        if r["vehicle_id"] is None and r.get("withheld") and not r.get("sold_at_farmgate"):
            r["sold_at_farmgate"] = True
    return results


def run_ilo_v3(farmers, fleet, markets, discount=FARMGATE_DISCOUNT, prices=None,
               dispatch_margin=DEFAULT_DISPATCH_MARGIN, consolidate=True, set_partition=True,
               safeguard=True, repair=True, return_meta=False, return_trace=False):
    """See module docstring. `fleet` is not mutated. Returns the pool-result list (same shape as ILO v2); with
    return_meta=True, (results, meta); with return_trace=True as well, (results, meta, trace_json) where
    trace_json is what the visualization adapter needs for exact per-market receipts ({} when the returned plan
    is a baseline fallback, which has no market-LP trace)."""
    t0 = time.time()
    prices = _as_prices(markets, discount, prices)
    fs = len(fleet)
    fg_fn = lambda pool: prices.value_of(pool)                                    # noqa: E731
    kw = dict(farmgate_value_fn=fg_fn, dispatch_margin=dispatch_margin, fix_route_duration=True,
              spoilage_from_pickup=True, charge_return_leg=True)
    S = lambda res: summarize_with_farmgate(res, farmers, markets, fs, prices=prices)["net_return_incl_farmgate"]  # noqa: E731

    plans, traces = {}, {}
    plans["A:ilo_pools"], traces["A:ilo_pools"] = run_our_system_v2(farmers, copy.deepcopy(fleet), markets,
                                                                    return_trace=True, **kw)
    meta = {"params": {"discount": prices.discount, "dispatch_margin": dispatch_margin,
                       "consolidate": consolidate, "set_partition": set_partition,
                       "safeguard": safeguard, "repair": repair}}
    if set_partition and farmers:
        t1 = time.time()
        cands, cstats = generate_candidates(farmers, fleet, markets, prices, dispatch_margin, consolidate)
        chosen, sp_status = solve_set_partition(cands, markets)
        covered = {i for c in chosen for i in c["ids"]}
        pools = [c["order"] for c in chosen] + [[f] for f in farmers if f.id not in covered]
        plans["B:set_partition"], traces["B:set_partition"] = run_our_system_v2(
            farmers, copy.deepcopy(fleet), markets, raw_pools_override=pools, return_trace=True, **kw)
        meta["candidates"] = {"total_kept": len(cands), **cstats, "sp_status": sp_status,
                              "sp_trips_chosen": len(chosen),
                              "sp_trips_chosen_by_source": {
                                  src: sum(1 for c in chosen if c["source"] == src)
                                  for src in {c["source"] for c in chosen}},
                              "sp_seconds": round(time.time() - t1, 2)}

    if safeguard:
        mk = lambda: fresh_capacity(markets)                                       # noqa: E731
        plans["fallback:farm_gate_only"] = run_farmgate_baseline_v2(farmers, markets)
        for tag, beh in (("rational", None), ("behavioural", DEFAULT_BEHAVIOUR)):
            plans[f"fallback:self_haul_{tag}"] = run_self_haul_v2(farmers, fleet, markets, mk(), prices=prices, behaviour=beh)
            plans[f"fallback:neighbour_{tag}"] = run_neighbour_pooling_v2(farmers, fleet, markets, mk(),
                                                                          prices=prices, behaviour=beh)
    values = {name: S(res) for name, res in plans.items()}
    # strict > keeps the earlier (ILO-own) plan on ties, so a fallback is chosen only when it is strictly better
    chosen_name = max(values, key=lambda k: (values[k], -list(values).index(k)))
    results = plans[chosen_name]
    trace = traces.get(chosen_name, {})
    meta["plan_values"] = values
    meta["chosen"] = chosen_name
    meta["ilo_own_best"] = max((k for k in values if not k.startswith("fallback:")), key=lambda k: values[k])
    meta["safeguard_used"] = chosen_name.startswith("fallback:")
    if repair:
        results, rstats = _repair_and_share(results, farmers, prices)
        meta.update(rstats)
        meta["final_value"] = S(results)
    else:
        meta["final_value"] = values[chosen_name]
    results = _flag_farmgate(results)
    meta["seconds"] = round(time.time() - t0, 2)
    if return_trace:
        return results, meta, _trace_json(trace, results)
    return (results, meta) if return_meta else results
