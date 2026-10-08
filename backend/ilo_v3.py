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
           farm-gate value. `per_farmer_net` IS that value-gain split (the legacy pro-rata-by-kg split is no longer
           exposed: it can leave farmers worse off). Each kept trip also carries `breakeven` (see break_even()).
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
from scipy.optimize import Bounds, LinearConstraint, linprog, milp
from scipy.sparse import lil_matrix

from algorithms_v2 import (
    EARTH_R_KM, _bin_pack_fleet_aware, _geo_clusters, _nearest_neighbor_order, _refrig_eps_km,
    _route_distance, _route_duration, _simulate_end_time, _split_by_time_window, _timeline_from, _two_opt,
    _withheld_result, fleet_capacity_cycle, run_our_system_v2,
)
from baselines_v3 import (
    DEFAULT_BEHAVIOUR, FARMGATE_DISCOUNT, FarmgatePrices, _as_prices, _neighbour_groups,
    run_farmgate_baseline_v2, run_neighbour_pooling_v2, run_self_haul_v2, summarize_with_farmgate,
)
from logistics_lib_v2 import (AVG_SPEED_KMPH, TURNAROUND_HR, WORKDAY_END_HR, fresh_capacity, get_road_circuity,
                              haversine, spoilage_fraction)

DEFAULT_DISPATCH_MARGIN = 0.0     # tuned in benchmark_ilo_v3.py (--margin-sweep); see ALGORITHM doc
CW_ALL_PAIRS_MAX = 400            # above this many eligible farmers per (mandi, crop) use k-nearest pairs
CW_KNN = 25
CW_TOP_MARKETS = 3                # a farmer is eligible for a mandi only if it is among their 3 best by net/kg
SP_TIME_LIMIT_S = 30.0
DEFAULT_STRESS_DISCOUNTS = (0.05, 0.10, 0.20, 0.30, 0.35)   # farm-gate discounts the finished plan is stress-tested at
FLEET_DT_HR = 0.25                # time grid of the fleet-capacity rows (conservative: occupancy rounded outward)
FLEET_MAX_START_SLOTS = 6         # start-hour options kept per (trip, vehicle class)
_EPS = 1e-6


# ----------------------------------------------------------------------
# Standalone trip evaluation (candidate scoring)
# ----------------------------------------------------------------------
def _eval_trip_topk(order, markets, prices, vtypes, margin, k, start_override=None, cap_mult=1.0):
    """The k best (market, vehicle) evaluations of one trip by net at base prices, best first. With price impact
    the SP must be able to send a trip to its 2nd or 3rd best mandi when the best one is crowded, so every trip is
    offered at several mandis instead of only the best one."""
    out = []
    for m in markets:
        e = _eval_trip(order, markets, prices, vtypes, margin, m, start_override=start_override, cap_mult=cap_mult)
        if e is not None:
            out.append(e)
    out.sort(key=lambda e: -e["net"])
    return out[:k]


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


def _eval_trip(order, markets, prices, vtypes, margin, forced_market=None, start_override=None, cap_mult=1.0):
    """Best single-mandi plan for hiring one FPO vehicle to take `order` (in that sequence); None if infeasible.
    Returns the gain over selling everything at the farm gate (`delta`) and what is needed to constrain mandi
    capacity in the set-partitioning model."""
    if not _simulate_end_time(order, True)[0]:
        return None
    start = min(f.ready_hr for f in order) if start_override is None else start_override
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
        frac = {c: min(1.0, cap_mult * m.capacity_kg[c] / q) if q else 0.0 for c, q in qty_c.items()}
        qeff = defaultdict(float)                      # kg that reach the buyer after spoilage, per crop
        for i, f in enumerate(order):
            qeff[f.crop] += f.qty_kg * frac[f.crop] * (1 - spoilage_fraction(f.crop, veh.refrigerated, t_arr - pickups[i]))
        rev = sum(q * m.price[c] for c, q in qeff.items())
        net = rev - cost
        if best is None or net > best["net"]:
            best = {"order": order, "market": m, "net": net, "qty_by_crop": dict(qty_c), "vehicle": veh,
                    "start": start, "rev": rev, "cost": cost, "qeff_by_crop": dict(qeff)}
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
    return get_road_circuity() * 2 * EARTH_R_KM * np.arcsin(np.sqrt(np.minimum(1.0, a)))   # road-km


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


