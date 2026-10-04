"""
integrated_milp.py
-------------------
Exact mathematical ground truth for the agricultural logistics problem,
built jointly (not sequentially) as ALGORITHM_AGENT_PROMPT/CONTRACT's
MILP task requests. Compared against ILO (formerly "Our System" --
run_our_system_v2 / run_ilo_v2, see the alias in algorithms_v2.py).

READ THIS FIRST: the honest scope of "exact" here.
====================================================
A fully joint MILP over routing + multi-trip scheduling + spoilage-aware,
multi-market-splitting revenue is NOT exactly representable as a linear
MILP -- three separate points in the model are products of two decision
variables (bilinear), and only some of them can be linearized without
approximation:

  1. Vehicle timing (which physical slot a candidate trip lands in,
     hence its actual start time) -- binary x continuous. EXACTLY
     linearizable via a standard big-M "indicator" reformulation. Done
     exactly below, no approximation.
  2. Transport cost attribution (which vehicle's per-km rate applies to
     which distance) -- binary x continuous once market choice is
     itself a decision. Also EXACTLY linearizable via the same big-M
     technique (see `_add_indicator_product`). Done exactly.
  3. Revenue = kg_sold x (1 - spoilage_fraction) where BOTH kg_sold and
     spoilage_fraction (a function of transit time) are decision
     variables. This is genuinely bilinear in general and does NOT have
     an exact linear reformulation without either discretizing one side
     or accepting a relaxation.

For #3, two honest choices existed (documented, not silently picked):
  (a) Allow markets to split a crop's quantity like ILO's LP does, and
      accept a McCormick relaxation -- valid, but only an UPPER BOUND on
      true optimal net return when a candidate's crop is genuinely split
      across markets or partially unsold (provably tight only at the
      corners: fully sold to one market, or fully unsold/fully spoiled).
  (b) Force each candidate's each crop to go entirely to ONE market (or
      go unsold) -- then kg_sold is a KNOWN CONSTANT once the market is
      chosen, so "constant x spoilage_fraction" is linear, not bilinear.
      Fully exact, no relaxation anywhere -- at the cost of not modeling
      ILO's multi-market splitting feature.

**This implementation takes (b).** It ships something that is actually,
provably exact end to end, rather than something that mixes an exact
core with an unquantified relaxation. The cost is explicit: this MILP's
optimum is the true optimum of a SLIGHTLY DIFFERENT problem than ILO
solves (single-market-per-crop-per-trip, not split-allowed) -- so a gap
between ILO and this MILP is a mix of "ILO's heuristic quality" and
"ILO gets to split, this benchmark doesn't." Section "Reading the gap"
in the results doc addresses this directly rather than leaving it
implicit. Extending to (a) as a second, relaxation-bound mode is flagged
as future work, not attempted here -- shipping one fully-exact mode,
tested and verified, was judged better use of the available effort than
two partially-verified modes.

Multi-trip vehicle scheduling uses a SLOT formulation (each vehicle has
K_MAX ordered slots, candidates are assigned into slots) rather than
pairwise trip-ordering binaries -- O(vehicles x K_MAX) precedence
constraints instead of O(candidates^2 x vehicles) disjunctive ones. This
loses no generality (any valid schedule can be relabeled into slot
order) and is dramatically smaller for the solver.

Candidate trips are pre-generated EXACTLY for small instances (exhaustive
subset enumeration up to MAX_SUBSET_SIZE, exact brute-force TSP-with-
time-windows per subset, identical algorithm to ILO's own order_route()
for small pools -- so route/timing decisions inside a candidate are
genuinely optimal, not heuristic). This is the OTHER place this stops
being unconditionally exact: subset enumeration is exhaustive only up to
MAX_SUBSET_SIZE and only considers the MIN-DISTANCE feasible route per
subset (matching ILO's own tie-break, for comparability) rather than
every feasible permutation. Both are scope limits for tractability, both
disclosed here and in the results doc, neither silently assumed.
"""

import itertools
from dataclasses import dataclass, field
from collections import defaultdict

import numpy as np
from scipy.optimize import milp, LinearConstraint, Bounds

from logistics_lib_v2 import haversine, spoilage_fraction, CROPS, AVG_SPEED_KMPH
from algorithms_v2 import DISPATCH_OVERHEAD_HR, STOP_OVERHEAD_HR, TURNAROUND_HR, WORKDAY_END_HR

