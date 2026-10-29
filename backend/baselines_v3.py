"""
baselines_v3.py
----------------
Status-quo baselines, replacing the two strawmen in algorithms_v2.py (run_individual_transport_v2 /
run_proximity_pooling_v2, kept untouched as LEGACY).

Why the legacy baselines were not credible (measured on the project's synthetic data, n=1000):
  * Individual Transport drew a dedicated truck from the FPO's own finite fleet for every farmer and
    dispatched even at a loss (181 of 277 trips lost money).
  * Proximity Pooling sent every pool to the highest LISTED price whatever the distance (93 of 105 trips
    lost money), and reused ILO's own k-means depots / fleet-aware bin-packing machinery.
  * Neither had a "don't bother" option, and unserved produce was valued at Rs 0 -- but the real status
    quo for a smallholder with no pooled transport is to sell at the farm gate to a trader.

THREE REFERENCE POINTS
  1. FARM-GATE SALE (run_farmgate_baseline_v2): the farmer sells to a trader at the doorstep. No transport.
  2. INDIVIDUAL / SELF-HAUL (run_self_haul_v2): a farmer hires a spot-market vehicle (not the FPO fleet),
     drives to the NEAREST mandi that buys the crop, and pays a ROUND TRIP.
  3. PROXIMITY / NEIGHBOUR POOLING (run_neighbour_pooling_v2): up to NEIGHBOUR_MAX_GROUP farmers within
     NEIGHBOUR_RADIUS_KM of each other share one hired vehicle to the nearest mandi buying their crop(s).

TWO TIERS for 2 and 3 (`behaviour=` argument):
  * BEHAVIOURAL (default) -- how farmers actually decide. They do NOT compute profit. They haul when the
    mandi is within reach (`max_haul_km`) and its posted price clearly beats the trader's offer
    (`price_margin`), regardless of what the trip will cost or how much will spoil. Spot hire carries a
    markup and a lead time (the truck arrives `spot_lead_hr` after they ask), and a neighbour group waits
    for its last member and routes nearest-first. Because nobody checks the arithmetic, behavioural farmers
    sometimes haul at a loss and sometimes skip a trip that would have paid -- that is the point.
  * RATIONAL (`behaviour=None`) -- an upper bound on the status quo: the group computes the exact trip
    economics and hauls only if it beats everyone's farm-gate sale. Not what farmers do; it is the
    "no-regret" yardstick (an optimiser that cannot beat this should be doing nothing smarter).

ASSUMPTIONS (not data -- replace with sourced values; every one is a parameter):
  * FARMGATE_DISCOUNT = 0.20: farm-gate price is 20% below the reference mandi price (median quoted price
    across the loaded markets), or pass explicit per-crop / per-farmer prices via FarmgatePrices.
  * Behaviour defaults: max_haul_km=40, price_margin=0.10, spot_markup=1.15, spot_lead_hr=1.0. These are
    placeholders chosen to be plausible, not measured; benchmark_baselines_v3.py shows sensitivity to them.
  * Spot vehicles are non-refrigerated, priced from VEHICLE_TYPES (x spot_markup), always available.
  * Farmers know prices but NOT how crowded the mandi will be: market capacity is a first-come ledger
    (by ready time) and whatever does not fit is hauled back unsold, same as ILO's accounting.

FAIRNESS SWITCH: ILO as shipped (a) charges no empty-return leg and (b) measures spoilage from the absolute
clock, not from pickup. These baselines default to the physically correct choice for both;
`match_ilo_accounting=True` reproduces ILO's convention for a like-for-like check of the shipped ILO.
ILO v3 (ilo_v3.py) uses the correct accounting too, so compare it against the default mode.
"""

import math
from collections import defaultdict
from dataclasses import dataclass
from statistics import median
from typing import Callable, Optional

import numpy as np

