"""
baselines_v3.py
----------------
Realistic "status quo" baselines, replacing the two strawmen in algorithms_v2.py
(run_individual_transport_v2 / run_proximity_pooling_v2, kept untouched as LEGACY).

Why the legacy baselines were not credible (measured on the project's own synthetic data, n=1000):
  * Individual Transport drew a dedicated truck from the FPO's own finite fleet for every farmer and
    dispatched even at a loss (181 of 277 trips lost money).
  * Proximity Pooling sent every pool to the highest LISTED price whatever the distance (93 of 105 trips
    lost money), and reused ILO's own k-means depots / fleet-aware bin-packing machinery.
  * Neither had a "don't bother" option, and unserved produce was valued at Rs 0 -- but the real status
    quo for a smallholder with no pooled transport is to sell at the farm gate to a trader.

What these baselines model instead (all three share one decision rule):
  1. FARM-GATE SALE (run_farmgate_baseline_v2): the farmer sells to a trader at the doorstep for
     (1 - FARMGATE_DISCOUNT) x the reference mandi price. No transport at all.
  2. SELF-HAUL (run_self_haul_v2): a farmer hires a spot-market vehicle (not the FPO fleet, so it is
     never scarce), drives to the NEAREST mandi that buys the crop, and pays a ROUND-TRIP. They only go
     if that beats the farm-gate sale.
  3. NEIGHBOUR POOLING (run_neighbour_pooling_v2): up to NEIGHBOUR_MAX_GROUP farmers within
     NEIGHBOUR_RADIUS_KM of each other with overlapping time windows share one hired vehicle to the
     nearest mandi that buys their crop(s). The group goes only if that beats everyone's farm-gate sale.
     No depots, no fleet-aware sizing, no LP, no multi-market split -- what neighbours actually do.

ASSUMPTIONS (not data -- replace with sourced values; every one is a parameter):
  * FARMGATE_DISCOUNT = 0.20: farm-gate price is 20% below the reference mandi price (median quoted price
    across the loaded markets). Published farm-gate vs mandi gaps vary by crop/state; the benchmark script
    prints a sensitivity table (0.10 / 0.20 / 0.30). The conclusions about ILO's uplift DEPEND on it.
  * Spot-hired vehicles are non-refrigerated, cost the same fixed + per-km as the same-size vehicle in
    VEHICLE_TYPES, and are always available (no markup, no scarcity).
  * Farmers know the mandi price and their own spoilage when deciding, but NOT how crowded the mandi will
    be: market capacity is a first-come (by ready time) ledger, and whatever does not fit is hauled back
    unsold, same as ILO's accounting.

FAIRNESS SWITCH: ILO (algorithms_v2.py) currently (a) charges no empty-return leg and (b) measures spoilage
from the absolute clock (hour 0), not from pickup. The realistic baselines default to the physically
correct choice for both (return leg charged, spoilage from pickup), which makes them look WORSE on (a) and
BETTER on (b). `match_ilo_accounting=True` reproduces ILO's convention exactly for a like-for-like check.
"""

import math
from collections import defaultdict
from statistics import median

import numpy as np

from algorithms_v2 import (
    EARTH_R_KM, _withheld_result, order_route, summarize,
)
from logistics_lib_v2 import (
    AVG_SPEED_KMPH, DISPATCH_OVERHEAD_HR, STOP_OVERHEAD_HR, VEHICLE_TYPES,
    Vehicle, haversine, spoilage_fraction,
)

try:
    from sklearn.neighbors import BallTree
    _HAVE_BALLTREE = True
except ImportError:                                     # pragma: no cover
    _HAVE_BALLTREE = False

FARMGATE_DISCOUNT = 0.20
NEIGHBOUR_RADIUS_KM = 5.0
NEIGHBOUR_MAX_GROUP = 4

_SPOT_TYPES = sorted((t for t in VEHICLE_TYPES if not t[2]), key=lambda t: t[1])   # non-refrigerated only
_SPOT_MAX_CAP = _SPOT_TYPES[-1][1]