MAX_SUBSET_SIZE = 5   # exhaustive-enumeration cap -- see module docstring
K_MAX_SLOTS = 3        # max trips per vehicle considered per run


# ----------------------------------------------------------------------
# Candidate trip generation
# ----------------------------------------------------------------------
@dataclass
class Candidate:
    idx: int
    farmer_ids: tuple            # farmer ids in this subset (unordered, for coverage constraints)
    order: list                  # Farmer objects, in the exact optimal visiting order
    route_dist_km: float          # pickup-leg distance for this exact order
    route_duration_hr: float      # baseline (start=0) completion time minus DISPATCH_OVERHEAD_HR
    offsets_hr: dict              # farmer.id -> arrival time at baseline start=0 (for latest_start)
    latest_start_hr: float        # latest dispatch time keeping every farmer's own deadline (exact)
    total_qty_kg: float
    needs_refrigeration: bool
    crop_qty: dict                # crop -> total kg of that crop in this candidate
    last_point: tuple             # (lat, lng) of the final pickup stop


def _feasible_permutation_min_distance(farmers):
    """Exact brute-force search over ALL orderings: among those that
    satisfy every farmer's own [ready_hr, deadline_hr] window (with
    waiting allowed), return the one with minimum total distance --
    identical selection rule to ILO's order_route() for pools <=7, so
    a candidate's internal routing is genuinely optimal, not just
    feasible. Returns None if no ordering is feasible at all."""
    best = None
    for perm in itertools.permutations(farmers):
        t = DISPATCH_OVERHEAD_HR
        offsets = {}
        feasible = True
        for i, f in enumerate(perm):
            if i > 0:
                t += haversine(perm[i-1].lat, perm[i-1].lng, f.lat, f.lng) / AVG_SPEED_KMPH
            t = max(t, f.ready_hr)
            if t > f.deadline_hr:
                feasible = False
                break
            offsets[f.id] = t
            t += STOP_OVERHEAD_HR
        if not feasible:
            continue
        dist = sum(haversine(perm[i].lat, perm[i].lng, perm[i+1].lat, perm[i+1].lng)
                   for i in range(len(perm) - 1))
        if best is None or dist < best[0]:
            best = (dist, list(perm), offsets, t)
    return best  # (dist, order, offsets, completion_at_baseline) or None


def generate_candidates(farmers, fleet, max_subset_size=MAX_SUBSET_SIZE):
    """Exhaustive (for small n): every non-empty farmer subset up to
    max_subset_size that (a) some vehicle in the fleet could physically
    carry (capacity) and (b) some vehicle in the fleet could legally
    carry (refrigeration), with a feasible pickup ordering at all.
    """
    max_cap = max((v.capacity_kg for v in fleet), default=0)
    have_refrigerated = any(v.refrigerated for v in fleet)
    candidates = []
    idx = 0
    n = len(farmers)
    for size in range(1, min(max_subset_size, n) + 1):
        for combo in itertools.combinations(farmers, size):
            qty = sum(f.qty_kg for f in combo)
            if qty > max_cap + 1e-9:
                continue
            needs_refrig = any(f.needs_refrigeration for f in combo)
            if needs_refrig and not have_refrigerated:
                continue
            result = _feasible_permutation_min_distance(combo)
            if result is None:
                continue
            dist, order, offsets, completion0 = result
            route_duration = completion0 - DISPATCH_OVERHEAD_HR
            latest_start = min(f.deadline_hr - offsets[f.id] for f in combo)
            if latest_start < -1e-9:
                continue  # shouldn't happen given the feasibility check above, safety net
            crop_qty = defaultdict(float)
            for f in combo:
                crop_qty[f.crop] += f.qty_kg
            candidates.append(Candidate(
                idx=idx, farmer_ids=tuple(f.id for f in combo), order=order,
                route_dist_km=dist, route_duration_hr=route_duration, offsets_hr=offsets,
                latest_start_hr=max(0.0, latest_start), total_qty_kg=qty,
                needs_refrigeration=needs_refrig, crop_qty=dict(crop_qty),
                last_point=(order[-1].lat, order[-1].lng),
            ))
            idx += 1
    return candidates


