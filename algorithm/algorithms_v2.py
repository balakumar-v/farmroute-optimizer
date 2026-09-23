"""
algorithms_v2.py
-----------------
Redesigned for scale. Two structural fixes from the v1 audit, applied to
ALL THREE algorithms (so the comparison stays fair -- we're not fixing
"Our System"'s bugs while leaving baselines broken):

  A) Fleet-constrained assignment: vehicles are now finite instances with
     an available_at_hr that gets updated as they're used (and can be
     reused later the same day -- simple multi-trip modeling). A pool
     that can't get a vehicle in time is genuinely unserved. v1 let
     unlimited vehicles dispatch "simultaneously."
  B) Market allocation is a single linear program per crop, solved
     jointly across every pool competing for that crop's markets
     (scipy.optimize.linprog, HiGHS backend) instead of a greedy pass
     in an arbitrary pool order. This removes the "whoever gets
     processed first wins the market" artifact and is provably optimal
     for the stated objective.

Only "Our System" gets the smart parts: multi-market LP allocation and
crop/time-aware pooling. The baselines keep their original (naive)
decision logic -- they just no longer get to cheat with an infinite
fleet.
"""

import itertools
import math
from collections import defaultdict
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import lil_matrix

from logistics_lib_v2 import (
    haversine, spoilage_fraction, CROPS,
    AVG_SPEED_KMPH, DISPATCH_OVERHEAD_HR, STOP_OVERHEAD_HR,
    TURNAROUND_HR, WORKDAY_END_HR, market_demand_nodes,
)

try:
    from sklearn.cluster import DBSCAN
    _HAVE_SKLEARN = True
except ImportError:
    _HAVE_SKLEARN = False

EPS_KM = 12.0
EARTH_R_KM = 6371.0


# ----------------------------------------------------------------------
# Fast geo-clustering: metric='haversine' + ball_tree avoids ever
# building an O(n^2) distance matrix, so this stays cheap into the
# tens of thousands of points (v1 built a full pairwise matrix).
# ----------------------------------------------------------------------
def _dbscan_clusters(farmer_list, eps_km=EPS_KM):
    if len(farmer_list) <= 1:
        return [farmer_list]
    if not _HAVE_SKLEARN:
        return [farmer_list]
    coords = np.radians([[f.lat, f.lng] for f in farmer_list])
    labels = DBSCAN(eps=eps_km / EARTH_R_KM, min_samples=1,
                     metric="haversine", algorithm="ball_tree").fit(coords).labels_
    groups = defaultdict(list)
    for f, lab in zip(farmer_list, labels):
        groups[lab].append(f)
    return list(groups.values())


# A "depot" grid cell, in degrees latitude. DBSCAN's single-link chaining
# means a cluster's end-to-end span isn't bounded by eps_km -- a chain of
# points each within eps_km of a neighbor can span far more than eps_km
# overall. Verified by testing at n=10,000: average pickup-route length
# ballooned to ~290km because clusters spanned the whole (growing)
# coverage area. Partitioning into depot-sized grid cells first bounds
# how far any single pool's stops can be from each other, independent of
# how large the total service area gets -- a cheap stand-in for real
# depot/hub routing.
DEPOT_CELL_KM = 2.2 * EPS_KM


