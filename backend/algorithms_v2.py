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
import random
from collections import defaultdict
from dataclasses import dataclass, field
import numpy as np
from scipy.optimize import linprog, linear_sum_assignment
from scipy.sparse import lil_matrix

from logistics_lib_v2 import (
    haversine, get_road_circuity, spoilage_fraction, spoilage_fraction_from_temp, CROPS,
    AVG_SPEED_KMPH, DISPATCH_OVERHEAD_HR, STOP_OVERHEAD_HR,
    TURNAROUND_HR, WORKDAY_END_HR, market_demand_nodes,
    FARMERS_PER_DEPOT, DEPOT_CELL_KM, _grid_partition, _depot_partition,
)

try:
    from sklearn.cluster import DBSCAN, KMeans
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
    labels = DBSCAN(eps=eps_km / get_road_circuity() / EARTH_R_KM, min_samples=1,   # eps is road-km
                     metric="haversine", algorithm="ball_tree").fit(coords).labels_
    groups = defaultdict(list)
    for f, lab in zip(farmer_list, labels):
        groups[lab].append(f)
    return list(groups.values())


# Fixed-size grid partition -- kept only as the fallback for when sklearn
# isn't available (KMeans needs it too). Superseded as the default path
# by _depot_partition() below. NOTE: _grid_partition, DEPOT_CELL_KM,
# FARMERS_PER_DEPOT and _depot_partition itself now live in
# logistics_lib_v2.py (imported above) so that depot_aware_fleet_
# composition() there can size the fleet off the exact same partition
# this module clusters with -- a single source of truth instead of two
# copies that could drift apart.

# Depot placement (replaces the grid partition as the default). A fixed
# grid only bounds how far apart a pool's stops can be -- it doesn't
# adapt to where farmers actually are, so a sparse cell forms a small,
# inefficient pool right next to a dense cell forming an oversized one.
# K-means places a small number of depots where the density actually is
# and assigns each farmer to their nearest one (exactly what a k-means
# label is), which produces more evenly-sized, tighter pools -- shorter
# average routes mean faster vehicle turnaround, which is what actually
# moves the coverage-plateau number (more trips/vehicle/day for the same
# fleet), not just tighter geography for its own sake.
#
# FARMERS_PER_DEPOT is tied to the fleet-sizing ratio
# (depot_aware_fleet_composition() in logistics_lib_v2.py also uses this
# same constant, ~1 vehicle per 40 farmers) so a depot's expected demand
# is roughly one vehicle-load's worth -- a reasoned default, not a
# fitted one.
#
# Depot placement alone does NOT fix the underlying cause the write-up
# named (a flat vehicles-per-farmer ratio that ignores local density) --
# it only makes each vehicle's trips more efficient. That's now
# addressed separately by depot_aware_fleet_composition() in
# logistics_lib_v2.py, which sizes the fleet off this same partition.
# Re-run benchmark_v2.py after any change here; see
# ALGORITHM_AND_RESULTS_V2.md for what past changes actually did to the
# numbers, not just this claim.


def _geo_clusters(farmer_list, eps_km=EPS_KM, scarcity_eps=None):
    """Depot partition first (bounds cluster span to the service area's
    growth, now density-adaptive via k-means), then DBSCAN within each
    depot's catchment.

    scarcity_eps: optional dict of {name: (needs_predicate, widened_eps_km)}
    -- e.g. {"refrig": (lambda f: f.needs_refrigeration, refrig_eps)}.
    Generalizes what was originally a single hardcoded refrig/non-refrig
    split (Round 4) to an arbitrary number of scarcity dimensions. A
    farmer matching one or more predicates is clustered at the MAX of
    their applicable widened epsilons (not just whichever predicate
    happens to run last), so a farmer who's scarce on two dimensions at
    once still gets the fully-widened radius. Farmers matching none
    keep the tight base eps_km. Defaults to None (i.e. no behavior
    change) so existing callers (Proximity Pooling) are unaffected.

    Processes eps groups in DESCENDING eps order (widest first), not
    whatever order a dict happens to yield -- this matters, not just
    for tidiness: fleet_capacity_cycle() (see run_our_system_v2) is a
    single shared, stateful iterator consumed in cluster-processing
    order, so which group goes first changes which capacity ceilings
    downstream pools actually draw, changing real results. An
    intermediate version of this function iterated a defaultdict's
    natural (first-farmer-encountered) order instead, which depended on
    incidental farmer ordering within each depot cell -- caught by
    diffing benchmark output against the pre-refactor baseline before
    shipping it (n=300/1,000 service% came back ~0.15-0.75pp off with
    no functional change intended). Descending eps order reproduces
    the original hardcoded behavior exactly (refrig group, which was
    always the wider one, was always processed first).
    """
    clusters = []
    for cell in _depot_partition(farmer_list):
        if not scarcity_eps:
            clusters.extend(_dbscan_clusters(cell, eps_km=eps_km))
            continue
        eps_groups = defaultdict(list)
        for f in cell:
            applicable = [widened for (needs_pred, widened) in scarcity_eps.values() if needs_pred(f)]
            eps_groups[max(applicable) if applicable else eps_km].append(f)
        for eff_eps in sorted(eps_groups, reverse=True):  # widest eps first -- see docstring
            clusters.extend(_dbscan_clusters(eps_groups[eff_eps], eps_km=eff_eps))
    return clusters