# ----------------------------------------------------------------------
# Variable registry -- scipy.optimize.milp wants one flat vector. This
# keeps every named variable family's slice trackable instead of manual
# index arithmetic scattered through the constraint-building code below.
# ----------------------------------------------------------------------
class VarRegistry:
    def __init__(self):
        self._names = {}      # name -> flat index
        self._is_binary = []  # parallel array: True/False per index
        self._lb = []
        self._ub = []
        self.n = 0

    def add(self, name, binary, lb=0.0, ub=None):
        if name in self._names:
            raise ValueError(f"duplicate variable {name}")
        i = self.n
        self._names[name] = i
        self._is_binary.append(binary)
        self._lb.append(0.0 if binary else lb)
        self._ub.append(1.0 if binary else (ub if ub is not None else np.inf))
        self.n += 1
        return i

    def idx(self, name):
        return self._names[name]

    def bounds(self):
        return Bounds(np.array(self._lb), np.array(self._ub))

    def integrality(self):
        return np.array([1 if b else 0 for b in self._is_binary])


# ----------------------------------------------------------------------
# MILP assembly and solve
# ----------------------------------------------------------------------
BIGM_TIME = WORKDAY_END_HR + 30.0   # generous vs. any realistic route/turnaround chain at this scale


def build_and_solve_milp(farmers, fleet, markets, service_target=None,
                          k_max_slots=K_MAX_SLOTS, max_subset_size=MAX_SUBSET_SIZE,
                          time_limit=120, verbose=False):
    """Builds and solves the exact (see module docstring for the precise,
    disclosed sense of "exact") integrated MILP. Returns a dict with
    solver status/objective/gap plus pool_result-shaped output for every
    activated candidate, so it slots into the same summarize() used for
    ILO and the two baselines.
    """
    candidates = generate_candidates(farmers, fleet, max_subset_size=max_subset_size)
    n_c = len(candidates)
    if verbose:
        print(f"{n_c} candidate trips generated")

    fleet_list = list(fleet)
    n_v = len(fleet_list)
    slots = list(range(k_max_slots))

    # compatible (c, v) pairs: capacity + hard refrigeration requirement
    compat = {}
    for c in candidates:
        compat[c.idx] = [v for v in fleet_list
                          if v.capacity_kg + 1e-9 >= c.total_qty_kg
                          and (not c.needs_refrigeration or v.refrigerated)]

    reg = VarRegistry()

    # a[c]
    for c in candidates:
        reg.add(f"a_{c.idx}", binary=True)

    # assign_slot[c,v,k] -- only for compatible (c,v)
    assign_keys = []  # (c.idx, v.id, k)
    for c in candidates:
        for v in compat[c.idx]:
            for k in slots:
                reg.add(f"asg_{c.idx}_{v.id}_{k}", binary=True)
                assign_keys.append((c.idx, v.id, k))

    # start[v,k] / completion[v,k]
    for v in fleet_list:
        for k in slots:
            reg.add(f"st_{v.id}_{k}", binary=False, lb=0.0, ub=WORKDAY_END_HR)
            reg.add(f"cp_{v.id}_{k}", binary=False, lb=0.0, ub=BIGM_TIME)

    # start_of[c]
    for c in candidates:
        reg.add(f"sof_{c.idx}", binary=False, lb=0.0, ub=WORKDAY_END_HR)

    # transport-cost aux[c,v,k] = assign_slot[c,v,k] * total_dist[c]
    dist_ub = {}
    for c in candidates:
        crops = list(c.crop_qty.keys())
        dist_ub[c.idx] = c.route_dist_km + sum(
            max(haversine(c.last_point[0], c.last_point[1], m.lat, m.lng) for m in markets)
            for _ in crops
        ) if markets else c.route_dist_km
        for v in compat[c.idx]:
            for k in slots:
                reg.add(f"aux_{c.idx}_{v.id}_{k}", binary=False, lb=0.0, ub=dist_ub[c.idx])

    # y[c,crop,m] -- every market, no top_k pruning (per the brief)
    ym_keys = []  # (c.idx, crop, m.id)
    for c in candidates:
        for crop in c.crop_qty:
            for m in markets:
                reg.add(f"y_{c.idx}_{crop}_{m.id}", binary=True)
                ym_keys.append((c.idx, crop, m.id))

    # z[c,m] = OR over crop of y[c,crop,m] -- "does candidate c visit
    # market m at all" (deduplicates the market-leg distance when
    # several crops in the same mixed-crop trip go to the same market;
    # a truck drops off 3 crops at one market with ONE visit, not three
    # -- verified against a real solve where summing dist*y directly
    # over (crop,market) triple-counted a shared market leg). Continuous
    # in [0,1]: forced to exactly the OR at any optimum since it only
    # ever appears with a positive cost coefficient (the solver wants
    # it at its lower bound, and z >= y_i pins that lower bound to
    # exactly max(y_i)).
    zc_keys = []
    for c in candidates:
        for m in markets:
            reg.add(f"z_{c.idx}_{m.id}", binary=False, lb=0.0, ub=1.0)
            zc_keys.append((c.idx, m.id))

    # spoil[c,crop,m] in [0,0.6], plus cap_active binary only where the
    # 0.6 cap could plausibly bind (worst-case transit check) -- keeps
    # the disjunctive machinery only where it's actually needed.
    cap_active_keys = set()
    for (cidx, crop, mid) in ym_keys:
        c = candidates[cidx]
        m = next(mm for mm in markets if mm.id == mid)
        dist = haversine(c.last_point[0], c.last_point[1], m.lat, m.lng)
        worst_transit = c.latest_start_hr + c.route_duration_hr + dist / AVG_SPEED_KMPH
        rate = CROPS[crop]["base_spoil_per_hr"]
        reg.add(f"sp_{cidx}_{crop}_{mid}", binary=False, lb=0.0, ub=0.6)
        if rate * worst_transit > 0.6:
            reg.add(f"cap_{cidx}_{crop}_{mid}", binary=True)
            cap_active_keys.add((cidx, crop, mid))

    # rev_term[c,crop,m] >= 0
    for (cidx, crop, mid) in ym_keys:
        c = candidates[cidx]
        m = next(mm for mm in markets if mm.id == mid)
        ev_max = c.crop_qty[crop] * m.price[crop]
        reg.add(f"rev_{cidx}_{crop}_{mid}", binary=False, lb=0.0, ub=max(ev_max, 0.0))

    n_vars = reg.n
    if verbose:
        print(f"{n_vars} MILP variables ({sum(reg._is_binary)} binary)")

    rows, cols, vals, lb_c, ub_c = [], [], [], [], []
    row = [0]

    def add_row(coeffs, lo, hi):
        r = row[0]
        for name, coef in coeffs:
            rows.append(r); cols.append(reg.idx(name)); vals.append(coef)
        lb_c.append(lo); ub_c.append(hi)
        row[0] += 1

    INF = np.inf

    # (1) sum_{v,k} assign_slot[c,v,k] == a[c]
    for c in candidates:
        terms = [(f"asg_{c.idx}_{v.id}_{k}", 1.0) for v in compat[c.idx] for k in slots]
        terms.append((f"a_{c.idx}", -1.0))
        add_row(terms, 0.0, 0.0)

    # (2) sum_c assign_slot[c,v,k] <= 1
    for v in fleet_list:
        for k in slots:
            terms = [(f"asg_{c.idx}_{v.id}_{k}", 1.0) for c in candidates if v in compat[c.idx]]
            if terms:
                add_row(terms, -INF, 1.0)

    # (3) farmer coverage: at most one trip per farmer
    farmer_to_candidates = defaultdict(list)
    for c in candidates:
        for fid in c.farmer_ids:
            farmer_to_candidates[fid].append(c)
    for fid, clist in farmer_to_candidates.items():
        add_row([(f"a_{c.idx}", 1.0) for c in clist], -INF, 1.0)

    # (5) completion[v,k] == start[v,k] + sum_c assign_slot[c,v,k]*route_duration(c)
    for v in fleet_list:
        for k in slots:
            terms = [(f"cp_{v.id}_{k}", 1.0), (f"st_{v.id}_{k}", -1.0)]
            terms += [(f"asg_{c.idx}_{v.id}_{k}", -c.route_duration_hr)
                      for c in candidates if v in compat[c.idx]]
            add_row(terms, 0.0, 0.0)

    # (6) chain: start[v,k] >= completion[v,k-1] + TURNAROUND - BIGM*(1 - used[v,k-1])
    #     and force start[v,k]==0 (hence completion==0) when slot k unused.
    for v in fleet_list:
        for k in slots:
            used_terms = [(f"asg_{c.idx}_{v.id}_{k}", 1.0) for c in candidates if v in compat[c.idx]]
            # start[v,k] <= BIGM * sum(used) -- pins start=0 when slot empty
            terms = [(f"st_{v.id}_{k}", 1.0)] + [(n, -BIGM_TIME) for n, _ in used_terms]
            add_row(terms, -INF, 0.0)
            if k > 0:
                prev_used = [(f"asg_{c.idx}_{v.id}_{k-1}", 1.0) for c in candidates if v in compat[c.idx]]
                # st[v,k] - cp[v,k-1] - BIGM*sum(prev_used) >= TURNAROUND - BIGM
                # (non-binding when slot k-1 is unused; binds exactly when it is)
                terms = [(f"st_{v.id}_{k}", 1.0), (f"cp_{v.id}_{k-1}", -1.0)] + \
                        [(n, -BIGM_TIME) for n, _ in prev_used]
                add_row(terms, TURNAROUND_HR - BIGM_TIME, INF)

    # (7) start_of[c]: big-M link to start[v,k]; deadline bound
    for c in candidates:
        for v in compat[c.idx]:
            for k in slots:
                a_name = f"asg_{c.idx}_{v.id}_{k}"
                # start_of[c] <= start[v,k] + BIGM*(1-assign)
                add_row([(f"sof_{c.idx}", 1.0), (f"st_{v.id}_{k}", -1.0), (a_name, BIGM_TIME)],
                        -INF, BIGM_TIME)
                # start_of[c] >= start[v,k] - BIGM*(1-assign)
                add_row([(f"sof_{c.idx}", 1.0), (f"st_{v.id}_{k}", -1.0), (a_name, -BIGM_TIME)],
                        -BIGM_TIME, INF)
        add_row([(f"sof_{c.idx}", 1.0)], -INF, c.latest_start_hr)

    # z[c,m] >= y[c,crop,m] for every crop in c -- pins z to the OR
    for c in candidates:
        for m in markets:
            for crop in c.crop_qty:
                y_name = f"y_{c.idx}_{crop}_{m.id}"
                if y_name in reg._names:
                    add_row([(f"z_{c.idx}_{m.id}", 1.0), (y_name, -1.0)], 0.0, INF)

    # (8) transport aux[c,v,k] = assign_slot[c,v,k] * total_dist_expr[c]
    #     total_dist_expr uses z[c,m] (deduplicated per-market), not a
    #     raw sum over (crop,market) y's -- see z[c,m] comment above.
    for c in candidates:
        z_terms_dist = [(f"z_{c.idx}_{m.id}",
                          haversine(c.last_point[0], c.last_point[1], m.lat, m.lng))
                         for m in markets]
        for v in compat[c.idx]:
            for k in slots:
                a_name = f"asg_{c.idx}_{v.id}_{k}"
                aux_name = f"aux_{c.idx}_{v.id}_{k}"
                ub = dist_ub[c.idx]
                # aux <= UB * assign
                add_row([(aux_name, 1.0), (a_name, -ub)], -INF, 0.0)
                # aux <= total_dist_expr  ->  aux - sum(dist*z) <= route_dist(c)
                add_row([(aux_name, 1.0)] + [(n, -w) for n, w in z_terms_dist], -INF, c.route_dist_km)
                # aux >= total_dist_expr - UB*(1-assign)
                #  ->  aux - sum(dist*z) - UB*assign >= route_dist(c) - UB
                add_row([(aux_name, 1.0)] + [(n, -w) for n, w in z_terms_dist] + [(a_name, -ub)],
                        c.route_dist_km - ub, INF)

    # (11) market allocation
    for c in candidates:
        for crop in c.crop_qty:
            terms = [(f"y_{c.idx}_{crop}_{m.id}", 1.0) for m in markets]
            terms.append((f"a_{c.idx}", -1.0))
            add_row(terms, -INF, 0.0)
    for m in markets:
        crops_at_m = set(crop for c in candidates for crop in c.crop_qty)
        for crop in crops_at_m:
            terms = [(f"y_{c.idx}_{crop}_{m.id}", c.crop_qty[crop])
                     for c in candidates if crop in c.crop_qty]
            if terms:
                add_row(terms, -INF, m.capacity_kg[crop])

    # (12) spoilage
    for (cidx, crop, mid) in ym_keys:
        c = candidates[cidx]
        m = next(mm for mm in markets if mm.id == mid)
        dist = haversine(c.last_point[0], c.last_point[1], m.lat, m.lng)
        rate = CROPS[crop]["base_spoil_per_hr"]
        const_part = rate * (c.route_duration_hr + dist / AVG_SPEED_KMPH)
        sp_name = f"sp_{cidx}_{crop}_{mid}"
        sof_name = f"sof_{cidx}"
        if (cidx, crop, mid) not in cap_active_keys:
            # spoil == rate*(start_of + route_duration + dist/speed)   [cap never binds -- verified]
            add_row([(sp_name, 1.0), (sof_name, -rate)], const_part, const_part)
        else:
            cap_name = f"cap_{cidx}_{crop}_{mid}"
            # spoil <= rate*transit
            add_row([(sp_name, 1.0), (sof_name, -rate)], -INF, const_part)
            # spoil <= 0.6 (already the variable UB, no row needed)
            # spoil >= rate*transit - BIGM*cap_active
            add_row([(sp_name, 1.0), (sof_name, -rate), (cap_name, BIGM_TIME)], const_part, INF)
            # spoil >= 0.6 - BIGM*(1-cap_active)  ->  spoil - BIGM*cap_active >= 0.6 - BIGM
            add_row([(sp_name, 1.0), (cap_name, -BIGM_TIME)], 0.6 - BIGM_TIME, INF)

    # (13) rev_term[c,crop,m] = y * effective_value(spoil)
    for (cidx, crop, mid) in ym_keys:
        c = candidates[cidx]
        m = next(mm for mm in markets if mm.id == mid)
        qty_price = c.crop_qty[crop] * m.price[crop]
        ev_max = qty_price
        rev_name = f"rev_{cidx}_{crop}_{mid}"
        y_name = f"y_{cidx}_{crop}_{mid}"
        sp_name = f"sp_{cidx}_{crop}_{mid}"
        # rev <= ev_max * y
        add_row([(rev_name, 1.0), (y_name, -ev_max)], -INF, 0.0)
        # rev <= ev_max - qty_price*spoil  ->  rev + qty_price*spoil <= ev_max
        add_row([(rev_name, 1.0), (sp_name, qty_price)], -INF, ev_max)
        # rev >= ev_max*y - qty_price*spoil  ->  rev - ev_max*y + qty_price*spoil >= 0
        add_row([(rev_name, 1.0), (sp_name, qty_price), (y_name, -ev_max)], 0.0, INF)

    # (14) optional service-level constraint
    total_qty_all = sum(f.qty_kg for f in farmers)
    if service_target is not None:
        terms = [(f"y_{c.idx}_{crop}_{m.id}", c.crop_qty[crop])
                 for c in candidates for crop in c.crop_qty for m in markets]
        add_row(terms, service_target * total_qty_all, INF)

    from scipy.sparse import csr_matrix
    A = csr_matrix((vals, (rows, cols)), shape=(row[0], n_vars))
    constraints = LinearConstraint(A, np.array(lb_c), np.array(ub_c))

    # objective: maximize sum(rev_term) - [fixed costs + per-km costs]
    obj = np.zeros(n_vars)
    for (cidx, crop, mid) in ym_keys:
        obj[reg.idx(f"rev_{cidx}_{crop}_{mid}")] -= 1.0  # minimize -rev
    for c in candidates:
        for v in compat[c.idx]:
            for k in slots:
                obj[reg.idx(f"asg_{c.idx}_{v.id}_{k}")] += v.fixed_cost
                obj[reg.idx(f"aux_{c.idx}_{v.id}_{k}")] += v.per_km_cost

    from scipy.optimize import milp as _milp
    res = _milp(obj, constraints=constraints, integrality=reg.integrality(),
                bounds=reg.bounds(), options={"time_limit": time_limit, "disp": verbose})

    return _parse_solution(res, reg, candidates, fleet_list, markets, farmers, service_target, k_max_slots)