def _grid_partition(farmer_list, cell_km=DEPOT_CELL_KM):
    if not farmer_list:
        return []
    cells = defaultdict(list)
    for f in farmer_list:
        lat_step = cell_km / 111.0
        lng_step = cell_km / max(1e-6, 111.0 * math.cos(math.radians(f.lat)))
        cells[(int(f.lat // lat_step), int(f.lng // lng_step))].append(f)
    return list(cells.values())


def _geo_clusters(farmer_list, eps_km=EPS_KM):
    """Depot partition first (bounds cluster span to the service area's
    growth), then DBSCAN within each depot cell."""
    clusters = []
    for cell in _grid_partition(farmer_list):
        clusters.extend(_dbscan_clusters(cell, eps_km=eps_km))
    return clusters


def _split_by_time_window(cluster):
    cluster = sorted(cluster, key=lambda f: f.ready_hr)
    groups, current, lo, hi = [], [], None, None
    for f in cluster:
        if current:
            new_lo, new_hi = max(lo, f.ready_hr), min(hi, f.deadline_hr)
        else:
            new_lo, new_hi = f.ready_hr, f.deadline_hr
        if new_lo <= new_hi:
            current.append(f)
            lo, hi = new_lo, new_hi
        else:
            groups.append(current)
            current, lo, hi = [f], f.ready_hr, f.deadline_hr
    if current:
        groups.append(current)
    return groups


def _bin_pack(farmer_list, max_cap):
    """Simple fixed-ceiling bin-pack, kept for the naive baseline and
    for callers that don't have a fleet mix to draw from."""
    items = sorted(farmer_list, key=lambda f: -f.qty_kg)
    bins = []
    for f in items:
        for b in bins:
            if b[1] + f.qty_kg <= max_cap:
                b[0].append(f)
                b[1] += f.qty_kg
                break
        else:
            bins.append([[f], f.qty_kg])
    return [b[0] for b in bins]


def _sweep_order(farmer_list):
    """Gillett-Miller sweep: sort by angle around the group's centroid.
    O(n log n), no pairwise distance matrix. Used so that bin-packing
    walks a spatially contiguous path instead of a weight-sorted one --
    see _bin_pack_fleet_aware for why that matters."""
    if len(farmer_list) <= 2:
        return list(farmer_list)
    clat = sum(f.lat for f in farmer_list) / len(farmer_list)
    clng = sum(f.lng for f in farmer_list) / len(farmer_list)
    return sorted(farmer_list, key=lambda f: math.atan2(f.lat - clat, f.lng - clng))


def fleet_capacity_cycle(fleet):
    """A REPEATING menu of the fleet's capacity mix (sorted descending),
    as an infinite round-robin iterator. Pool ceilings are drawn from
    this in proportion to the fleet's actual composition, so a fleet
    that's mostly 2000kg trucks with a few 5000kg trucks mostly forms
    2000kg-ish pools.

    This must NOT be a one-shot queue that empties after len(fleet)
    pools -- verified by testing at n=10,000: with a one-shot queue,
    once it ran dry every remaining pool silently collapsed to ~1
    farmer, because a fleet of 250 vehicles legitimately needs to
    serve thousands of pools over a day via multi-trip reuse (that's
    the whole point of the deadline-based reuse fix). The menu just
    needs to keep handing out a realistic SIZE for each new pool, not
    ration a fixed count of them.
    """
    menu = sorted((v.capacity_kg for v in fleet), reverse=True) or [1.0]
    return itertools.cycle(menu)


def _bin_pack_fleet_aware(farmer_list, capacity_cycle):
    """Like _bin_pack, but each new pool's capacity ceiling is drawn from
    the fleet's real capacity distribution (via the shared capacity_slots
    queue) instead of always being the single largest vehicle in the
    fleet. This is the fix for a real failure mode found while testing
    this redesign: bin-packing to one global max ceiling bundles nearly
    every farmer into a near-max-capacity load, so only the (usually few)
    largest trucks can ever serve them, while every smaller/mid-size
    vehicle sits idle. Sizing pools from the fleet mix instead lets
    small and mid trucks actually get used.

    Simplification: which geo-cluster "claims" the large-capacity slots
    first is whichever is processed first (arbitrary order) -- this is
    the same kind of order artifact the v1 audit found in market
    allocation, just for vehicle-size matching instead. Left as a known
    limitation rather than solved jointly (see write-up).

    Walks a SPATIAL sweep order (see _sweep_order), not a weight-sorted
    one. Bin-packing by descending weight (the v1/early-v2 approach)
    picks farmers for the same pool purely by how well their quantities
    add up, with no regard for where they actually are -- verified by
    testing this at n=1000, that produced pools whose pickup route took
    over 40 simulated hours because a single "pool" could contain
    farmers from opposite ends of a sprawling geo-cluster. Packing along
    a spatial walk keeps each pool a geographically contiguous slice.
    """
    items = _sweep_order(farmer_list)
    bins = []
    cur, cur_w, cur_cap = [], 0.0, None
    for f in items:
        if cur and cur_w + f.qty_kg > cur_cap:
            bins.append(cur)
            cur, cur_w, cur_cap = [], 0.0, None
        if not cur:
            cur_cap = max(next(capacity_cycle), f.qty_kg)
        cur.append(f)
        cur_w += f.qty_kg
    if cur:
        bins.append(cur)
    return bins


def _route_distance(order):
    return sum(haversine(order[i].lat, order[i].lng, order[i + 1].lat, order[i + 1].lng)
               for i in range(len(order) - 1))


def _simulate_end_time(order, enforce_windows):
    t = DISPATCH_OVERHEAD_HR
    for i, f in enumerate(order):
        if i > 0:
            t += haversine(order[i - 1].lat, order[i - 1].lng, f.lat, f.lng) / AVG_SPEED_KMPH
        t = max(t, f.ready_hr)
        if enforce_windows and t > f.deadline_hr:
            return False, None
        t += STOP_OVERHEAD_HR
    return True, t


def _nearest_neighbor_order(pool):
    remaining = sorted(pool, key=lambda f: f.ready_hr)
    order = [remaining.pop(0)]
    while remaining:
        last = order[-1]
        nxt = min(remaining, key=lambda f: haversine(last.lat, last.lng, f.lat, f.lng))
        remaining.remove(nxt)
        order.append(nxt)
    return order


def _two_opt(order, max_iters=100):
    improved = True
    it = 0
    while improved and it < max_iters:
        improved = False
        it += 1
        for i in range(1, len(order) - 1):
            for j in range(i + 1, len(order)):
                new_order = order[:i] + order[i:j + 1][::-1] + order[j + 1:]
                if _route_distance(new_order) < _route_distance(order):
                    order = new_order
                    improved = True
    return order


def order_route(pool, enforce_windows=True):
    """Brute force only for tiny pools (<=7) -- kept small on purpose
    so it never becomes the scaling bottleneck; nearest-neighbor+2-opt
    for everything else (this is unchanged from v1's approach, which
    the audit found scales fine since pool sizes stay bounded by
    vehicle capacity)."""
    if len(pool) <= 1:
        t_end = DISPATCH_OVERHEAD_HR + (pool[0].ready_hr if pool else 0) + (STOP_OVERHEAD_HR if pool else 0)
        return pool, 0.0, t_end
    if len(pool) <= 7:
        best = None
        for perm in itertools.permutations(pool):
            feasible, t_end = _simulate_end_time(list(perm), enforce_windows)
            if enforce_windows and not feasible:
                continue
            dist = _route_distance(list(perm))
            if best is None or dist < best[1]:
                _, t_end_actual = _simulate_end_time(list(perm), enforce_windows=False)
                best = (list(perm), dist, t_end_actual)
        if best:
            return best
        order = _nearest_neighbor_order(pool)
        _, t_end = _simulate_end_time(order, enforce_windows=False)
        return order, _route_distance(order), t_end
    order = _two_opt(_nearest_neighbor_order(pool))
    _, t_end = _simulate_end_time(order, enforce_windows=False)
    return order, _route_distance(order), t_end


# ----------------------------------------------------------------------
# A) Fleet-constrained assignment (real, finite fleet; multi-trip reuse)
# ----------------------------------------------------------------------
def assign_fleet(pool_descs, fleet):
    """pool_descs: list of dicts with 'total_qty', 'needs_refrigeration',
    'ready_hr', 'deadline_hr', 'route_duration' (pickup-leg duration,
    i.e. this pool's originally-simulated t_end minus DISPATCH_OVERHEAD_HR
    -- travel + stop time, independent of what hour the vehicle actually
    starts). Mutates each vehicle's available_at_hr. Returns a list of
    (Vehicle | None, actual_completion_hr | None), aligned to pool_descs.

    Processed in ready_hr order (chronological dispatch), best-fit
    (smallest vehicle that both fits and can still make the deadline),
    with a preference for refrigerated trucks when the pool needs it.

    A real bug lived here in an earlier version: candidates were
    required to already be free *before* the pool's ready_hr. Since
    every pool becomes ready in the first few hours while a single
    trip commonly takes longer than that, no vehicle could ever
    qualify for a second trip -- multi-trip reuse silently never fired.
    The fix is to check the pool's *deadline* instead: a vehicle that's
    still mid-turnaround when a pool becomes ready can dispatch late
    and still make it, as long as it's free before the deadline.
    """
    n = len(pool_descs)
    assigned = [None] * n
    completions = [None] * n
    order = sorted(range(n), key=lambda i: pool_descs[i]["ready_hr"])
    for i in order:
        p = pool_descs[i]
        if p["ready_hr"] > WORKDAY_END_HR:
            continue
        cands = []
        for v in fleet:
            if v.capacity_kg < p["total_qty"]:
                continue
            dispatch_start = max(v.available_at_hr, p["ready_hr"])
            if dispatch_start > WORKDAY_END_HR:
                continue
            completion = dispatch_start + p["route_duration"]
            if completion > p["deadline_hr"]:
                continue
            cands.append((v, completion))
        if not cands:
            continue
        if p["needs_refrigeration"]:
            ref = [c for c in cands if c[0].refrigerated]
            if ref:
                cands = ref
        v, completion = min(cands, key=lambda c: c[0].capacity_kg)
        v.available_at_hr = completion + TURNAROUND_HR
        assigned[i] = v
        completions[i] = completion
    return assigned, completions


# ----------------------------------------------------------------------
# B) Global LP market allocation (one crop at a time)
# ----------------------------------------------------------------------
def allocate_markets_lp(pool_infos, crop, markets, elastic_pricing=False, tranches=3, top_k=6):
    """pool_infos: list of dicts with 'total_qty', 'last_point' (lat,lng),
    't_after_pickup', 'vehicle'. Returns a list (aligned to pool_infos)
    of dicts: revenue, spoil_loss_kg, market_legs_km, unsold_kg, markets_used.

    Sparsified to the top_k markets/tranches per pool by net value/kg --
    keeps the LP's variable count linear in pool count regardless of
    how many markets exist, which is what keeps this tractable at scale.
    """
    nodes = market_demand_nodes(markets, crop, elastic_pricing, tranches)
    n_pools = len(pool_infos)
    n_nodes = len(nodes)
    result = [{"revenue": 0.0, "spoil_loss_kg": 0.0, "market_dist": {}, "unsold_kg": p["total_qty"]}
              for p in pool_infos]
    if n_pools == 0 or n_nodes == 0:
        return result

    edges = []  # (pool_idx, node_idx, net_val, dist, spoil)
    for pi, p in enumerate(pool_infos):
        cand = []
        for ni, node in enumerate(nodes):
            m = node["market"]
            dist = haversine(p["last_point"][0], p["last_point"][1], m.lat, m.lng)
            transit_hr = p["t_after_pickup"] + dist / AVG_SPEED_KMPH
            spoil = spoilage_fraction(crop, p["vehicle"].refrigerated, transit_hr)
            transport_per_kg = (p["vehicle"].per_km_cost * dist) / max(p["total_qty"], 1)
            net_val = node["price"] * (1 - spoil) - transport_per_kg
            cand.append((net_val, ni, dist, spoil))
        cand.sort(key=lambda c: -c[0])
        for net_val, ni, dist, spoil in cand[:top_k]:
            edges.append((pi, ni, net_val, dist, spoil))

    if not edges:
        return result

    n_edges = len(edges)
    c = np.array([-e[2] for e in edges])  # maximize net_val == minimize -net_val
    A_ub = lil_matrix((n_pools + n_nodes, n_edges))
    b_ub = np.zeros(n_pools + n_nodes)
    for ei, (pi, ni, *_r) in enumerate(edges):
        A_ub[pi, ei] = 1
        A_ub[n_pools + ni, ei] = 1
    for pi, p in enumerate(pool_infos):
        b_ub[pi] = p["total_qty"]
    for ni, node in enumerate(nodes):
        b_ub[n_pools + ni] = node["capacity_kg"]

    res = linprog(c, A_ub=A_ub.tocsr(), b_ub=b_ub, bounds=(0, None), method="highs")
    if not res.success:
        return result  # solver failure -> treat conservatively as unsold

    x = res.x
    for ei, (pi, ni, net_val, dist, spoil) in enumerate(edges):
        take = x[ei]
        if take <= 1e-6:
            continue
        node = nodes[ni]
        m_id = node["market"].id
        r = result[pi]
        r["revenue"] += take * node["price"] * (1 - spoil)
        r["spoil_loss_kg"] += take * spoil
        r["unsold_kg"] -= take
        if m_id not in r["market_dist"]:
            r["market_dist"][m_id] = dist  # same physical stop even if multiple tranches
    for r in result:
        r["unsold_kg"] = max(0.0, r["unsold_kg"])
    return result


# ----------------------------------------------------------------------
# Shared: turn a finished pool (possibly multiple crops, one per
# allocation entry) into the standard result dict.
# ----------------------------------------------------------------------
def _finalize(pool, vehicle, order, route_dist, allocs):
    total_qty = sum(f.qty_kg for f in pool)
    revenue = sum(a["revenue"] for a in allocs)
    spoil_loss_kg = sum(a["spoil_loss_kg"] for a in allocs)
    unsold_kg = sum(a["unsold_kg"] for a in allocs)
    market_dist = {}
    for a in allocs:
        market_dist.update(a["market_dist"])  # same distance regardless of which crop reached it
    market_legs_km = sum(market_dist.values())
    transport_cost = vehicle.fixed_cost + vehicle.per_km_cost * (route_dist + market_legs_km)
    net_return = revenue - transport_cost
    per_farmer = {f.id: (f.qty_kg / total_qty) * net_return for f in pool} if total_qty else {}
    return {
        "farmer_ids": [f.id for f in pool], "vehicle_id": vehicle.id,
        "markets_used": sorted(market_dist.keys()), "total_qty_kg": total_qty,
        "revenue": revenue, "transport_cost": transport_cost,
        "spoilage_loss_kg": spoil_loss_kg, "unsold_kg": unsold_kg,
        "unserved_no_vehicle_kg": 0.0, "net_return": net_return, "per_farmer_net": per_farmer,
        "infeasible": False,
    }


def _no_vehicle_result(pool):
    q = sum(f.qty_kg for f in pool)
    return {
        "farmer_ids": [f.id for f in pool], "vehicle_id": None, "markets_used": [],
        "total_qty_kg": q, "revenue": 0.0, "transport_cost": 0.0, "spoilage_loss_kg": 0.0,
        "unsold_kg": 0.0, "unserved_no_vehicle_kg": q, "net_return": 0.0,
        "per_farmer_net": {f.id: 0.0 for f in pool}, "infeasible": True,
    }


# ----------------------------------------------------------------------
# 1. OUR SYSTEM v2
#    Pooling is now MIXED-CROP: a truck can carry tomatoes from one
#    farmer and onions from another on the same trip (it just sells
#    each crop's share separately downstream). v1/early-v2 pooled
#    strictly within one crop, which -- verified by actually running
#    this at n=30 -- produced more, smaller pools than a crop-blind
#    baseline and lost more of them to vehicle scarcity than it
#    gained from smarter market allocation. Mixing crops recovers the
#    trip-count advantage while keeping per-crop LP allocation.
# ----------------------------------------------------------------------
def run_our_system_v2(farmers, fleet, markets, elastic_pricing=False, top_k=6):
    capacity_slots = fleet_capacity_cycle(fleet)
    raw_pools = []
    for gc in _geo_clusters(farmers):  # crop-blind clustering
        for tg in _split_by_time_window(gc):  # still crop-blind; only timing matters here
            raw_pools.extend(_bin_pack_fleet_aware(tg, capacity_slots))
    raw_pools.sort(key=lambda p: min(f.id for f in p))

    # Route every pool first (route timing doesn't depend on which
    # vehicle gets assigned -- speed is modeled as constant).
    routed = []
    for pool in raw_pools:
        order, route_dist, t_end = order_route(pool, enforce_windows=True)
        routed.append((pool, order, route_dist, t_end))

    pool_descs = [{
        "total_qty": sum(f.qty_kg for f in pool),
        "needs_refrigeration": any(f.needs_refrigeration for f in pool),
        "ready_hr": min(f.ready_hr for f in pool),
        "deadline_hr": min(f.deadline_hr for f in pool),
        "route_duration": t_end - DISPATCH_OVERHEAD_HR,
    } for pool, order, route_dist, t_end in routed]

    vehicles_assigned, completions = assign_fleet(pool_descs, fleet)

    results = [None] * len(routed)
    pool_alloc_lists = defaultdict(list)   # pool_idx -> list of per-crop alloc dicts
    by_crop_lp = defaultdict(list)         # crop -> list of (pool_idx, pool_info)
    for i, ((pool, order, route_dist, t_end), vehicle) in enumerate(zip(routed, vehicles_assigned)):
        if vehicle is None:
            results[i] = _no_vehicle_result(pool)
            continue
        last_point = (order[-1].lat, order[-1].lng)
        by_crop_in_pool = defaultdict(list)
        for f in pool:
            by_crop_in_pool[f.crop].append(f)
        for crop, flist in by_crop_in_pool.items():
            by_crop_lp[crop].append((i, {
                "total_qty": sum(f.qty_kg for f in flist), "last_point": last_point,
                "t_after_pickup": completions[i], "vehicle": vehicle,
            }))

    for crop, entries in by_crop_lp.items():
        infos = [e[1] for e in entries]
        allocs = allocate_markets_lp(infos, crop, markets, elastic_pricing=elastic_pricing, top_k=top_k)
        for (i, info), alloc in zip(entries, allocs):
            pool_alloc_lists[i].append(alloc)

    for i, (pool, order, route_dist, t_end) in enumerate(routed):
        if results[i] is not None:
            continue  # already a _no_vehicle_result
        vehicle = vehicles_assigned[i]
        results[i] = _finalize(pool, vehicle, order, route_dist, pool_alloc_lists[i])
    return results


# ----------------------------------------------------------------------
# 2. INDIVIDUAL TRANSPORT v2 -- same fleet constraint, no pooling,
#    no multi-market split (single best market per farmer, no fallback).
#    remaining_cap: dict market_id -> {crop: kg left}, a real depleting
#    ledger shared across this run (mirrors v1's semantics).
# ----------------------------------------------------------------------
def run_individual_transport_v2(farmers, fleet, markets, remaining_cap):
    order_f = sorted(farmers, key=lambda f: f.ready_hr)
    t_ends = {f.id: _simulate_end_time([f], enforce_windows=False)[1] for f in order_f}
    pool_descs = [{
        "total_qty": f.qty_kg, "needs_refrigeration": f.needs_refrigeration,
        "ready_hr": f.ready_hr, "deadline_hr": f.deadline_hr,
        "route_duration": t_ends[f.id] - DISPATCH_OVERHEAD_HR,
    } for f in order_f]
    vehicles_assigned, completions = assign_fleet(pool_descs, fleet)

    results = []
    for f, vehicle, completion in zip(order_f, vehicles_assigned, completions):
        if vehicle is None:
            results.append(_no_vehicle_result([f]))
            continue
        t_after_pickup = completion
        last_point = (f.lat, f.lng)
        best = None
        for m in markets:
            dist = haversine(last_point[0], last_point[1], m.lat, m.lng)
            transit_hr = t_after_pickup + dist / AVG_SPEED_KMPH
            spoil = spoilage_fraction(f.crop, vehicle.refrigerated, transit_hr)
            transport_per_kg = (vehicle.per_km_cost * dist) / max(f.qty_kg, 1)
            net_val = m.price[f.crop] * (1 - spoil) - transport_per_kg
            if best is None or net_val > best[0]:
                best = (net_val, m, dist, spoil)
        _, m, dist, spoil = best
        avail = max(remaining_cap[m.id][f.crop], 0)
        sold = min(f.qty_kg, avail)
        remaining_cap[m.id][f.crop] -= sold
        revenue = sold * m.price[f.crop] * (1 - spoil)
        spoil_loss_kg = sold * spoil
        transport_cost = vehicle.fixed_cost + vehicle.per_km_cost * dist
        net_return = revenue - transport_cost
        results.append({
            "farmer_ids": [f.id], "vehicle_id": vehicle.id, "markets_used": [m.id],
            "total_qty_kg": f.qty_kg, "revenue": revenue, "transport_cost": transport_cost,
            "spoilage_loss_kg": spoil_loss_kg, "unsold_kg": f.qty_kg - sold,
            "unserved_no_vehicle_kg": 0.0, "net_return": net_return,
            "per_farmer_net": {f.id: net_return}, "infeasible": False,
        })
    return results


# ----------------------------------------------------------------------
# 3. PROXIMITY POOLING v2 -- geography only, single highest LISTED
#    price market, capacity ignored at selection time (matches v1's
#    naive baseline exactly). Same fleet constraint as the others.
# ----------------------------------------------------------------------
def run_proximity_pooling_v2(farmers, fleet, markets, remaining_cap):
    capacity_slots = fleet_capacity_cycle(fleet)
    raw_pools = []
    for gc in _geo_clusters(farmers):  # crop-blind
        raw_pools.extend(_bin_pack_fleet_aware(gc, capacity_slots))
    raw_pools.sort(key=lambda p: min(f.id for f in p))

    routed = []
    for pool in raw_pools:
        order = _nearest_neighbor_order(pool)
        _, t_end = _simulate_end_time(order, enforce_windows=False)
        routed.append((pool, order, t_end))

    pool_descs = [{
        "total_qty": sum(f.qty_kg for f in pool), "needs_refrigeration": False,  # naive: never checks
        "ready_hr": min(f.ready_hr for f in pool), "deadline_hr": min(f.deadline_hr for f in pool),
        "route_duration": t_end - DISPATCH_OVERHEAD_HR,
    } for pool, order, t_end in routed]
    vehicles_assigned, completions = assign_fleet(pool_descs, fleet)

    results = []
    for (pool, order, t_end), vehicle, completion in zip(routed, vehicles_assigned, completions):
        if vehicle is None:
            results.append(_no_vehicle_result(pool))
            continue
        last_point = (order[-1].lat, order[-1].lng)
        by_crop = defaultdict(list)
        for f in pool:
            by_crop[f.crop].append(f)
        revenue, spoil_loss_kg, market_legs_km, unsold, markets_used = 0.0, 0.0, 0.0, 0.0, []
        for crop, flist in by_crop.items():
            qty = sum(f.qty_kg for f in flist)
            m = max(markets, key=lambda mk: mk.price[crop])
            dist = haversine(last_point[0], last_point[1], m.lat, m.lng)
            transit_hr = completion + dist / AVG_SPEED_KMPH
            spoil = spoilage_fraction(crop, vehicle.refrigerated, transit_hr)
            avail = max(remaining_cap[m.id][crop], 0)
            sold = min(qty, avail)
            remaining_cap[m.id][crop] -= sold
            revenue += sold * m.price[crop] * (1 - spoil)
            spoil_loss_kg += sold * spoil
            market_legs_km += dist
            unsold += qty - sold
            markets_used.append(m.id)
        route_dist = _route_distance(order)
        transport_cost = vehicle.fixed_cost + vehicle.per_km_cost * (route_dist + market_legs_km)
        net_return = revenue - transport_cost
        total_qty = sum(f.qty_kg for f in pool)
        per_farmer = {f.id: (f.qty_kg / total_qty) * net_return for f in pool} if total_qty else {}
        results.append({
            "farmer_ids": [f.id for f in pool], "vehicle_id": vehicle.id,
            "markets_used": sorted(set(markets_used)), "total_qty_kg": total_qty,
            "revenue": revenue, "transport_cost": transport_cost,
            "spoilage_loss_kg": spoil_loss_kg, "unsold_kg": unsold,
            "unserved_no_vehicle_kg": 0.0, "net_return": net_return,
            "per_farmer_net": per_farmer, "infeasible": False,
        })
    return results


# ----------------------------------------------------------------------
# Summary helper
# ----------------------------------------------------------------------
def summarize(results, n_farmers, fleet_size):
    total_revenue = sum(r["revenue"] for r in results)
    total_cost = sum(r["transport_cost"] for r in results)
    total_spoil_kg = sum(r["spoilage_loss_kg"] for r in results)
    total_unsold_kg = sum(r["unsold_kg"] for r in results)
    total_unserved_kg = sum(r["unserved_no_vehicle_kg"] for r in results)
    total_qty = sum(r["total_qty_kg"] for r in results)
    net_return = total_revenue - total_cost
    vehicles_used = len({r["vehicle_id"] for r in results if r["vehicle_id"] is not None})
    per_farmer_net = {}
    for r in results:
        per_farmer_net.update(r["per_farmer_net"])
    return {
        "total_revenue": total_revenue, "total_transport_cost": total_cost,
        "total_spoilage_kg": total_spoil_kg, "total_unsold_kg": total_unsold_kg,
        "total_unserved_no_vehicle_kg": total_unserved_kg, "total_qty_kg": total_qty,
        "net_return": net_return, "net_return_per_farmer": net_return / n_farmers if n_farmers else 0,
        "vehicles_used": vehicles_used,
        "vehicle_utilization_pct": 100 * vehicles_used / fleet_size if fleet_size else 0,
        "pools_formed": len(results),
        "pct_qty_served": 100 * (1 - (total_unsold_kg + total_unserved_kg) / total_qty) if total_qty else 0,
    }