def generate_candidates(farmers, fleet, markets, prices, margin, consolidate=True, cap_mult=1.0, markets_per_trip=1):
    """Dict ids(frozenset) -> best scored trip. Only trips that beat the farm gate (delta > 0) are kept."""
    vtypes = _fleet_types(fleet)
    cands = {}
    stats = defaultdict(int)

    def offer(order, source, forced=None):
        if order is None:
            return
        stats[source + "_tried"] += 1
        if markets_per_trip > 1 and forced is None:
            evals = _eval_trip_topk(order, markets, prices, vtypes, margin, markets_per_trip, cap_mult=cap_mult)
        else:
            e = _eval_trip(order, markets, prices, vtypes, margin, forced, cap_mult=cap_mult)
            evals = [] if e is None else [e]
        for c in evals:
            if c["delta"] <= _EPS:
                continue
            key = c["ids"] if markets_per_trip == 1 else (c["ids"], c["market"].id)
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


def _impact_extend(A, ub, obj, items, price_impact, markets):
    """Add concave, volume-dependent mandi revenue to a set-partitioning model (no binaries).
    Each trip then contributes only -(cost + farm-gate hurdle) to the objective; its revenue comes from tranche
    variables y[(mandi, crop), j] <= width_j, filled at decreasing Rs/kg slopes, with
        sum_j y[(m, c), j]  <=  sum over chosen trips of their effective kg of crop c at m.
    price_impact=None returns the model unchanged (fixed prices). Returns (A, ub, obj, var_lb, var_ub, integrality)."""
    n = len(items)
    if price_impact is None:
        return A, ub, obj, np.zeros(n), np.ones(n), np.ones(n)
    mk = {m.id: m for m in markets}
    keys = sorted({(c["market"].id, crop) for c in items for crop in c["qeff_by_crop"]})
    kidx = {k: i for i, k in enumerate(keys)}
    ycols = [(k, w, slope) for k in keys for (_a, w, slope) in price_impact.tranches(mk[k[0]], k[1])]
    ny, nk = len(ycols), len(keys)
    Ax = lil_matrix((nk, n + ny))
    for col, c in enumerate(items):
        for crop, q in c["qeff_by_crop"].items():
            Ax[kidx[(c["market"].id, crop)], col] = -q
    for yi, (k, _w, _s) in enumerate(ycols):
        Ax[kidx[k], n + yi] = 1.0
    from scipy.sparse import hstack, vstack, csr_matrix
    A2 = vstack([hstack([A, csr_matrix((A.shape[0], ny))]), Ax.tocsr()]).tocsr()
    ub2 = np.concatenate([ub, np.zeros(nk)])
    x_obj = np.array([-(c["delta"] - c["rev"]) for c in items])            # cost + farm-gate hurdle (minimise)
    obj2 = np.concatenate([x_obj, -np.array([s for _k, _w, s in ycols])])
    lb = np.zeros(n + ny)
    ubv = np.concatenate([np.ones(n), np.array([w for _k, w, _s in ycols])])
    integ = np.concatenate([np.ones(n), np.zeros(ny)])
    return A2, ub2, obj2, lb, ubv, integ


def solve_set_partition(cands, markets, price_impact=None):
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
    cap_mult = price_impact.capacity_multiple if price_impact is not None else 1.0
    for (mid, crop), r in mk_rows.items():
        ub[r] = cap_of[mid][crop] * cap_mult
    for col, c in enumerate(items):
        for i in c["ids"]:
            A[frow[i], col] = 1.0
        for crop, q in c["qty_by_crop"].items():
            A[mk_rows[(c["market"].id, crop)], col] = q
    obj = -np.array([c["delta"] for c in items])
    A_m, ub_m, obj_m, lb_v, ub_v, integ = _impact_extend(A.tocsr(), ub, obj, items, price_impact, markets)
    try:
        res = milp(obj_m, constraints=LinearConstraint(A_m, -np.inf, ub_m), integrality=integ,
                   bounds=Bounds(lb_v, ub_v), options={"time_limit": SP_TIME_LIMIT_S, "mip_rel_gap": 1e-4})
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
# Phase 3b: fleet-aware set partitioning (columns = trip x vehicle class x start slot)
# ----------------------------------------------------------------------
def _vehicle_classes(fleet):
    """Vehicles grouped by identical spec -> {key: [Vehicle]}; key = (capacity, refrigerated, fixed, per_km)."""
    cls = {}
    for v in fleet:
        cls.setdefault((v.capacity_kg, v.refrigerated, v.fixed_cost, v.per_km_cost), []).append(v)
    return cls