# ----------------------------------------------------------------------
# Prices / farm-gate value
# ----------------------------------------------------------------------
def reference_prices(markets):
    """crop -> median quoted price across markets (the regional reference a trader prices off)."""
    by_crop = defaultdict(list)
    for m in markets:
        for crop, p in m.price.items():
            by_crop[crop].append(p)
    return {c: median(ps) for c, ps in by_crop.items()}


def farmgate_value(farmer, ref, discount=FARMGATE_DISCOUNT):
    """Rs for selling the whole lot at the doorstep. 0 if no market quotes the crop (no reference)."""
    return farmer.qty_kg * ref.get(farmer.crop, 0.0) * (1.0 - discount)


# ----------------------------------------------------------------------
# Spot-hired vehicle
# ----------------------------------------------------------------------
def _spot_vehicle(qty_kg, spot_id):
    """Smallest non-refrigerated vehicle that fits qty_kg; (vehicle, n_loads). Lots above the largest
    vehicle are hauled in several loads (cost scales with n_loads)."""
    for name, cap, refrig, fixed, per_km in _SPOT_TYPES:
        if cap >= qty_kg:
            return Vehicle(spot_id, name, cap, refrig, fixed, per_km), 1
    name, cap, refrig, fixed, per_km = _SPOT_TYPES[-1]
    return Vehicle(spot_id, name, cap, refrig, fixed, per_km), math.ceil(qty_kg / cap)


# ----------------------------------------------------------------------
# One trip: timing, market choice, go/no-go decision, execution
# ----------------------------------------------------------------------
def _timeline(order):
    """Dispatch at the group's earliest ready time. Returns (pickup_time_per_farmer, time_loaded_vehicle_leaves)."""
    t = min(f.ready_hr for f in order) + DISPATCH_OVERHEAD_HR
    pickups = []
    for i, f in enumerate(order):
        if i > 0:
            t += haversine(order[i - 1].lat, order[i - 1].lng, f.lat, f.lng) / AVG_SPEED_KMPH
        t = max(t, f.ready_hr)
        pickups.append(t)
        t += STOP_OVERHEAD_HR
    return pickups, t


def _pickup_route_km(order):
    return sum(haversine(order[i].lat, order[i].lng, order[i + 1].lat, order[i + 1].lng)
               for i in range(len(order) - 1))


def _nearest_market_buying_all(point, crops, markets):
    cands = [m for m in markets if all(c in m.price and c in m.capacity_kg for c in crops)]
    if not cands:
        return None
    return min(cands, key=lambda m: haversine(point[0], point[1], m.lat, m.lng))


def _split_if_no_common_market(group, markets):
    """Neighbours who grow different crops still share a truck only if ONE mandi buys all of them;
    otherwise they split into one-crop sub-groups (each then looks for its own mandi)."""
    last = (group[-1].lat, group[-1].lng)
    if _nearest_market_buying_all(last, {f.crop for f in group}, markets) is not None:
        return [group]
    by_crop = defaultdict(list)
    for f in group:
        by_crop[f.crop].append(f)
    return list(by_crop.values())


def _evaluate_group(group, markets, ref, discount, return_leg, absolute_clock):
    """Returns a plan dict if hiring a vehicle for `group` beats everyone's farm-gate sale and meets the
    deadlines, else None (=> everyone sells at the farm gate)."""
    order, _, _ = order_route(list(group), enforce_windows=True)
    pickups, t_leave = _timeline(order)
    if t_leave > min(f.deadline_hr for f in order):
        return None
    last = (order[-1].lat, order[-1].lng)
    m = _nearest_market_buying_all(last, {f.crop for f in order}, markets)
    if m is None:
        return None
    leg = haversine(last[0], last[1], m.lat, m.lng)
    t_arr = t_leave + leg / AVG_SPEED_KMPH
    qty = sum(f.qty_kg for f in order)
    vehicle, loads = _spot_vehicle(qty, None)
    route_km = _pickup_route_km(order)
    back_km = haversine(m.lat, m.lng, order[0].lat, order[0].lng) if return_leg else 0.0
    trip_km = loads * (route_km + leg + back_km)
    cost = loads * vehicle.fixed_cost + vehicle.per_km_cost * trip_km
    spoil = [spoilage_fraction(f.crop, False, t_arr if absolute_clock else t_arr - pickups[i])
             for i, f in enumerate(order)]
    expected_rev = sum(f.qty_kg * m.price[f.crop] * (1 - s) for f, s in zip(order, spoil))
    if expected_rev - cost < sum(farmgate_value(f, ref, discount) for f in order):
        return None
    return {"order": order, "market": m, "spoil": spoil, "vehicle": vehicle, "loads": loads,
            "cost": cost, "trip_km": trip_km, "qty": qty}