REFRIG_EPS_MAX_MULT = 3.0  # cap how much scarcity can widen the clustering radius


def _scarcity_eps_km(farmers, fleet, needs_predicate, capable_predicate,
                      eps_km=EPS_KM, max_mult=REFRIG_EPS_MAX_MULT):
    """General form of the scarcity-aware eps-widening logic. Originally
    written as _refrig_eps_km() below with refrigeration hardcoded
    throughout; pulled out into this predicate-driven version so the
    same scarcity math (traced and verified against the MILP ground
    truth for refrigeration -- see _refrig_eps_km()'s docstring) can be
    reused for OTHER vehicle-type scarcity dimensions without copying
    it. needs_predicate(farmer) -> bool selects the farmers who
    specifically require this vehicle subtype; capable_predicate(vehicle)
    -> bool selects the fleet subset that can serve them.

    Two distinct scarcity pressures, not one: how much needing DEMAND
    exists relative to total capable CAPACITY (capacity_scarcity), and
    how few capable VEHICLES exist at all (vehicle_scarcity) -- the
    latter matters independently because each extra trip pays a full
    fixed cost again regardless of how full it is. Verified this
    distinction is necessary, not just tidier, on the refrigeration
    case this was first traced against: with quantity/capacity alone,
    the traced MILP instance (see _refrig_eps_km()'s docstring) only
    reached 82% of the MILP optimum (still splitting out one farmer
    33km away) because total refrigeration-needing demand there was
    comfortably under one truck's capacity, which under-weighted how
    badly a SECOND avoidable trip hurts when only one capable vehicle
    exists at all. Taking the max of both signals closes it to the
    vehicle-count-driven cap.
    """
    needing = [f for f in farmers if needs_predicate(f)]
    if not needing:
        return eps_km
    capable_vehicles = [v for v in fleet if capable_predicate(v)]
    if not capable_vehicles:
        return eps_km * max_mult  # no capable vehicles at all -- moot either way, widen maximally
    needing_qty = sum(f.qty_kg for f in needing)
    capable_cap = sum(v.capacity_kg for v in capable_vehicles)
    vehicle_scarcity = 1.0 / len(capable_vehicles)   # 1.0 when only one capable vehicle exists
    capacity_scarcity = needing_qty / capable_cap
    mult = min(max_mult, 1.0 + max(vehicle_scarcity, capacity_scarcity) * (max_mult - 1.0))
    return eps_km * mult


def _refrig_eps_km(farmers, fleet, eps_km=EPS_KM, max_mult=REFRIG_EPS_MAX_MULT):
    """Refrigerated vehicles are a minority of the fleet by design
    (~32% of default_fleet_composition's weighting). When a farmer
    population's refrigeration-needing demand is large relative to the
    fleet's total refrigerated capacity, a fixed geographic radius can
    block pooling decisions that are economically obvious once you
    account for how expensive it is to dispatch a SEPARATE refrigerated
    trip for each small, eps-isolated cluster.

    This was not a guess: traced directly on a MILP-vs-ILO gap
    (MILP_GROUND_TRUTH.md, "A concrete, traced cause of ILO's worst
    gap") -- 4 of 6 farmers needing refrigeration against a fleet with
    exactly 1 refrigerated truck made a 33km-spanning consolidated trip
    the true optimum, but ILO's fixed 12km eps could never consider it:
    no two of those farmers were within eps_km of each other even via a
    chain.

    Widens the clustering radius ONLY for refrigeration-needing farmers
    (the general population keeps the tight eps that fixed the
    sprawling-route regression at scale -- ALGORITHM_AND_RESULTS_V2.md
    ss7 bug 4 -- stays intact for everyone else), scaled by how scarce
    refrigerated capacity actually is and capped at max_mult so it can't
    grow unbounded.

    Only applied to ILO (run_our_system_v2), not to the naive Proximity
    Pooling baseline -- this is a genuine piece of problem-aware
    intelligence, not a bookkeeping fix, and Proximity Pooling is
    deliberately kept geography-only for comparability with the
    original baseline definition.
    """
    return _scarcity_eps_km(farmers, fleet,
                             needs_predicate=lambda f: f.needs_refrigeration,
                             capable_predicate=lambda v: v.refrigerated,
                             eps_km=eps_km, max_mult=max_mult)