def _class_label(key):
    return f"{key[0]:g}kg{'-reefer' if key[1] else ''}"


def expand_fleet_columns(cands, fleet, markets, prices, margin, cap_mult=1.0, keep_market=False):
    """Turn each candidate trip into columns (trip, vehicle class, start slot). Occupancy matches what
    assign_fleet simulates: a vehicle is busy from `start` for route_duration (+ TURNAROUND_HR), rounded
    outward onto a FLEET_DT_HR grid so that conflict-free columns are truly conflict-free."""
    classes = _vehicle_classes(fleet)
    dt = FLEET_DT_HR
    cols = []
    for c in cands.values():
        order = c["order"]
        qty = sum(f.qty_kg for f in order)
        r = min(f.ready_hr for f in order)
        dl = min(f.deadline_hr for f in order)
        dur = _route_duration(order, 0.0, True)               # start-independent pickup-leg duration
        s0 = np.ceil(r / dt - 1e-9) * dt
        s_max = min(WORKDAY_END_HR, dl - dur)
        if s_max < s0 - 1e-9:
            continue
        K = int(np.floor((s_max - s0) / dt + 1e-9))
        idx = sorted({int(round(x)) for x in np.linspace(0, K, min(FLEET_MAX_START_SLOTS, K + 1))})
        for key, vs in classes.items():
            if key[0] < qty:
                continue
            rep = vs[0]
            for k in idx:
                s_k = s0 + k * dt
                e = _eval_trip(order, markets, prices, [rep], margin, c["market"] if keep_market else None,
                               start_override=s_k, cap_mult=cap_mult)
                if e is None or e["delta"] <= _EPS:
                    continue
                c0 = int(np.floor(s_k / dt + 1e-9))
                c1 = int(np.ceil((s_k + dur + TURNAROUND_HR) / dt - 1e-9)) - 1
                e.update(ids=c["ids"], source=c["source"], cls=key, cells=(c0, c1), dur=dur)
                cols.append(e)
    return cols


def solve_fleet_set_partition(cols, markets, fleet, price_impact=None):
    """Exact 0/1 program: disjoint trips, mandi capacity per crop, AND at most n_class vehicles busy in any
    time cell. Returns (chosen columns, status, meta) -- meta carries the LP shadow value of one extra vehicle
    per class (first-order, from the LP relaxation)."""
    if not cols:
        return [], "no_candidates", {}
    classes = _vehicle_classes(fleet)
    fids = sorted({i for c in cols for i in c["ids"]})
    frow = {i: r for r, i in enumerate(fids)}
    mk_rows, fl_rows = {}, {}
    base = len(fids)
    for c in cols:
        for crop in c["qty_by_crop"]:
            mk_rows.setdefault((c["market"].id, crop), base + len(mk_rows))
    base += len(mk_rows)
    for c in cols:
        for j in range(c["cells"][0], c["cells"][1] + 1):
            fl_rows.setdefault((c["cls"], j), base + len(fl_rows))
    nrows = base + len(fl_rows)
    A = lil_matrix((nrows, len(cols)))
    ub = np.ones(nrows)
    cap_of = {m.id: m.capacity_kg for m in markets}
    cap_mult = price_impact.capacity_multiple if price_impact is not None else 1.0
    for (mid, crop), r in mk_rows.items():
        ub[r] = cap_of[mid][crop] * cap_mult
    for (key, j), r in fl_rows.items():
        t_cell = j * FLEET_DT_HR
        ub[r] = sum(1 for v in classes[key] if v.available_at_hr <= t_cell + 1e-9)
    for col, c in enumerate(cols):
        for i in c["ids"]:
            A[frow[i], col] = 1.0
        for crop, q in c["qty_by_crop"].items():
            A[mk_rows[(c["market"].id, crop)], col] = q
        for j in range(c["cells"][0], c["cells"][1] + 1):
            A[fl_rows[(c["cls"], j)], col] = 1.0
    A = A.tocsr()
    obj = -np.array([c["delta"] for c in cols])
    A, ub, obj, lb_v, ub_v, integ = _impact_extend(A, ub, obj, cols, price_impact, markets)
    meta = {"columns": len(cols), "fleet_rows": len(fl_rows), "price_impact": price_impact is not None}
    # shadow value of one more vehicle per class (LP relaxation, first order)
    try:
        lp = linprog(obj, A_ub=A, b_ub=ub, bounds=np.c_[lb_v, ub_v], method="highs")
        if lp.status == 0:
            marg = -np.asarray(lp.ineqlin.marginals)
            sv = defaultdict(float)
            for (key, _j), r in fl_rows.items():
                sv[_class_label(key)] += float(marg[r])
            meta["lp_bound"] = float(-lp.fun)
            meta["shadow_value_per_extra_vehicle"] = {k: round(v, 1) for k, v in sv.items()}
    except Exception:                                               # pragma: no cover
        pass
    try:
        res = milp(obj, constraints=LinearConstraint(A, -np.inf, ub), integrality=integ,
                   bounds=Bounds(lb_v, ub_v), options={"time_limit": SP_TIME_LIMIT_S, "mip_rel_gap": 1e-4})
        if res.x is not None and res.status in (0, 1):
            return [cols[k] for k in range(len(cols)) if res.x[k] > 0.5], (
                "optimal" if res.status == 0 else "time_limit_best_found"), meta
    except Exception:                                               # pragma: no cover
        pass
    return [], "solver_failed", meta