def _execute(plan, remaining_cap, spot_id):
    """Sell against the shared, depleting market ledger; what does not fit is hauled back unsold."""
    order, m, spoil, vehicle = plan["order"], plan["market"], plan["spoil"], plan["vehicle"]
    vehicle.id = spot_id
    by_crop = defaultdict(list)
    for i, f in enumerate(order):
        by_crop[f.crop].append(i)
    revenue = spoil_loss = unsold = 0.0
    for crop, idxs in by_crop.items():
        qty_c = sum(order[i].qty_kg for i in idxs)
        sold = min(qty_c, max(remaining_cap[m.id].get(crop, 0.0), 0.0))
        remaining_cap[m.id][crop] = remaining_cap[m.id].get(crop, 0.0) - sold
        frac = sold / qty_c if qty_c else 0.0
        for i in idxs:
            f = order[i]
            revenue += f.qty_kg * frac * m.price[crop] * (1 - spoil[i])
            spoil_loss += f.qty_kg * frac * spoil[i]
        unsold += qty_c - sold
    net = revenue - plan["cost"]
    total_qty = plan["qty"]
    return {
        "farmer_ids": [f.id for f in order], "vehicle_id": spot_id, "markets_used": [m.id],
        "total_qty_kg": total_qty, "revenue": revenue, "transport_cost": plan["cost"],
        "spoilage_loss_kg": spoil_loss, "unsold_kg": unsold, "unserved_no_vehicle_kg": 0.0,
        "net_return": net, "per_farmer_net": {f.id: (f.qty_kg / total_qty) * net for f in order},
        "infeasible": False, "spot_hire": True, "route_distance_km": plan["trip_km"],
    }


def _run_groups(groups, markets, remaining_cap, discount, match_ilo_accounting):
    ref = reference_prices(markets)
    return_leg = not match_ilo_accounting
    absolute_clock = match_ilo_accounting
    # first-come-first-served on the shared market ledger, by group ready time
    groups = sorted(groups, key=lambda g: (min(f.ready_hr for f in g), min(f.id for f in g)))
    results, next_spot = [], 0
    for g in groups:
        for sub in _split_if_no_common_market(g, markets):
            plan = _evaluate_group(sub, markets, ref, discount, return_leg, absolute_clock)
            if plan is None:
                results.append(_withheld_result(sub))        # sells at the farm gate instead
            else:
                next_spot += 1
                results.append(_execute(plan, remaining_cap, -next_spot))   # negative id = spot-hired
    return results


# ----------------------------------------------------------------------
# Public baselines
# ----------------------------------------------------------------------
def run_farmgate_baseline_v2(farmers, markets):
    """Everyone sells at the doorstep. No trips, no cost; value comes from summarize_with_farmgate()."""
    return [_withheld_result([f]) for f in sorted(farmers, key=lambda f: f.id)]


def run_self_haul_v2(farmers, fleet, markets, remaining_cap, discount=FARMGATE_DISCOUNT,
                     match_ilo_accounting=False):
    """Each farmer alone: spot-hired vehicle -> nearest mandi buying the crop (round trip), if it beats the
    farm-gate sale. `fleet` is accepted for signature parity and deliberately unused: these farmers are
    not customers of the FPO's fleet."""
    return _run_groups([[f] for f in farmers], markets, remaining_cap, discount, match_ilo_accounting)