# A "capacity scarcity" dimension (generalizing the refrigeration fix
# above to vehicles above the fleet's smallest tier) was tried in this
# round and reverted -- see ALGORITHM_AND_RESULTS_V2.md s13 for the
# full writeup. Short version: the one farmer-level attribute available
# (qty_kg exceeding the smallest vehicle's capacity) does not identify
# a genuinely SCARCE vehicle subset the way needs_refrigeration does --
# in this fleet mini_pickup is only ~10-11% of vehicles, so "capacity
# above baseline" selects ~89% of the fleet as "capable," the opposite
# of scarce. Widening eps for that farmer subset only sprawled their
# pools with no matching benefit, and measurably hurt results (net
# return down 5-12% at several scales, tested before shipping). Kept
# _scarcity_eps_km() above as a reusable, predicate-driven helper for
# if a genuine second scarcity dimension shows up later; did not keep
# a second, harmful application of it in this round.


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
def assign_fleet(pool_descs, fleet, order_key=None):
    """pool_descs: list of dicts with 'total_qty', 'needs_refrigeration',
    'ready_hr', 'deadline_hr', 'route_duration' (pickup-leg duration,
    i.e. this pool's originally-simulated t_end minus DISPATCH_OVERHEAD_HR
    -- travel + stop time, independent of what hour the vehicle actually
    starts). Mutates each vehicle's available_at_hr. Returns a list of
    (Vehicle | None, actual_completion_hr | None), aligned to pool_descs.

    Processed in ready_hr order (chronological dispatch), best-fit
    (smallest vehicle that both fits and can still make the deadline),
    with a preference for refrigerated trucks when the pool needs it.
    Which pool "claims" a scarce vehicle when several compete is
    whichever is processed first -- an arbitrary order artifact (see
    _bin_pack_fleet_aware()'s docstring for the same kind of artifact
    elsewhere).

    A round-based joint replacement (batching every still-unassigned
    pool and the whole fleet into one Hungarian-algorithm matching per
    round, repeated until nothing more can be assigned) was tried in
    Round 5 and reverted -- see _assign_fleet_joint_attempt() below and
    ALGORITHM_AND_RESULTS_V2.md s14 for why. Short version: batching
    into synchronized rounds caps each round's assignments at one per
    vehicle, which throws away the fine-grained, per-vehicle timing
    that lets THIS version reuse a vehicle the instant it individually
    frees up. That granularity turned out to matter far more than the
    order-artifact it was meant to fix -- a severe, consistent
    regression across every scale tested (up to -27pp service% at
    n=50), not a subtle tradeoff. This greedy version remains the
    shipped implementation for all three algorithms.

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
    # Default: chronological dispatch (ready_hr). `order_key` lets ILO try other claim orders on
    # scarce vehicles; the two baselines never pass it, so their behaviour is unchanged.
    # ILO v3 fleet-aware set partitioning may pin a pool to a specific vehicle and start hour
    # ("hint_vehicle_id" / "hint_start"). Hinted pools are placed first, in start order; a hint that
    # cannot be honoured (capacity, deadline, vehicle busy) silently falls through to the greedy rule below.
    # Pools without hints (all baselines, ILO v2) behave exactly as before.
    by_vid = {v.id: v for v in fleet}
    hinted = sorted((i for i in range(n) if pool_descs[i].get("hint_vehicle_id") is not None),
                    key=lambda i: pool_descs[i]["hint_start"])
    for i in hinted:
        p = pool_descs[i]
        v = by_vid.get(p["hint_vehicle_id"])
        if v is None or v.capacity_kg < p["total_qty"] or p["ready_hr"] > WORKDAY_END_HR:
            continue
        dispatch_start = max(v.available_at_hr, p["ready_hr"], p["hint_start"])
        completion = dispatch_start + p["route_duration"]
        if dispatch_start > WORKDAY_END_HR or completion > p["deadline_hr"]:
            continue
        v.available_at_hr = completion + TURNAROUND_HR
        assigned[i] = v
        completions[i] = completion
    order = sorted(range(n), key=order_key or (lambda i: pool_descs[i]["ready_hr"]))
    for i in order:
        if assigned[i] is not None:
            continue
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


ASSIGN_FLEET_REFRIG_PENALTY = 1.0e5   # cost added for a feasible-but-non-reefer match on a refrig-needing pool
ASSIGN_FLEET_INFEASIBLE_COST = 1.0e9  # >> any real capacity_kg + penalty; marks "no edge" in the cost matrix


def _assign_fleet_joint_attempt(pool_descs, fleet):
    """NOT USED -- kept only as a documented, verified-worse alternative
    (ALGORITHM_AND_RESULTS_V2.md s14), the same way _refrig_eps_km's
    reverted capacity dimension is documented rather than silently
    deleted. Do not wire this in without re-reading s14 first.

    Round-based joint assignment: each ROUND solves one exact bipartite
    min-cost matching (scipy.optimize.linear_sum_assignment) across
    every still-unassigned pool and the WHOLE fleet at once, instead of
    deciding pool-by-pool in ready_hr order. The idea was to remove the
    order-artifact assign_fleet() above still has. It does remove it --
    but at a steep cost documented in s14: each round can match AT MOST
    one pool per vehicle (Hungarian gives a one-to-one matching), so
    with far more pools than vehicles (typical here), only n_v pools
    clear per round; instrumented directly on a real run (n=1,000,
    26 vehicles, 307 pools needing assignment): round assignment counts
    were 26, 26, 25, 16, 3, 1, then stuck, leaving 210 of 307 pools
    (68%) unassigned even though the greedy version served most of them.
    Rounds synchronize every vehicle's clock together, discarding the
    fine-grained fact that different vehicles individually free up at
    different real times -- exactly the granularity multi-trip reuse
    depends on when trips and the workday are both short relative to
    fleet size. A real fix would need genuine time-expanded modeling
    (each vehicle offering discrete availability slots through the
    day), not a per-round batch match; that's a materially bigger
    undertaking than what was scoped here.
    """
    n = len(pool_descs)
    assigned = [None] * n
    completions = [None] * n
    n_v = len(fleet)
    remaining = [i for i in range(n) if pool_descs[i]["ready_hr"] <= WORKDAY_END_HR]
    if not remaining or n_v == 0:
        return assigned, completions
    max_rounds = n + n_v + 5
    for _ in range(max_rounds):
        if not remaining:
            break
        n_p = len(remaining)
        cost = np.full((n_p, n_v), ASSIGN_FLEET_INFEASIBLE_COST)
        completion_of = {}
        any_feasible = False
        for pi, i in enumerate(remaining):
            p = pool_descs[i]
            for vi, v in enumerate(fleet):
                if v.capacity_kg < p["total_qty"]:
                    continue
                dispatch_start = max(v.available_at_hr, p["ready_hr"])
                if dispatch_start > WORKDAY_END_HR:
                    continue
                completion = dispatch_start + p["route_duration"]
                if completion > p["deadline_hr"]:
                    continue
                c = v.capacity_kg
                if p["needs_refrigeration"] and not v.refrigerated:
                    c += ASSIGN_FLEET_REFRIG_PENALTY
                cost[pi, vi] = c
                completion_of[(pi, vi)] = completion
                any_feasible = True
        if not any_feasible:
            break
        row_ind, col_ind = linear_sum_assignment(cost)
        newly_assigned = set()
        for pi, vi in zip(row_ind, col_ind):
            if cost[pi, vi] >= ASSIGN_FLEET_INFEASIBLE_COST:
                continue  # forced pairing (rectangular matching), not a real match
            i = remaining[pi]
            v = fleet[vi]
            completion = completion_of[(pi, vi)]
            v.available_at_hr = completion + TURNAROUND_HR
            assigned[i] = v
            completions[i] = completion
            newly_assigned.add(i)
        if not newly_assigned:
            break
        remaining = [i for i in remaining if i not in newly_assigned]
    return assigned, completions



# ----------------------------------------------------------------------
# B) Global LP market allocation (one crop at a time)
# ----------------------------------------------------------------------
def allocate_markets_lp(pool_infos, crop, markets, elastic_pricing=False, tranches=3, top_k=6,
                        return_leg=False):
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
    result = [{"revenue": 0.0, "spoil_loss_kg": 0.0, "market_dist": {}, "unsold_kg": p["total_qty"], "edges": []}
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
            # return_leg=True also prices the empty leg back from the market to the pool's first stop
            back = (haversine(p["first_point"][0], p["first_point"][1], m.lat, m.lng)
                    if (return_leg and p.get("first_point")) else 0.0)
            transport_per_kg = (p["vehicle"].per_km_cost * (dist + back)) / max(p["total_qty"], 1)
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
        r["edges"].append({"market_id": m_id, "price": node["price"], "kg": take, "dist_km": dist})
        if m_id not in r["market_dist"]:
            r["market_dist"][m_id] = dist  # same physical stop even if multiple tranches
    for r in result:
        r["unsold_kg"] = max(0.0, r["unsold_kg"])
    return result


# ----------------------------------------------------------------------
# Shared: turn a finished pool (possibly multiple crops, one per
# allocation entry) into the standard result dict.
# ----------------------------------------------------------------------
def _finalize(pool, vehicle, order, route_dist, allocs, markets_by_id=None, charge_return_leg=False):
    # farmer_ids is reported in `order` (the routed visiting sequence from
    # order_route()), not `pool` (the unordered grouping) -- `order` was
    # already threaded through as a parameter but unused, so the API was
    # reporting which farmers are in a trip without the sequence a route
    # was actually computed for. total_qty/per_farmer are order-independent
    # sums, so they're unaffected either way.
    total_qty = sum(f.qty_kg for f in pool)
    revenue = sum(a["revenue"] for a in allocs)
    spoil_loss_kg = sum(a["spoil_loss_kg"] for a in allocs)
    unsold_kg = sum(a["unsold_kg"] for a in allocs)
    market_dist = {}
    for a in allocs:
        market_dist.update(a["market_dist"])  # same distance regardless of which crop reached it
    market_legs_km = sum(market_dist.values())
    if charge_return_leg and market_dist and markets_by_id:
        # empty leg home: from the farthest market visited back to the pool's first stop
        far = markets_by_id[max(market_dist, key=market_dist.get)]
        market_legs_km += haversine(far.lat, far.lng, order[0].lat, order[0].lng)
    transport_cost = vehicle.fixed_cost + vehicle.per_km_cost * (route_dist + market_legs_km)
    net_return = revenue - transport_cost
    per_farmer = {f.id: (f.qty_kg / total_qty) * net_return for f in pool} if total_qty else {}
    return {
        "farmer_ids": [f.id for f in order], "vehicle_id": vehicle.id,
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


def _withheld_result(pool):
    """A pool the planner deliberately did NOT dispatch because running it would lose
    money (true net return < 0) or because its vehicle-time earns more elsewhere.
    Distinct from _no_vehicle_result(): there the pool WANTED a truck and none was free;
    here a truck was available but the trip is not worth taking. No cost is incurred
    and the produce is not shipped, so it is reported separately (withheld_uneconomic_kg)
    rather than as 'unsold at market' or 'never got a truck'."""
    q = sum(f.qty_kg for f in pool)
    return {
        "farmer_ids": [f.id for f in pool], "vehicle_id": None, "markets_used": [],
        "total_qty_kg": q, "revenue": 0.0, "transport_cost": 0.0, "spoilage_loss_kg": 0.0,
        "unsold_kg": 0.0, "unserved_no_vehicle_kg": 0.0, "withheld_uneconomic_kg": q,
        "net_return": 0.0, "per_farmer_net": {f.id: 0.0 for f in pool},
        "infeasible": False, "withheld": True,
    }


# ----------------------------------------------------------------------
# Live sensor-override hook
# ----------------------------------------------------------------------
# Design decision (flagged as open in the brief): run_our_system_v2()'s
# per-crop `allocs` -- each with its own market split, price, and kg --
# get summed into the flat pool_result by _finalize() and are otherwise
# lost. Since pools are mixed-crop, overriding one pool's spoilage from a
# single sensor reading needs each crop's own allocation, not just the
# pool total. Chose option (a) from the brief: run_our_system_v2() can
# optionally return a `trace` dict (one PoolTrace per dispatched pool)
# alongside the normal results list, with exactly what's needed to
# recompute later -- rather than trying to reverse-engineer a pool's crop
# composition from the flat result after the fact (option (b)), which
# would need farmer crop lookups threaded back in anyway and gains
# nothing over just keeping the breakdown that already existed mid-call.
@dataclass
class PoolTrace:
    pool_id: int                  # index into the results list from the same call
    farmers: list                 # Farmer objects in this pool (id, qty_kg)
    vehicle: object                # the assigned Vehicle (refrigerated, cost fields)
    transport_cost: float          # fixed once dispatched -- carried over unchanged
    unsold_kg: float                # LP-driven shortfall -- also unchanged by a sensor reading
    crop_allocations: dict = field(default_factory=dict)  # crop -> [{"market_id","price","kg","dist_km"}]


def apply_sensor_reading(trace, pool_id, observed_temp_c, elapsed_hours):
    """Recompute ONE dispatched pool's spoilage-driven numbers
    (spoilage_loss_kg, revenue, net_return, per_farmer_net) from a live
    transit temperature + elapsed hours, e.g. from an ESP32+DHT22 riding
    with the batch. Does NOT re-run pooling, routing, vehicle assignment,
    or market allocation -- those are locked in once the truck has
    departed. `markets_used`, `unsold_kg`, `unserved_no_vehicle_kg`, and
    `transport_cost` are therefore carried over unchanged; only the
    spoilage-driven figures move.

    trace: the second return value of
           run_our_system_v2(..., return_trace=True).
    pool_id: index into the results list from that SAME call (i.e.
             results[pool_id] is the modeled pool_result this overrides).

    Returns a dict in the same shape as a pool_result, plus three extra
    informational keys (sensor_override, observed_temp_c,
    observed_elapsed_hr) so callers can tell a live-overridden result
    apart from a modeled one.

    Can be called again as new readings arrive over the same trip --
    each call is a fresh recompute from the cached allocation, not an
    incremental update, so passing a later (temp, elapsed_hours) pair
    just supersedes the previous override.
    """
    if pool_id not in trace:
        raise KeyError(
            f"No trace for pool_id={pool_id}. Either return_trace=True wasn't "
            f"passed to run_our_system_v2(), or this pool never got a vehicle "
            f"(infeasible pools have no allocation to override)."
        )
    pt = trace[pool_id]
    revenue, spoil_loss_kg = 0.0, 0.0
    markets_used = set()
    for crop, edges in pt.crop_allocations.items():
        spoil = spoilage_fraction_from_temp(crop, observed_temp_c, elapsed_hours)
        for e in edges:
            revenue += e["kg"] * e["price"] * (1 - spoil)
            spoil_loss_kg += e["kg"] * spoil
            markets_used.add(e["market_id"])
    net_return = revenue - pt.transport_cost
    total_qty = sum(f.qty_kg for f in pt.farmers)
    per_farmer = {f.id: (f.qty_kg / total_qty) * net_return for f in pt.farmers} if total_qty else {}
    return {
        "farmer_ids": [f.id for f in pt.farmers], "vehicle_id": pt.vehicle.id,
        "markets_used": sorted(markets_used), "total_qty_kg": total_qty,
        "revenue": revenue, "transport_cost": pt.transport_cost,
        "spoilage_loss_kg": spoil_loss_kg, "unsold_kg": pt.unsold_kg,
        "unserved_no_vehicle_kg": 0.0, "net_return": net_return, "per_farmer_net": per_farmer,
        "infeasible": False,
        "sensor_override": True, "observed_temp_c": observed_temp_c, "observed_elapsed_hr": elapsed_hours,
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
# --- economic dispatch control (see ALGORITHM_AND_RESULTS_V2.md s17) -------------------------
DISPATCH_MIN_NET = 0.0          # a trip must at least break even to run
MAX_WITHHOLD_PASSES = 30        # re-plan passes after withholding loss-making trips (exits early at a fixed point)
LOCAL_SEARCH_MAX_EVALS = 30     # full re-plans the bounded local search may spend
LOCAL_SEARCH_MAX_POOLS = 120    # skip the local search above this many pools (runtime guard)
_NET_EPS = 1e-6
MULTISTART_MAX_POOLS = 300      # above this many pools only the chronological order is tried (runtime guard)
# Orders in which pools claim scarce vehicles. No single order wins everywhere (measured), so ILO
# runs the same economic search under each and keeps the best plan; "ready" is the original order,
# so the result can never be worse than the single-order plan.
CLAIM_ORDERS = ("ready", "qty", "deadline", "slack")
# Extra DETERMINISTIC random claim orders (seeded by index, so a plan is reproducible). Measured on
# 18 real-data + synthetic scenarios: 24 extra orders gave +0.21% mean (max +2.55%) net return and
# never a worse plan (the best plan found is kept). 8 keeps most of that at a fraction of the runtime;
# skipped above RANDOM_ORDERS_MAX_POOLS pools so large instances keep their runtime guard.
N_RANDOM_ORDERS = 8
RANDOM_ORDERS_MAX_POOLS = 60


def _order_key_for(mode, descs):
    if isinstance(mode, tuple) and mode[0] == "rand":      # ("rand", k): a fixed pseudo-random claim order
        ranks = list(range(len(descs)))
        random.Random(mode[1]).shuffle(ranks)
        return lambda i: ranks[i]
    if mode == "ready":
        return None                                   # assign_fleet default: chronological
    if mode == "slack":     # tightest window first
        return lambda i: descs[i]["deadline_hr"] - descs[i]["ready_hr"] - descs[i]["route_duration"]
    if mode == "qty":       # biggest load first
        return lambda i: -descs[i]["total_qty"]
    if mode == "deadline":  # earliest deadline first
        return lambda i: (descs[i]["deadline_hr"], descs[i]["ready_hr"])
    raise ValueError(mode)


def _timeline_from(order, start):
    """Pickup time of each stop (and the time the loaded vehicle leaves the last one) for a trip
    dispatched at `start`."""
    t = start + DISPATCH_OVERHEAD_HR
    pickups = []
    for i, f in enumerate(order):
        if i > 0:
            t += haversine(order[i - 1].lat, order[i - 1].lng, f.lat, f.lng) / AVG_SPEED_KMPH
        t = max(t, f.ready_hr)
        pickups.append(t)
        t += STOP_OVERHEAD_HR
    return pickups, t


def _route_duration(order, t_end, fix):
    """Pickup-leg duration used by assign_fleet. Legacy: t_end - overhead, where t_end is simulated from
    clock 0 and so includes waiting for ready times that have already passed by dispatch time (overstates
    duration, shrinking vehicle reuse). fix=True simulates from the pool's earliest ready time instead."""
    if not fix:
        return t_end - DISPATCH_OVERHEAD_HR
    d0 = min(f.ready_hr for f in order)
    _, t_leave = _timeline_from(order, d0)
    return t_leave - d0 - DISPATCH_OVERHEAD_HR