def assign_vehicles_to_columns(chosen, fleet):
    """Interval colouring: turn the class/slot solution into concrete vehicle ids. Returns pool_hints for
    run_our_system_v2 ({frozenset(farmer ids): {vehicle_id, start}}). Columns that cannot be placed get no hint
    (the greedy assignment then handles them)."""
    classes = _vehicle_classes(fleet)
    free = {key: [[v.available_at_hr, v.id] for v in vs] for key, vs in classes.items()}
    hints = {}
    for c in sorted(chosen, key=lambda c: (c["start"], c["cells"][0])):
        ok = [x for x in free[c["cls"]] if x[0] <= c["start"] + 1e-9]
        if not ok:
            continue
        pick = max(ok, key=lambda x: x[0])
        pick[0] = (c["cells"][1] + 1) * FLEET_DT_HR
        hints[c["ids"]] = {"vehicle_id": pick[1], "start": c["start"]}
    return hints


# ----------------------------------------------------------------------
# Phase 4: repair + gain sharing
# ----------------------------------------------------------------------
def break_even(net_return, members, prices):
    """How wrong can the assumed doorstep price be before this trip stops paying?
    The trip beats the farm gate iff the real doorstep prices are <= price_scale x the assumed ones.
      price_scale          lambda* = net_return / assumed farm-gate value of the members
      cushion_pct          100 * (lambda* - 1): % the real doorstep price may exceed the assumption
      per_kg_by_crop       break-even doorstep Rs/kg per crop (qty-weighted assumed price x lambda*)
      assumed_per_kg_by_crop   the doorstep price the planner assumed
      breakeven_discount   (only when prices = median mandi x (1 - d)) the smallest true discount d* at which
                           hauling is still worth it
    Operational rule: dispatch iff the trader's quoted doorstep price per kg is below per_kg_by_crop."""
    fg = prices.value_of(members)
    if fg <= 0:
        return None
    lam = float(net_return / fg)
    assumed, be = {}, {}
    for crop in sorted({f.crop for f in members}):
        fs = [f for f in members if f.crop == crop]
        q = sum(f.qty_kg for f in fs)
        assumed[crop] = float(sum(f.qty_kg * prices.per_kg(f) for f in fs) / q)
        be[crop] = lam * assumed[crop]
    out = {"price_scale": lam, "cushion_pct": 100.0 * (lam - 1.0), "per_kg_by_crop": be,
           "assumed_per_kg_by_crop": assumed}
    if getattr(prices, "price_fn", None) is None and not getattr(prices, "per_kg_by_crop", None):
        out["breakeven_discount"] = float(1.0 - lam * (1.0 - prices.discount))
    return out