def _neighbour_groups(farmers, radius_km=NEIGHBOUR_RADIUS_KM, max_group=NEIGHBOUR_MAX_GROUP):
    """Greedy: seed = earliest-ready unassigned farmer; add its nearest unassigned neighbours within
    radius_km whose time windows still overlap, up to max_group and the largest spot vehicle's capacity."""
    fl = list(farmers)
    n = len(fl)
    if n == 0:
        return []
    coords = np.radians([[f.lat, f.lng] for f in fl])
    if _HAVE_BALLTREE:
        nbrs = BallTree(coords, metric="haversine").query_radius(coords, r=radius_km / EARTH_R_KM)
    else:                                               # pragma: no cover
        nbrs = [[j for j in range(n) if haversine(fl[i].lat, fl[i].lng, fl[j].lat, fl[j].lng) <= radius_km]
                for i in range(n)]
    assigned, groups = set(), []
    for i in sorted(range(n), key=lambda k: (fl[k].ready_hr, fl[k].id)):
        if i in assigned:
            continue
        assigned.add(i)
        group, lo, hi, qty = [fl[i]], fl[i].ready_hr, fl[i].deadline_hr, fl[i].qty_kg
        cands = sorted((j for j in nbrs[i] if j not in assigned),
                       key=lambda j: haversine(fl[i].lat, fl[i].lng, fl[j].lat, fl[j].lng))
        for j in cands:
            if len(group) >= max_group:
                break
            f = fl[j]
            new_lo, new_hi = max(lo, f.ready_hr), min(hi, f.deadline_hr)
            if new_lo > new_hi or qty + f.qty_kg > _SPOT_MAX_CAP:
                continue
            group.append(f)
            assigned.add(j)
            lo, hi, qty = new_lo, new_hi, qty + f.qty_kg
        groups.append(group)
    return groups


def run_neighbour_pooling_v2(farmers, fleet, markets, remaining_cap, discount=FARMGATE_DISCOUNT,
                             radius_km=NEIGHBOUR_RADIUS_KM, max_group=NEIGHBOUR_MAX_GROUP,
                             match_ilo_accounting=False):
    """Neighbours within radius_km (max_group of them, overlapping windows) share one hired vehicle to the
    nearest mandi buying their crop(s), if that beats everyone's farm-gate sale. `fleet` unused (see above)."""
    return _run_groups(_neighbour_groups(farmers, radius_km, max_group), markets, remaining_cap,
                       discount, match_ilo_accounting)


# ----------------------------------------------------------------------
# Summary that values the farm-gate fallback (works for ILO and the legacy baselines too)
# ----------------------------------------------------------------------
def summarize_with_farmgate(results, farmers, markets, fleet_size, discount=FARMGATE_DISCOUNT):
    """summarize() + the value of produce the plan did not haul (pools with vehicle_id None -- withheld by the
    planner, never got a truck, or chosen farm-gate sale) valued at the farm-gate price. This is what the
    farmer actually walks away with, so it is the fair number to compare across algorithms.

    Also fixes two summarize() quirks for spot-hired baselines: vehicles_used / utilisation count only the
    FPO fleet (non-negative vehicle ids), spot hires are reported separately as spot_trips.
    """
    s = summarize(results, len(farmers), fleet_size)
    ref = reference_prices(markets)
    by_id = {f.id: f for f in farmers}
    fg_kg = fg_rev = 0.0
    for r in results:
        if r["vehicle_id"] is not None:
            continue
        for fid in r["farmer_ids"]:
            f = by_id[fid]
            fg_kg += f.qty_kg
            fg_rev += farmgate_value(f, ref, discount)
    fpo_vehicles = {r["vehicle_id"] for r in results if r["vehicle_id"] is not None and r["vehicle_id"] >= 0}
    s.update({
        "vehicles_used": len(fpo_vehicles),
        "vehicle_utilization_pct": 100 * len(fpo_vehicles) / fleet_size if fleet_size else 0,
        "spot_trips": sum(1 for r in results if r["vehicle_id"] is not None and r["vehicle_id"] < 0),
        "farmgate_kg": fg_kg, "farmgate_revenue": fg_rev, "farmgate_discount": discount,
        "net_return_incl_farmgate": s["net_return"] + fg_rev,
        "net_return_per_farmer_incl_farmgate": (s["net_return"] + fg_rev) / len(farmers) if farmers else 0,
    })
    return s
