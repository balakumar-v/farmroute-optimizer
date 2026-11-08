"""How a trip's earnings are split among the farmers on it.

Two rules, both guaranteeing every farmer at least their own doorstep value (a trip is only kept if the pool beats
its members' combined doorstep value) and both summing to the trip's net return:

  "kg"          (default, unchanged) own doorstep value + trip surplus x (own kg / pool kg).
  "cost_aware"  revenue is attributed by each farmer's doorstep value (what their lot is worth), the pickup-route
                cost by each farmer's leave-one-out detour (how much longer the route is with them on it), and the
                remaining trip cost (fixed + legs to the mandis) by kg. Anyone pushed below their doorstep value is
                lifted to it and the others' surplus is scaled down to pay for that.

Pure functions, no I/O, so they can be tested and compared offline (tools/compare_split_rules.py).
"""
from __future__ import annotations

SPLIT_RULES = ("kg", "cost_aware")
_EPS = 1e-9


def split_kg(members, net_return, fg):
    """members: farmers; fg: {farmer_id: doorstep value}. Returns {farmer_id: payout}."""
    qty = sum(f.qty_kg for f in members)
    surplus = net_return - sum(fg[f.id] for f in members)
    return {f.id: fg[f.id] + surplus * f.qty_kg / qty for f in members}


def detours(order):
    """Leave-one-out pickup detour per farmer (km): route length minus route length without them."""
    from algorithms_v2 import _route_distance
    full = _route_distance(order)
    out = {}
    for i, f in enumerate(order):
        rest = order[:i] + order[i + 1:]
        out[f.id] = max(0.0, full - _route_distance(rest)) if rest else full
    return out, full


def split_cost_aware(order, net_return, revenue, transport_cost, fg, per_km_cost):
    """order: members in visiting order. per_km_cost: the vehicle's Rs/km (0/None -> all cost by kg)."""
    qty = sum(f.qty_kg for f in order)
    det, route_km = detours(order)
    pickup_cost = min(transport_cost, (per_km_cost or 0.0) * route_km)
    rest_cost = transport_cost - pickup_cost
    fg_total = sum(fg[f.id] for f in order)
    det_total = sum(det.values())
    pay = {}
    for f in order:
        gross = revenue * (fg[f.id] / fg_total if fg_total > _EPS else f.qty_kg / qty)
        pick = pickup_cost * (det[f.id] / det_total if det_total > _EPS else f.qty_kg / qty)
        pay[f.id] = gross - pick - rest_cost * f.qty_kg / qty
    return _lift_to_floor(order, pay, fg, net_return)


def _lift_to_floor(order, pay, fg, net_return):
    """Raise anyone below their doorstep value to it; scale the others' surplus down so the total stays net_return."""
    low = {f.id for f in order if pay[f.id] < fg[f.id]}
    if not low:
        return pay
    out = {i: fg[i] for i in low}
    free = [f for f in order if f.id not in low]
    budget = net_return - sum(fg[f.id] for f in order)          # surplus left to share, >= 0 for a kept trip
    s = {f.id: pay[f.id] - fg[f.id] for f in free}
    tot = sum(s.values())
    qty = sum(f.qty_kg for f in free)
    for f in free:
        share = (s[f.id] / tot) if tot > _EPS else (f.qty_kg / qty if qty else 0.0)
        out[f.id] = fg[f.id] + max(budget, 0.0) * share
    return out


def split_trip(rule, members, result, prices, per_km_cost=None):
    """members in any order for 'kg'; in visiting order for 'cost_aware'. result = the pool-result dict."""
    fg = {f.id: prices.value(f) for f in members}
    if rule == "kg":
        return split_kg(members, result["net_return"], fg)
    if rule == "cost_aware":
        return split_cost_aware(members, result["net_return"], result["revenue"], result["transport_cost"], fg,
                                per_km_cost)
    raise ValueError(f"split_rule must be one of {SPLIT_RULES}")