def discount_stress(results, farmers, prices, discounts=DEFAULT_STRESS_DISCOUNTS):
    """Re-value a finished plan if the true doorstep discount were d instead of the assumed one (all doorstep
    prices scaled by (1-d)/(1-assumed d); the plan is NOT re-optimised). Per d:
      gain_dispatch_all    gain over farm-gate if every planned trip runs
      gain_with_quote_rule gain if each trip runs only when it really beats the doorstep price (live quote)
      trips_losing         planned trips that would lose to the doorstep price
    The gap between the two gains is what a live-quote dispatch rule is worth."""
    from baselines_v3 import FARMGATE_DISCOUNT
    base_d = getattr(prices, "discount", FARMGATE_DISCOUNT)
    by_id = {f.id: f for f in farmers}
    trips = [(r, [by_id[i] for i in r["farmer_ids"]]) for r in results if r["vehicle_id"] is not None]
    out = {}
    for d in discounts:
        scale = (1.0 - d) / (1.0 - base_d)
        gain_all = gain_rule = 0.0
        losing = 0
        for r, members in trips:
            delta = r["net_return"] - scale * prices.value_of(members)
            gain_all += delta
            gain_rule += max(delta, 0.0)
            losing += delta < -_EPS
        out[d] = {"gain_dispatch_all": float(gain_all), "gain_with_quote_rule": float(gain_rule),
                  "trips_losing": int(losing),
                  "trips": len(trips)}
    return out