def _t_after_pickup(comp, duration, order, flist, from_pickup):
    """Hours of transit already accumulated when the loaded vehicle leaves the last stop. Legacy: the absolute
    clock `comp` (produce 'spoils' from hour 0). from_pickup=True: hours since the crop's (quantity-weighted)
    pickup instead."""
    if not from_pickup:
        return comp
    pk, _ = _timeline_from(order, comp - duration)
    pk_of = {f.id: t for f, t in zip(order, pk)}
    q = sum(f.qty_kg for f in flist)
    return max(0.0, comp - sum(f.qty_kg * pk_of[f.id] for f in flist) / q)


def run_our_system_v2(farmers, fleet, markets, elastic_pricing=False, top_k=6, return_trace=False,
                      withhold_uneconomic=True, farmgate_value_fn=None, dispatch_margin=0.0,
                      fix_route_duration=False, spoilage_from_pickup=False, charge_return_leg=False,
                      raw_pools_override=None, pool_hints=None):
    """withhold_uneconomic=False reproduces the previous behaviour exactly (every pool that
    can get a vehicle is dispatched, even at a loss). True (default) adds economic dispatch:
    the plan is re-computed with loss-making trips withheld, so their vehicle-time and market
    capacity go to trips that earn money, and the best plan found is kept. The returned plan's
    total net return is never lower than the withhold_uneconomic=False plan's.
    Optional v3 arguments (all default to the exact previous behaviour):
      farmgate_value_fn(pool)->Rs: the pool's opportunity cost, i.e. what its farmers get if NOT hauled.
        When given, the objective counts that value for every pool that is not dispatched, and a trip is
        dispatched only if it beats DISPATCH_MIN_NET + farmgate value * (1 + dispatch_margin).
      fix_route_duration / spoilage_from_pickup / charge_return_leg: see _route_duration, _t_after_pickup
        and _finalize.
      raw_pools_override: use these pools (lists of Farmer) instead of the geographic clustering.
      pool_hints: {frozenset(farmer ids): {"vehicle_id", "start"}} -- pin those pools to a vehicle / start hour
        (ILO v3 fleet-aware set partitioning). Unhonourable hints fall back to the greedy assignment."""
    capacity_slots = fleet_capacity_cycle(fleet)
    raw_pools = []
    if raw_pools_override is not None:
        raw_pools = [list(p) for p in raw_pools_override if p]
    else:
        refrig_eps = _refrig_eps_km(farmers, fleet)
        scarcity_eps = {"refrig": (lambda f: f.needs_refrigeration, refrig_eps)}
        for gc in _geo_clusters(farmers, scarcity_eps=scarcity_eps):  # crop-blind clustering
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
        "route_duration": _route_duration(order, t_end, fix_route_duration),
        **({"hint_vehicle_id": pool_hints[frozenset(f.id for f in pool)]["vehicle_id"],
            "hint_start": pool_hints[frozenset(f.id for f in pool)]["start"]}
           if pool_hints and frozenset(f.id for f in pool) in pool_hints else {}),
    } for pool, order, route_dist, t_end in routed]
    markets_by_id = {m.id: m for m in markets}
    pool_fg = [farmgate_value_fn(pool) for pool, _o, _d, _t in routed] if farmgate_value_fn else None

    def hurdle(i):
        """Net return a dispatched pool must reach to be worth running."""
        return DISPATCH_MIN_NET + (pool_fg[i] * (1.0 + dispatch_margin) if pool_fg else 0.0)

    base_avail = [v.available_at_hr for v in fleet]

    def plan(active, order_mode="ready"):
        """One full plan (vehicle assignment -> per-crop market LP -> finalize) over the pools
        in `active` (indices into `routed`); every other pool is reported as withheld.
        Returns (results_by_pool_idx, total_net, allocs_by_pool_idx, vehicle_by_pool_idx,
        fleet_availability_after)."""
        for v, a in zip(fleet, base_avail):          # every plan starts from the same fleet state
            v.available_at_hr = a
        sub = [pool_descs[i] for i in active]
        vehicles, completions = assign_fleet(sub, fleet, order_key=_order_key_for(order_mode, sub))
        avail_after = [v.available_at_hr for v in fleet]   # fleet state this plan leaves behind
        veh_of = dict(zip(active, vehicles))
        comp_of = dict(zip(active, completions))

        results = {}
        by_crop_lp = defaultdict(list)         # crop -> list of (pool_idx, pool_info)
        for i in active:
            pool, order, route_dist, t_end = routed[i]
            vehicle = veh_of[i]
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
                    "t_after_pickup": _t_after_pickup(comp_of[i], pool_descs[i]["route_duration"], order,
                                                      flist, spoilage_from_pickup),
                    "first_point": (order[0].lat, order[0].lng), "vehicle": vehicle,
                }))

        pool_alloc_lists = defaultdict(list)   # pool_idx -> list of per-crop alloc dicts (tagged with "crop")
        for crop, entries in by_crop_lp.items():
            infos = [e[1] for e in entries]
            allocs = allocate_markets_lp(infos, crop, markets, elastic_pricing=elastic_pricing, top_k=top_k,
                                         return_leg=charge_return_leg)
            for (i, info), alloc in zip(entries, allocs):
                alloc["crop"] = crop
                pool_alloc_lists[i].append(alloc)

        active_set = set(active)
        for i, (pool, order, route_dist, t_end) in enumerate(routed):
            if i not in active_set:
                results[i] = _withheld_result(pool)
            elif i not in results:
                results[i] = _finalize(pool, veh_of[i], order, route_dist, pool_alloc_lists[i],
                                       markets_by_id, charge_return_leg)
                results[i]["dispatch_hr"] = comp_of[i] - pool_descs[i]["route_duration"]   # planned start hour
        total_net = sum(r["net_return"] for r in results.values())
        if pool_fg:     # undispatched pools' farmers sell at the farm gate: that value is part of the objective
            total_net += sum(pool_fg[i] for i, r in results.items() if r["vehicle_id"] is None)
        return results, total_net, pool_alloc_lists, veh_of, avail_after

    n_pools = len(routed)

    def search(order_mode):
        """Economic dispatch under one claim order. Returns the best plan found:
        (active, results, net, allocs, veh_of, avail_after)."""
        active = list(range(n_pools))
        best = (active,) + plan(active, order_mode)
        if not (withhold_uneconomic and n_pools):
            return best
        # Phase 1 -- withhold every trip that loses money, re-plan (a freed vehicle / freed market
        # capacity can turn another pool profitable or newly servable), repeat to a fixed point.
        cur_active, cur_results = active, best[1]
        for _ in range(MAX_WITHHOLD_PASSES):
            losers = {i for i in cur_active
                      if cur_results[i]["vehicle_id"] is not None and cur_results[i]["net_return"] < hurdle(i)}
            if not losers:
                break
            cur_active = [i for i in cur_active if i not in losers]
            cand = plan(cur_active, order_mode)
            cur_results = cand[0]
            if cand[1] > best[2] + _NET_EPS:
                best = (cur_active,) + cand

        # Phase 2 -- bounded local search over which pools run. Moves: withhold one low-earning pool
        # (only when other pools are starved of a vehicle), or re-admit one withheld pool. A move is
        # kept only if total net return strictly improves, so this can never make the plan worse.
        if n_pools <= LOCAL_SEARCH_MAX_POOLS:
            evals = 0
            improved = True
            while improved and evals < LOCAL_SEARCH_MAX_EVALS:
                improved = False
                b_active, b_results, b_net = best[0], best[1], best[2]
                b_set = set(b_active)
                starved = any(b_results[i].get("unserved_no_vehicle_kg", 0.0) > 0 for i in b_active)
                moves = []
                dispatched = sorted((i for i in b_active if b_results[i]["vehicle_id"] is not None),
                                    key=lambda i: b_results[i]["net_return"] - (pool_fg[i] if pool_fg else 0.0))
                if starved:   # frees vehicle-time for starved pools: try dropping the lowest earners first
                    moves += [("drop", i) for i in dispatched]
                else:         # nothing starved: still try dropping a trip that loses money on its own
                    moves += [("drop", i) for i in dispatched if b_results[i]["net_return"] < hurdle(i)]
                moves += [("add", i) for i in sorted(set(range(n_pools)) - b_set,
                                                      key=lambda i: -pool_descs[i]["total_qty"])]
                for kind, i in moves:
                    if evals >= LOCAL_SEARCH_MAX_EVALS:
                        break
                    trial = sorted(b_set - {i}) if kind == "drop" else sorted(b_set | {i})
                    evals += 1
                    cand = plan(trial, order_mode)
                    if cand[1] > b_net + _NET_EPS:
                        best = (trial,) + cand
                        improved = True
                        break          # restart the move list from the improved plan
        return best

    modes = CLAIM_ORDERS if (withhold_uneconomic and n_pools <= MULTISTART_MAX_POOLS) else CLAIM_ORDERS[:1]
    if withhold_uneconomic and n_pools <= RANDOM_ORDERS_MAX_POOLS:
        modes = tuple(modes) + tuple(("rand", k) for k in range(N_RANDOM_ORDERS))
    best = None
    for mode in modes:
        cand = search(mode)
        if best is None or cand[2] > best[2] + _NET_EPS:   # strict: ties keep the earlier (chronological) plan
            best = cand

    active, res_by_idx, total_net, pool_alloc_lists, veh_of, avail_final = best
    for v, a in zip(fleet, avail_final):   # leave the fleet in the state the reported plan implies
        v.available_at_hr = a
    results = [res_by_idx[i] for i in range(n_pools)]

    trace = {}
    if return_trace:
        for i, (pool, order, route_dist, t_end) in enumerate(routed):
            if results[i]["vehicle_id"] is None:
                continue  # no vehicle, or withheld: nothing was dispatched, so nothing to trace
            crop_allocations = defaultdict(list)
            for alloc in pool_alloc_lists[i]:
                crop_allocations[alloc["crop"]].extend(alloc["edges"])
            trace[i] = PoolTrace(
                pool_id=i, farmers=list(pool), vehicle=veh_of[i],
                transport_cost=results[i]["transport_cost"], unsold_kg=results[i]["unsold_kg"],
                crop_allocations=dict(crop_allocations),
            )
        return results, trace
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
            if f.crop not in m.price or f.crop not in remaining_cap[m.id]:
                continue  # this market doesn't buy f.crop -- not a candidate
            dist = haversine(last_point[0], last_point[1], m.lat, m.lng)
            transit_hr = t_after_pickup + dist / AVG_SPEED_KMPH
            spoil = spoilage_fraction(f.crop, vehicle.refrigerated, transit_hr)
            transport_per_kg = (vehicle.per_km_cost * dist) / max(f.qty_kg, 1)
            net_val = m.price[f.crop] * (1 - spoil) - transport_per_kg
            if best is None or net_val > best[0]:
                best = (net_val, m, dist, spoil)
        if best is None:
            # No market in the whole set buys f.crop. The vehicle still made
            # the trip (cost already committed by assign_fleet), it just had
            # nowhere to sell -- mirrors how ILO's LP reports a crop with no
            # feasible demand node (unsold_kg = full qty, revenue = 0).
            transport_cost = vehicle.fixed_cost
            results.append({
                "farmer_ids": [f.id], "vehicle_id": vehicle.id, "markets_used": [],
                "total_qty_kg": f.qty_kg, "revenue": 0.0, "transport_cost": transport_cost,
                "spoilage_loss_kg": 0.0, "unsold_kg": f.qty_kg,
                "unserved_no_vehicle_kg": 0.0, "net_return": -transport_cost,
                "per_farmer_net": {f.id: -transport_cost}, "infeasible": False,
            })
            continue
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
            candidates = [mk for mk in markets if crop in mk.price and crop in remaining_cap[mk.id]]
            if not candidates:
                # No market anywhere buys this crop -- whole sub-lot goes unsold,
                # no market leg to add to the route.
                unsold += qty
                continue
            m = max(candidates, key=lambda mk: mk.price[crop])
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
    total_withheld_kg = sum(r.get("withheld_uneconomic_kg", 0.0) for r in results)   # baselines never withhold
    total_qty = sum(r["total_qty_kg"] for r in results)
    net_return = total_revenue - total_cost
    vehicles_used = len({r["vehicle_id"] for r in results if r["vehicle_id"] is not None})
    per_farmer_net = {}
    for r in results:
        per_farmer_net.update(r["per_farmer_net"])
    return {
        "total_revenue": total_revenue, "total_transport_cost": total_cost,
        "total_spoilage_kg": total_spoil_kg, "total_unsold_kg": total_unsold_kg,
        "total_unserved_no_vehicle_kg": total_unserved_kg, "total_withheld_kg": total_withheld_kg,
        "total_qty_kg": total_qty,
        "net_return": net_return, "net_return_per_farmer": net_return / n_farmers if n_farmers else 0,
        "vehicles_used": vehicles_used,
        "vehicle_utilization_pct": 100 * vehicles_used / fleet_size if fleet_size else 0,
        "pools_formed": len(results),
        "pct_qty_served": 100 * (1 - (total_unsold_kg + total_unserved_kg + total_withheld_kg) / total_qty) if total_qty else 0,
    }


# ----------------------------------------------------------------------
# Naming: "Our System" is now called ILO (Integrated Logistics
# Optimization), per the project's updated terminology. run_our_system_v2
# is kept as the actual function name (renaming it would break the
# CONTRACT.md interface backend/ already integrates against), aliased
# here so new code can call it by its current name. Use "ILO" in prose
# and documentation going forward.
# ----------------------------------------------------------------------
run_ilo_v2 = run_our_system_v2