def _parse_solution(res, reg, candidates, fleet_list, markets, farmers, service_target, k_max_slots):
    status_map = {0: "optimal", 1: "time_limit_or_iteration_limit", 2: "infeasible",
                  3: "unbounded", 4: "other"}
    status_name = status_map.get(res.status, f"status_{res.status}")

    if res.x is None:
        return {
            "status": status_name, "success": False, "net_return": None,
            "mip_gap": None, "pool_results": [], "unserved_farmer_ids": [f.id for f in farmers],
            "n_candidates": len(candidates), "message": res.message,
        }

    x = res.x
    net_return = -res.fun  # we minimized the negation

    def v_(name):
        return x[reg.idx(name)]

    pool_results = []
    served_farmer_ids = set()
    for c in candidates:
        if v_(f"a_{c.idx}") < 0.5:
            continue
        assigned_vehicle = None
        # find which (v,k) this candidate landed in
        for v in fleet_list:
            found = False
            for k in range(k_max_slots):
                nm = f"asg_{c.idx}_{v.id}_{k}"
                if nm in reg._names and v_(nm) > 0.5:
                    assigned_vehicle = v
                    found = True
                    break
            if found:
                break
        if assigned_vehicle is None:
            continue  # shouldn't happen if a[c]=1, but guard

        revenue, spoil_loss_kg, market_dist, markets_used = 0.0, 0.0, {}, set()
        for crop in c.crop_qty:
            for m in markets:
                y_name = f"y_{c.idx}_{crop}_{m.id}"
                if y_name not in reg._names:
                    continue
                if v_(y_name) > 0.5:
                    qty = c.crop_qty[crop]
                    spoil = v_(f"sp_{c.idx}_{crop}_{m.id}")
                    revenue += qty * m.price[crop] * (1 - spoil)
                    spoil_loss_kg += qty * spoil
                    dist = haversine(c.last_point[0], c.last_point[1], m.lat, m.lng)
                    market_dist[m.id] = dist
                    markets_used.add(m.id)
        market_legs_km = sum(market_dist.values())
        transport_cost = assigned_vehicle.fixed_cost + assigned_vehicle.per_km_cost * (
            c.route_dist_km + market_legs_km)
        sold_qty = sum(c.crop_qty[crop] for crop in c.crop_qty
                        for m in markets if v_(f"y_{c.idx}_{crop}_{m.id}") > 0.5)
        unsold_kg = c.total_qty_kg - sold_qty
        pool_net_return = revenue - transport_cost
        per_farmer = {fid: (next(f.qty_kg for f in c.order if f.id == fid) / c.total_qty_kg) * pool_net_return
                       for fid in c.farmer_ids} if c.total_qty_kg else {}
        pool_results.append({
            "farmer_ids": list(c.farmer_ids), "vehicle_id": assigned_vehicle.id,
            "markets_used": sorted(markets_used), "total_qty_kg": c.total_qty_kg,
            "revenue": revenue, "transport_cost": transport_cost,
            "spoilage_loss_kg": spoil_loss_kg, "unsold_kg": unsold_kg,
            "unserved_no_vehicle_kg": 0.0, "net_return": pool_net_return,
            "per_farmer_net": per_farmer, "infeasible": False,
        })
        served_farmer_ids.update(c.farmer_ids)

    unserved_ids = [f.id for f in farmers if f.id not in served_farmer_ids]
    for fid in unserved_ids:
        f = next(ff for ff in farmers if ff.id == fid)
        pool_results.append({
            "farmer_ids": [fid], "vehicle_id": None, "markets_used": [],
            "total_qty_kg": f.qty_kg, "revenue": 0.0, "transport_cost": 0.0,
            "spoilage_loss_kg": 0.0, "unsold_kg": 0.0, "unserved_no_vehicle_kg": f.qty_kg,
            "net_return": 0.0, "per_farmer_net": {fid: 0.0}, "infeasible": True,
        })

    return {
        "status": status_name, "success": res.success, "net_return": net_return,
        "mip_gap": getattr(res, "mip_gap", None), "mip_dual_bound": getattr(res, "mip_dual_bound", None),
        "pool_results": pool_results, "unserved_farmer_ids": unserved_ids,
        "n_candidates": len(candidates), "service_target": service_target, "message": res.message,
    }