def _repair_and_share(results, farmers, prices):
    """Drop any dispatched trip that earns less than its members' farm-gate value; then split each remaining
    trip's surplus so every farmer gets at least their own farm-gate value."""
    by_id = {f.id: f for f in farmers}
    out, dropped = [], 0
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
        r["breakeven"] = break_even(r["net_return"], members, prices)
        qty = sum(f.qty_kg for f in members)
        surplus = r["net_return"] - fg
        # value-gain sharing is the ONLY split ILO v3 reports: each farmer gets their own farm-gate value plus a
        # qty-share of the trip's surplus (sums to net_return; never below the doorstep price). The legacy
        # pro-rata-by-kg split can leave low-price-crop farmers worse off, so it is not exposed here.
        r["per_farmer_net"] = {f.id: prices.value(f) + surplus * f.qty_kg / qty for f in members}
        out.append(r)
    return out, {"trips_dropped_below_farmgate": dropped}


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
               safeguard=True, repair=True, return_meta=False, return_trace=False,
               fleet_aware=True, keep_blind_plan=True, price_impact=None, true_price_impact=None,
               stress_discounts=DEFAULT_STRESS_DISCOUNTS, mc_draws=0, mc_min_prob=None, mc_kwargs=None,
               markets_per_trip=None):
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
    # price_impact = what the planner BELIEVES (drives the set-partitioning MILP); true_price_impact = how plans
    # are simulated and scored (default: same as the belief). Splitting them lets you stress a wrong elasticity.
    acct = true_price_impact if true_price_impact is not None else price_impact
    belief_mult = price_impact.capacity_multiple if price_impact is not None else 1.0       # planner's capacity belief
    if markets_per_trip is None:                       # with price impact a trip needs several mandi options
        markets_per_trip = 3 if price_impact is not None else 1
    if acct is not None:                                # volume-dependent mandi prices in the simulator/baselines
        kw["elastic_pricing"] = acct
        kw["top_k"] = min(len(markets) * len(acct.breakpoints), 64)            # LP must see every tranche node
    S = lambda res: summarize_with_farmgate(res, farmers, markets, fs, prices=prices)["net_return_incl_farmgate"]  # noqa: E731

    plans, traces = {}, {}
    plans["A:ilo_pools"], traces["A:ilo_pools"] = run_our_system_v2(farmers, copy.deepcopy(fleet), markets,
                                                                    return_trace=True, **kw)
    meta = {"params": {"discount": prices.discount, "dispatch_margin": dispatch_margin,
                       "consolidate": consolidate, "set_partition": set_partition, "price_impact": price_impact is not None,
                       "true_price_impact": acct is not None, "capacity_multiple_belief": belief_mult,
                       "safeguard": safeguard, "repair": repair}}
    if set_partition and farmers:
        t1 = time.time()
        cands, cstats = generate_candidates(farmers, fleet, markets, prices, dispatch_margin, consolidate,
                                            cap_mult=belief_mult, markets_per_trip=markets_per_trip)
        chosen, sp_status = solve_set_partition(cands, markets, price_impact)
        covered = {i for c in chosen for i in c["ids"]}
        pools = [c["order"] for c in chosen] + [[f] for f in farmers if f.id not in covered]
        blind_name = "B0:set_partition_fleet_blind" if fleet_aware else "B:set_partition"
        if (not fleet_aware) or keep_blind_plan:
            plans[blind_name], traces[blind_name] = run_our_system_v2(
                farmers, copy.deepcopy(fleet), markets, raw_pools_override=pools, return_trace=True, **kw)
        fl_meta = {}
        if fleet_aware and fleet:
            cols = expand_fleet_columns(cands, fleet, markets, prices, dispatch_margin, cap_mult=belief_mult,
                                        keep_market=markets_per_trip > 1)
            fchosen, fl_status, fl_meta = solve_fleet_set_partition(cols, markets, fleet, price_impact)
            fl_meta["status"] = fl_status
            if fl_status in ("optimal", "time_limit_best_found"):
                hints = assign_vehicles_to_columns(fchosen, fleet)
                fcov = {i for c in fchosen for i in c["ids"]}
                fpools = [c["order"] for c in fchosen] + [[f] for f in farmers if f.id not in fcov]
                plans["B:set_partition"], traces["B:set_partition"] = run_our_system_v2(
                    farmers, copy.deepcopy(fleet), markets, raw_pools_override=fpools, pool_hints=hints,
                    return_trace=True, **kw)
                fl_meta["trips_chosen"] = len(fchosen)
                fl_meta["hints_placed"] = len(hints)
                fl_meta["classes_used"] = {_class_label(k): sum(1 for c in fchosen if c["cls"] == k)
                                           for k in {c["cls"] for c in fchosen}}
            elif blind_name not in plans:
                plans[blind_name], traces[blind_name] = run_our_system_v2(
                    farmers, copy.deepcopy(fleet), markets, raw_pools_override=pools, return_trace=True, **kw)
        meta["fleet_aware"] = fl_meta
        meta["candidates"] = {"total_kept": len(cands), **cstats, "sp_status": sp_status,
                              "sp_trips_chosen": len(chosen),
                              "sp_trips_chosen_by_source": {
                                  src: sum(1 for c in chosen if c["source"] == src)
                                  for src in {c["source"] for c in chosen}},
                              "sp_seconds": round(time.time() - t1, 2)}

    if safeguard:
        true_mult = acct.capacity_multiple if acct is not None else 1.0                 # the scoring world's capacity

        def mk():
            cap = fresh_capacity(markets)
            return {mid: {c: v * true_mult for c, v in d.items()} for mid, d in cap.items()}
        plans["fallback:farm_gate_only"] = run_farmgate_baseline_v2(farmers, markets)
        for tag, beh in (("rational", None), ("behavioural", DEFAULT_BEHAVIOUR)):
            plans[f"fallback:self_haul_{tag}"] = run_self_haul_v2(farmers, fleet, markets, mk(), prices=prices,
                                                                   behaviour=beh, price_impact=acct)
            plans[f"fallback:neighbour_{tag}"] = run_neighbour_pooling_v2(farmers, fleet, markets, mk(), prices=prices,
                                                                          behaviour=beh, price_impact=acct)
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
    if mc_draws:                                   # Monte Carlo replay of the finished plan (stress.py)
        from stress import monte_carlo_stress, withhold_fragile
        mc = monte_carlo_stress(results, farmers, fleet, markets, prices, n_draws=mc_draws, price_impact=acct,
                                **(mc_kwargs or {}))
        meta["monte_carlo"] = mc["plan"]
        for r in results:                          # attach per-trip probabilities
            if r["vehicle_id"] is not None:
                t = next((t for t in mc["trips"] if frozenset(t["farmer_ids"]) == frozenset(r["farmer_ids"])), None)
                if t is not None:
                    r["mc"] = {k: t[k] for k in ("p_beat", "p_lost", "mean_gain", "p5_gain")}
        if mc_min_prob is not None:
            results, n_w = withhold_fragile(results, farmers, mc, mc_min_prob)
            meta["monte_carlo"]["trips_withheld_as_fragile"] = n_w
            meta["final_value"] = S(results)
    if stress_discounts:
        meta["discount_stress"] = discount_stress(results, farmers, prices, stress_discounts)
    meta["seconds"] = round(time.time() - t0, 2)
    if return_trace:
        return results, meta, _trace_json(trace, results)
    return (results, meta) if return_meta else results