from algorithms_v2 import (
    EARTH_R_KM, _withheld_result, order_route, summarize,
)
from logistics_lib_v2 import (
    AVG_SPEED_KMPH, DISPATCH_OVERHEAD_HR, STOP_OVERHEAD_HR, VEHICLE_TYPES,
    Vehicle, get_road_circuity, haversine, spoilage_fraction,
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


@dataclass(frozen=True)
class Behaviour:
    """How a real farmer decides. See module docstring; all values are assumptions."""
    max_haul_km: float = 40.0       # won't truck produce to a mandi further than this (day-trip reach)
    price_margin: float = 0.10      # mandi posted price must beat the trader's offer by at least this
    spot_markup: float = 1.15       # spot-market hire costs this multiple of the table rate
    spot_lead_hr: float = 1.0       # hours between asking for a truck and it arriving


DEFAULT_BEHAVIOUR = Behaviour()


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


class FarmgatePrices:
    """What a trader pays at the doorstep (Rs/kg). Resolution order per farmer:
         1. price_fn(farmer)  -- full control, e.g. keyed by the farmer's district/region
         2. per_kg[crop]      -- an observed doorstep price for the crop
         3. median mandi price x (1 - discount)   -- the assumption used when nothing better is known
       Pass an instance as `prices=` to the baselines, summarize_with_farmgate and run_ilo_v3."""

    def __init__(self, markets, discount=FARMGATE_DISCOUNT, per_kg=None,
                 price_fn: Optional[Callable] = None):
        self.discount = discount
        self.ref = reference_prices(markets)
        self.per_kg_by_crop = dict(per_kg or {})
        self.price_fn = price_fn

    def per_kg(self, farmer):
        if self.price_fn is not None:
            return float(self.price_fn(farmer))
        if farmer.crop in self.per_kg_by_crop:
            return float(self.per_kg_by_crop[farmer.crop])
        return self.ref.get(farmer.crop, 0.0) * (1.0 - self.discount)

    def value(self, farmer):
        return farmer.qty_kg * self.per_kg(farmer)

    def value_of(self, farmers):
        return sum(self.value(f) for f in farmers)


def _as_prices(markets, discount, prices):
    return prices if prices is not None else FarmgatePrices(markets, discount)


# ----------------------------------------------------------------------
# Spot-hired vehicle
# ----------------------------------------------------------------------
def _farmgate_result(farmers):
    """A pool that was not hauled because the farmer(s) sold at the doorstep. It is the same shape as a withheld
    pool (no vehicle, nothing sold at a mandi) plus `sold_at_farmgate`, so the UI can tell it apart from produce
    that never got a truck."""
    r = _withheld_result(list(farmers))
    r["sold_at_farmgate"] = True
    return r


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
def _timeline(order, start=None, lead=0.0):
    """Pickup time per farmer, and the time the loaded vehicle leaves the last stop. `start` defaults to the
    group's earliest ready time (rational: dispatched the moment anyone is ready); `lead` is the wait for a
    hired vehicle to arrive."""
    if start is None:
        start = min(f.ready_hr for f in order)
    t = start + lead + DISPATCH_OVERHEAD_HR
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


def _nn_order(group):
    """Nearest-first from the earliest-ready farmer: how people actually chain pickups."""
    rest = sorted(group, key=lambda f: (f.ready_hr, f.id))
    order = [rest.pop(0)]
    while rest:
        last = order[-1]
        j = min(range(len(rest)), key=lambda k: haversine(last.lat, last.lng, rest[k].lat, rest[k].lng))
        order.append(rest.pop(j))
    return order


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


def _trip_numbers(order, m, start, lead, markup, return_leg, absolute_clock):
    """Everything physical about hiring a vehicle to take `order` (in that sequence) to mandi m."""
    pickups, t_leave = _timeline(order, start, lead)
    last = order[-1]
    leg = haversine(last.lat, last.lng, m.lat, m.lng)
    t_arr = t_leave + leg / AVG_SPEED_KMPH
    qty = sum(f.qty_kg for f in order)
    vehicle, loads = _spot_vehicle(qty, None)
    back_km = haversine(m.lat, m.lng, order[0].lat, order[0].lng) if return_leg else 0.0
    trip_km = loads * (_pickup_route_km(order) + leg + back_km)
    cost = markup * (loads * vehicle.fixed_cost + vehicle.per_km_cost * trip_km)
    spoil = [spoilage_fraction(f.crop, False, t_arr if absolute_clock else t_arr - pickups[i])
             for i, f in enumerate(order)]
    return {"order": order, "market": m, "pickups": pickups, "t_leave": t_leave, "spoil": spoil,
            "vehicle": vehicle, "loads": loads, "cost": cost, "trip_km": trip_km, "qty": qty, "markup": markup}


def _evaluate_rational(group, markets, prices, return_leg, absolute_clock):
    """(plan, leftover): plan if hiring a vehicle beats everyone's farm-gate sale and meets deadlines."""
    order, _, _ = order_route(list(group), enforce_windows=True)
    last = (order[-1].lat, order[-1].lng)
    m = _nearest_market_buying_all(last, {f.crop for f in order}, markets)
    if m is None:
        return None, list(group)
    plan = _trip_numbers(order, m, None, 0.0, 1.0, return_leg, absolute_clock)
    if plan["t_leave"] > min(f.deadline_hr for f in order):
        return None, list(group)
    expected_rev = sum(f.qty_kg * m.price[f.crop] * (1 - s) for f, s in zip(order, plan["spoil"]))
    if expected_rev - plan["cost"] < prices.value_of(order):
        return None, list(group)
    return plan, []


def _evaluate_behavioural(group, markets, prices, b, return_leg, absolute_clock):
    """(plan, leftover): the farmer-style rule. No profit calculation anywhere in here."""
    group = list(group)
    cx = sum(f.lat for f in group) / len(group)
    cy = sum(f.lng for f in group) / len(group)
    m = _nearest_market_buying_all((cx, cy), {f.crop for f in group}, markets)
    if m is None or haversine(cx, cy, m.lat, m.lng) > b.max_haul_km:
        return None, group                                   # too far to bother -> sell to the trader
    if any(m.price[f.crop] < (1.0 + b.price_margin) * prices.per_kg(f) for f in group):
        return None, group                                   # mandi does not clearly pay more
    leftover = []
    while group:                                             # physical: a pickup after your deadline is a no-show
        order = _nn_order(group)
        start = max(f.ready_hr for f in order)               # the group waits for its last member
        plan = _trip_numbers(order, m, start, b.spot_lead_hr, b.spot_markup, return_leg, absolute_clock)
        late = [f for f, t in zip(order, plan["pickups"]) if t > f.deadline_hr]
        if not late:
            return plan, leftover
        leftover += late
        group = [f for f in group if f not in late]
    return None, leftover


def _execute(plan, remaining_cap, spot_id, impact=None, sold_state=None):
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
        crop_rev = 0.0
        for i in idxs:
            f = order[i]
            crop_rev += f.qty_kg * frac * m.price[crop] * (1 - spoil[i])
            spoil_loss += f.qty_kg * frac * spoil[i]
        if impact is not None and sold > 0:
            # realised price moves with what this mandi-crop has already received today (first come, first served)
            c0 = sold_state.get((m.id, crop), 0.0)
            crop_rev *= (impact.revenue(m, crop, c0 + sold) - impact.revenue(m, crop, c0)) / (m.price[crop] * sold)
            sold_state[(m.id, crop)] = c0 + sold
        revenue += crop_rev
        unsold += qty_c - sold
    net = revenue - plan["cost"]
    total_qty = plan["qty"]
    return {
        "farmer_ids": [f.id for f in order], "vehicle_id": spot_id, "markets_used": [m.id],
        "total_qty_kg": total_qty, "revenue": revenue, "transport_cost": plan["cost"],
        "spoilage_loss_kg": spoil_loss, "unsold_kg": unsold, "unserved_no_vehicle_kg": 0.0,
        "net_return": net, "per_farmer_net": {f.id: (f.qty_kg / total_qty) * net for f in order},
        "infeasible": False, "spot_hire": True, "route_distance_km": plan["trip_km"],
        # the hired vehicle is not part of the FPO fleet, so the visualization adapter needs its spec
        "vehicle_spec": {"type_name": vehicle.type_name, "capacity_kg": vehicle.capacity_kg,
                         "refrigerated": vehicle.refrigerated, "fixed_cost": vehicle.fixed_cost * plan["markup"],
                         "per_km_cost": vehicle.per_km_cost * plan["markup"], "loads": plan["loads"]},
    }


def _run_groups(groups, markets, remaining_cap, prices, behaviour, match_ilo_accounting, price_impact=None):
    return_leg = not match_ilo_accounting
    absolute_clock = match_ilo_accounting
    # first-come-first-served on the shared market ledger, by group ready time
    groups = sorted(groups, key=lambda g: (min(f.ready_hr for f in g), min(f.id for f in g)))
    results, next_spot, sold_state = [], 0, {}
    for g in groups:
        for sub in _split_if_no_common_market(g, markets):
            if behaviour is None:
                plan, leftover = _evaluate_rational(sub, markets, prices, return_leg, absolute_clock)
            else:
                plan, leftover = _evaluate_behavioural(sub, markets, prices, behaviour, return_leg, absolute_clock)
            if leftover:
                results.append(_farmgate_result(leftover))        # sells at the farm gate instead
            if plan is not None:
                next_spot += 1
                results.append(_execute(plan, remaining_cap, -next_spot, price_impact, sold_state))   # negative id = spot-hired
    return results


# ----------------------------------------------------------------------
# Public baselines
# ----------------------------------------------------------------------
def run_farmgate_baseline_v2(farmers, markets):
    """Everyone sells at the doorstep. No trips, no cost; value comes from summarize_with_farmgate()."""
    return [_farmgate_result([f]) for f in sorted(farmers, key=lambda f: f.id)]


def run_self_haul_v2(farmers, fleet, markets, remaining_cap, discount=FARMGATE_DISCOUNT,
                     match_ilo_accounting=False, behaviour=DEFAULT_BEHAVIOUR, prices=None, price_impact=None):
    """Each farmer alone: spot-hired vehicle -> nearest mandi buying the crop (round trip).
    behaviour=Behaviour(...) (default): hauls on the farmer rules, no profit calculation.
    behaviour=None: rational upper bound (hauls only if it beats the farm gate).
    `fleet` is accepted for signature parity and deliberately unused: these farmers are not customers of
    the FPO's fleet."""
    return _run_groups([[f] for f in farmers], markets, remaining_cap, _as_prices(markets, discount, prices),
                       behaviour, match_ilo_accounting, price_impact)


def _neighbour_groups(farmers, radius_km=NEIGHBOUR_RADIUS_KM, max_group=NEIGHBOUR_MAX_GROUP,
                      check_windows=True):
    """Greedy: seed = earliest-ready unassigned farmer; add its nearest unassigned neighbours within
    radius_km, up to max_group and the largest spot vehicle's capacity. check_windows=True (rational) also
    requires the members' time windows to overlap; behavioural groups form on proximity alone."""
    fl = list(farmers)
    n = len(fl)
    if n == 0:
        return []
    coords = np.radians([[f.lat, f.lng] for f in fl])
    if _HAVE_BALLTREE:
        nbrs = BallTree(coords, metric="haversine").query_radius(coords, r=radius_km / get_road_circuity() / EARTH_R_KM)
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
            if (check_windows and new_lo > new_hi) or qty + f.qty_kg > _SPOT_MAX_CAP:
                continue
            group.append(f)
            assigned.add(j)
            lo, hi, qty = new_lo, new_hi, qty + f.qty_kg
        groups.append(group)
    return groups


def run_neighbour_pooling_v2(farmers, fleet, markets, remaining_cap, discount=FARMGATE_DISCOUNT,
                             radius_km=NEIGHBOUR_RADIUS_KM, max_group=NEIGHBOUR_MAX_GROUP,
                             match_ilo_accounting=False, behaviour=DEFAULT_BEHAVIOUR, prices=None, price_impact=None):
    """Neighbours within radius_km (max_group of them) share one hired vehicle to the nearest mandi buying
    their crop(s). behaviour=Behaviour(...) (default): groups form on proximity alone, wait for the last
    member, route nearest-first and haul on the farmer rules. behaviour=None: rational upper bound
    (windows must overlap, exact economics, hauls only if it beats everyone's farm gate). `fleet` unused."""
    groups = _neighbour_groups(farmers, radius_km, max_group, check_windows=behaviour is None)
    return _run_groups(groups, markets, remaining_cap, _as_prices(markets, discount, prices), behaviour,
                       match_ilo_accounting, price_impact)


# ----------------------------------------------------------------------
# Summary that values the farm-gate fallback (works for ILO and the legacy baselines too)
# ----------------------------------------------------------------------
def summarize_with_farmgate(results, farmers, markets, fleet_size, discount=FARMGATE_DISCOUNT, prices=None):
    """summarize() + the value of produce the plan did not haul (pools with vehicle_id None -- withheld by the
    planner, never got a truck, or chosen farm-gate sale) valued at the farm-gate price. This is what the
    farmer actually walks away with, so it is the fair number to compare across algorithms.

    Vehicle counts: `vehicles_used` is every vehicle that actually drove (FPO fleet + spot hires), so the
    comparison table is not misleading for baselines that never touch the FPO fleet; `fpo_vehicles_used` and
    `vehicle_utilization_pct` refer to the FPO fleet only (non-negative ids); `spot_trips` counts hires.
    """
    prices = _as_prices(markets, discount, prices)
    s = summarize(results, len(farmers), fleet_size)
    by_id = {f.id: f for f in farmers}
    fg_kg = fg_rev = 0.0
    for r in results:
        if r["vehicle_id"] is not None:
            continue
        for fid in r["farmer_ids"]:
            f = by_id[fid]
            fg_kg += f.qty_kg
            fg_rev += prices.value(f)
    all_vehicles = {r["vehicle_id"] for r in results if r["vehicle_id"] is not None}
    fpo_vehicles = {v for v in all_vehicles if v >= 0}
    s.update({
        "vehicles_used": len(all_vehicles), "fpo_vehicles_used": len(fpo_vehicles),
        "vehicle_utilization_pct": 100 * len(fpo_vehicles) / fleet_size if fleet_size else 0,
        "spot_trips": sum(1 for r in results if r["vehicle_id"] is not None and r["vehicle_id"] < 0),
        "farmgate_kg": fg_kg, "farmgate_revenue": fg_rev, "farmgate_discount": prices.discount,
        "net_return_incl_farmgate": s["net_return"] + fg_rev,
        "net_return_per_farmer_incl_farmgate": (s["net_return"] + fg_rev) / len(farmers) if farmers else 0,
    })
    return s
