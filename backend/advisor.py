"""
advisor.py -- read-only views over a stored ILO plan. Nothing here changes what the optimizer decides.

  fleet_advice   N4  what one extra vehicle of each class is worth (the solver's LP shadow value)
  quote_check    N2  a trader's doorstep offer vs a farmer's take-home from the planned trip: "haul" or "sell"
  impact         N3  kg moved to mandi, rupees gained vs doing nothing, km and CO2 saved by pooling
  payout_statements  #5  what each farmer receives, line by line, reconciled to the plan total
  diff_plans     N8  which farmers a re-plan actually changed, and what changed for each
  driver_sheet   #4  one vehicle's trips in order: where to go, when, how many kg to collect
  farmer_cards   #3  the one card each farmer is allowed to see (their own data only)
  farmer_status      "hauled" / "farmgate" / "unserved" for one farmer (shared by the portal and payout views)

All inputs are the JSON shapes /plan/{id} already returns, so a plan read back from Postgres works unchanged.
"""
from logistics_lib_v2 import Market, haversine
from baselines_v3 import FarmgatePrices

_EPS = 1e-6

# --- EMISSION ASSUMPTIONS (not measured data; edit here, the API echoes them in every impact response) ---
# Diesel burns ~2.68 kg CO2 per litre. Fuel economy by vehicle class is a rough planning figure for Indian
# light/medium goods vehicles, loaded; refrigerated bodies burn more. Replace with transporter-reported
# figures when you have them.
DIESEL_KG_CO2_PER_L = 2.68
KM_PER_LITRE = {  # (capacity_kg, refrigerated) -> km per litre
    (1000, False): 12.0, (2000, False): 9.0, (2000, True): 7.5, (5000, False): 6.0, (5000, True): 5.0,
}
DEFAULT_KM_PER_LITRE = 8.0


def class_label(capacity_kg, refrigerated):
    """Same label ilo_v3._class_label gives a vehicle class, so shadow values line up with fleet rows."""
    return f"{capacity_kg:g}kg{'-reefer' if refrigerated else ''}"


def _pool_for(pools, farmer_id):
    return next((p for p in pools if farmer_id in p["farmer_ids"]), None)


def farmer_status(pools, farmer_id):
    """'hauled' (rides a trip), 'unserved' (wanted a truck, none free) or 'farmgate' (sold at the doorstep:
    the planner judged hauling not worth it)."""
    p = _pool_for(pools, farmer_id)
    if p is None:
        return None
    if p["vehicle_id"] is not None:
        return "hauled"
    return "unserved" if p.get("unserved_no_vehicle_kg", 0.0) > _EPS else "farmgate"


def _prices(snapshot, discount):
    markets = [Market(id=m["id"], lat=m["lat"], lng=m["lng"], price=m["price"], capacity_kg=m["capacity_kg"])
               for m in snapshot["markets"]]
    return FarmgatePrices(markets, discount=discount)


def _discount(plan):
    rb = plan.get("realistic_baselines") or {}
    return (rb.get("assumptions") or {}).get("farmgate_discount", 0.20)


# ----------------------------------------------------------------------
# N4  Fleet advisor
# ----------------------------------------------------------------------
def fleet_advice(snapshot, ilo, ilo_meta):
    """`ilo` = {"pools": [...]}; `ilo_meta` = realistic_baselines["ilo_meta"] of the stored plan."""
    fa = (ilo_meta or {}).get("fleet_aware") or {}
    shadow = fa.get("shadow_value_per_extra_vehicle")
    if shadow is None:
        return {"available": False,
                "reason": "No shadow value on this plan (the fleet-aware solver did not run or found no trips)."}
    owned, used_ids = {}, {}
    cls_of = {}
    for v in snapshot["fleet"]:
        lab = class_label(v["capacity_kg"], v["refrigerated"])
        owned[lab] = owned.get(lab, 0) + 1
        cls_of[v["id"]] = lab
    trips = {}
    for p in ilo["pools"]:
        if p["vehicle_id"] is not None and p["vehicle_id"] in cls_of:
            lab = cls_of[p["vehicle_id"]]
            trips[lab] = trips.get(lab, 0) + 1
            used_ids.setdefault(lab, set()).add(p["vehicle_id"])
    classes = []
    for lab in sorted(owned):
        sv = float(shadow.get(lab, 0.0))
        idle = owned[lab] - len(used_ids.get(lab, ()))
        advice = "add" if sv > 1.0 else ("surplus" if idle > 0 else "enough")
        classes.append({"class": lab, "owned": owned[lab], "trips_run": trips.get(lab, 0),
                        "idle_vehicles": idle, "shadow_value_inr": sv, "advice": advice})
    best = max(classes, key=lambda c: c["shadow_value_inr"], default=None)
    return {
        "available": True,
        "classes": classes,
        "best_addition": best["class"] if best and best["shadow_value_inr"] > 1.0 else None,
        "plan_chosen": ilo_meta.get("chosen"),
        "applies_to_returned_plan": not ilo_meta.get("safeguard_used", False),
        "notes": [
            "Shadow value = extra rupees (over selling at the farm gate) the planner could earn if it had one "
            "more vehicle of that class, from the LP relaxation of its trip-selection program. It is a "
            "first-order estimate, not a promise.",
            "It is already net of running cost (fixed + per-km) but NOT of buying or renting the vehicle.",
            "Estimated on the solver's own trip options; if applies_to_returned_plan is false the returned "
            "plan was a baseline fallback, so read it as indicative only.",
        ],
    }


# ----------------------------------------------------------------------
# N2  Doorstep quote check
# ----------------------------------------------------------------------
def quote_check(plan, farmer_id, quote_per_kg):
    """Haul or sell? Compares the trader's quote (Rs/kg, for the farmer's whole lot) with the farmer's
    take-home from the planned trip (`per_farmer_net`, which already includes their share of costs).
    Raises KeyError if the farmer is unknown, ValueError if the quote is not a positive number."""
    if not quote_per_kg or quote_per_kg <= 0:
        raise ValueError("quote_per_kg must be a positive number (Rs per kg).")
    snap, ilo = plan["input_snapshot"], plan["integrated_logistics_optimization"]
    farmer = next((f for f in snap["farmers"] if f["id"] == farmer_id), None)
    if farmer is None:
        raise KeyError(farmer_id)
    qty = farmer["qty_kg"]
    sell_value = quote_per_kg * qty
    status = farmer_status(ilo["pools"], farmer_id)
    assumed = _prices(snap, _discount(plan)).per_kg(_as_obj(farmer))
    out = {"farmer_id": farmer_id, "crop": farmer["crop"], "qty_kg": qty, "status": status,
           "quote_per_kg": quote_per_kg, "sell_value_inr": sell_value,
           "assumed_doorstep_per_kg": assumed}
    if status == "hauled":
        pool = _pool_for(ilo["pools"], farmer_id)
        take_home = float(pool["per_farmer_net"][str(farmer_id)] if str(farmer_id) in pool["per_farmer_net"]
                          else pool["per_farmer_net"][farmer_id])
        out.update(
            decision="haul" if take_home > sell_value + _EPS else "sell",
            haul_take_home_inr=take_home,
            advantage_of_hauling_inr=take_home - sell_value,
            break_even_quote_per_kg=take_home / qty,
            note="Haul if the trader's quote is below break_even_quote_per_kg. Take-home is the farmer's share of "
                 "the planned trip after transport cost and transit spoilage; it assumes the other riders also "
                 "go, and the plan is not re-optimised if this farmer drops out.")
    else:
        out.update(
            decision="no_trip_planned",
            note="The planner did not haul this farmer's produce because it did not beat the assumed doorstep "
                 "price" + (" (and no truck was free)." if status == "unserved" else ".") +
                 " A quote below assumed_doorstep_per_kg may change that: re-plan with the real quote.")
    return out


def _as_obj(d):
    from types import SimpleNamespace
    return SimpleNamespace(**d)


# ----------------------------------------------------------------------
# N3  Impact counters
# ----------------------------------------------------------------------
def _co2_per_km(capacity_kg, refrigerated):
    kmpl = KM_PER_LITRE.get((capacity_kg, bool(refrigerated)), DEFAULT_KM_PER_LITRE)
    return DIESEL_KG_CO2_PER_L / kmpl


def impact(plan, routes):
    """`routes` = the ILO solution's routes from the visualization payload (they carry stop order).
    Call inside roads.distance_context(...) so distances match the ones the plan was optimised with."""
    snap, ilo = plan["input_snapshot"], plan["integrated_logistics_optimization"]
    base = (plan.get("realistic_baselines") or {}).get("farmgate_only")
    pools = ilo["pools"]
    hauled = [p for p in pools if p["vehicle_id"] is not None]
    kg_hauled = sum(p["total_qty_kg"] for p in hauled)
    kg_spoiled = sum(p["spoilage_loss_kg"] for p in hauled)
    kg_unsold = sum(p["unsold_kg"] for p in hauled)

    prices = _prices(snap, _discount(plan))
    by_id = {f["id"]: f for f in snap["farmers"]}
    gains = []
    for p in hauled:
        for fid in p["farmer_ids"]:
            f = by_id[fid]
            net = p["per_farmer_net"].get(str(fid), p["per_farmer_net"].get(fid))
            gains.append(float(net) - prices.value(_as_obj(f)))

    summary = ilo["summary"]
    rupees = None
    if base is not None:
        rupees = summary["net_return_incl_farmgate"] - base["summary"]["net_return_incl_farmgate"]

    fleet = {v["id"]: v for v in snap["fleet"]}
    km_pooled = km_separate = co2_pooled = co2_saved = 0.0
    comparable = 0
    for r in routes:
        stops, markets = r["stops"], [s for s in r["stops"] if s["type"] == "market"]
        if len(markets) != 1 or stops[-1]["type"] != "market":
            continue                                    # multi-mandi trip: no clean separate-trips comparison
        m, farm = stops[-1], stops[:-1]
        loop = haversine(m["lat"], m["lng"], farm[0]["lat"], farm[0]["lng"]) \
            + sum(haversine(a["lat"], a["lng"], b["lat"], b["lng"]) for a, b in zip(farm, farm[1:])) \
            + haversine(farm[-1]["lat"], farm[-1]["lng"], m["lat"], m["lng"])
        apart = sum(2 * haversine(s["lat"], s["lng"], m["lat"], m["lng"]) for s in farm)
        v = fleet.get(r["vehicleId"])
        f = _co2_per_km(v["capacity_kg"], v["refrigerated"]) if v else _co2_per_km(0, False)
        km_pooled += loop
        km_separate += apart
        co2_pooled += loop * f
        co2_saved += (apart - loop) * f                  # assumes separate trips use the same vehicle type
        comparable += 1

    return {
        "kg_hauled_to_mandi": kg_hauled,
        "kg_spoiled_in_transit": kg_spoiled,
        "kg_unsold_at_mandi": kg_unsold,
        "kg_reaching_buyers": kg_hauled - kg_spoiled - kg_unsold,
        "rupees_gained_vs_farmgate_only": rupees,
        "farmers_hauled": len(gains),
        "gain_per_hauled_farmer_inr": {
            "mean": sum(gains) / len(gains) if gains else 0.0,
            "min": min(gains) if gains else 0.0,
            "max": max(gains) if gains else 0.0},
        "km_pooled": km_pooled,
        "km_if_hauled_separately": km_separate,
        "km_saved_by_pooling": km_separate - km_pooled,
        "co2_kg_pooled": co2_pooled,
        "co2_kg_saved_by_pooling": co2_saved,
        "trips_compared": comparable,
        "assumptions": {
            "farmgate_discount": _discount(plan),
            "diesel_kg_co2_per_litre": DIESEL_KG_CO2_PER_L,
            "km_per_litre": {class_label(c, r): v for (c, r), v in KM_PER_LITRE.items()},
            "separate_trips_use_same_vehicle_type": True,
        },
        "notes": [
            "Rupees gained is against selling every lot at the assumed doorstep price, not against real "
            "farmer behaviour; the doorstep price is an assumption.",
            "Produce sold at the farm gate is not counted as wasted, so there is no 'food saved' figure; "
            "kg_reaching_buyers is what the plan actually moved to a mandi after transit spoilage.",
            "km and CO2 'saved' compare each pooled trip with the same farmers hauling separately to the same "
            "mandi (closed loop mandi -> farms -> mandi). Multi-mandi trips are left out of that comparison.",
            "Emission factors are rough planning assumptions (see assumptions); treat CO2 as indicative.",
        ],
    }


# ----------------------------------------------------------------------
# #5  Per-farmer payout statement
# ----------------------------------------------------------------------
# Tags say how much to trust a line: "exact" = a number the farmer/operator entered, "derived" = computed by the
# planner from those inputs, "assumed" = rests on the doorstep-price assumption.
def payout_statements(plan):
    """One statement per farmer. A hauled farmer gets their own farm-gate value plus a quantity share of the
    trip's surplus (ILO v3's value-gain split); anyone not hauled is valued at the assumed doorstep price.
    The totals add up to the plan's net_return_incl_farmgate (checked in the tests)."""
    snap, ilo = plan["input_snapshot"], plan["integrated_logistics_optimization"]
    prices = _prices(snap, _discount(plan))
    out = []
    for f in snap["farmers"]:
        fid, status = f["id"], farmer_status(ilo["pools"], f["id"])
        fg_value = prices.value(_as_obj(f))
        lines = [
            {"key": "crop", "label": "Crop", "value": f["crop"], "tag": "exact"},
            {"key": "qty_kg", "label": "Quantity (kg)", "value": f["qty_kg"], "tag": "exact"},
            {"key": "doorstep_per_kg", "label": "Assumed doorstep price (Rs/kg)",
             "value": prices.per_kg(_as_obj(f)), "tag": "assumed"},
            {"key": "doorstep_value", "label": "Value if sold at the doorstep (Rs)", "value": fg_value,
             "tag": "assumed"},
        ]
        trip = None
        if status == "hauled":
            pool = _pool_for(ilo["pools"], fid)
            total = float(pool["per_farmer_net"].get(str(fid), pool["per_farmer_net"].get(fid)))
            lines.append({"key": "trip_share", "label": "Your share of the trip's extra earnings (Rs)",
                          "value": total - fg_value, "tag": "derived"})
            trip = {"vehicle_id": pool["vehicle_id"], "markets_used": pool["markets_used"],
                    "dispatch_hr": pool.get("dispatch_hr"), "farmers_on_trip": len(pool["farmer_ids"]),
                    "trip_revenue_inr": pool["revenue"], "trip_transport_cost_inr": pool["transport_cost"],
                    "trip_spoilage_kg": pool["spoilage_loss_kg"]}
        else:
            total = fg_value
        out.append({"farmer_id": fid, "status": status, "lines": lines, "total_inr": total, "trip": trip})
    return {"total_inr": sum(s["total_inr"] for s in out),
            "plan_value_inr": ilo["summary"]["net_return_incl_farmgate"],
            "statements": out}


# ----------------------------------------------------------------------
# N8  Plan diff
# ----------------------------------------------------------------------
def _placement(plan):
    """farmer_id -> what the plan does for them."""
    pools = plan["integrated_logistics_optimization"]["pools"]
    snap = plan["input_snapshot"]
    stm = {s["farmer_id"]: s for s in payout_statements(plan)["statements"]}
    out = {}
    for f in snap["farmers"]:
        fid, st = f["id"], stm[f["id"]]
        pool = _pool_for(pools, fid)
        hauled = st["status"] == "hauled"
        out[fid] = {"status": st["status"], "vehicle_id": pool["vehicle_id"] if hauled else None,
                    "markets": sorted(pool["markets_used"]) if hauled else [],
                    "dispatch_hr": pool.get("dispatch_hr") if hauled else None,
                    "payout_inr": st["total_inr"]}
    return out


def diff_plans(old, new, min_payout_change_inr=1.0, min_dispatch_shift_hr=0.5):
    """Who a re-plan touched. Only farmers whose status, truck, mandi, pickup time (beyond
    `min_dispatch_shift_hr`) or payout (beyond `min_payout_change_inr`) changed are listed, each with
    plain-language reasons, so only they need a message."""
    a, b = _placement(old), _placement(new)
    changed = []
    for fid in sorted(set(a) & set(b)):
        x, y, why = a[fid], b[fid], []
        if x["status"] != y["status"]:
            why.append(f"status changed from {x['status']} to {y['status']}")
        if x["vehicle_id"] != y["vehicle_id"] and x["status"] == y["status"] == "hauled":
            why.append(f"moved to a different truck (vehicle {x['vehicle_id']} -> {y['vehicle_id']})")
        if x["markets"] != y["markets"] and x["status"] == y["status"] == "hauled":
            why.append(f"mandi changed ({x['markets']} -> {y['markets']})")
        if (x["dispatch_hr"] is not None and y["dispatch_hr"] is not None
                and abs(x["dispatch_hr"] - y["dispatch_hr"]) >= min_dispatch_shift_hr):
            why.append(f"pickup time moved from hour {x['dispatch_hr']:.2f} to {y['dispatch_hr']:.2f}")
        delta = y["payout_inr"] - x["payout_inr"]
        if abs(delta) >= min_payout_change_inr:
            why.append(f"payout {'up' if delta > 0 else 'down'} by Rs {abs(delta):,.0f}")
        if why:
            changed.append({"farmer_id": fid, "before": x, "after": y, "payout_change_inr": delta, "why": why})
    return {"farmers_changed": len(changed), "farmers_unchanged": len(set(a) & set(b)) - len(changed),
            "farmers_only_in_old": sorted(set(a) - set(b)), "farmers_only_in_new": sorted(set(b) - set(a)),
            "changed": changed}


# ----------------------------------------------------------------------
# #4  Driver route sheet
# ----------------------------------------------------------------------
def _hhmm(hours):
    m = round(hours * 60)
    return f"{m // 60:02d}:{m % 60:02d}"


def _maps_link(lat, lng):
    return f"https://www.google.com/maps/search/?api=1&query={lat:.6f},{lng:.6f}"


def driver_sheet(plan, solution, vehicle_id):
    """One vehicle's trips, in dispatch order. `solution` = the ILO solution from the visualization payload
    (routes carry stop order, simulationEvents carry the planned arrival times and pickup weights).
    Raises KeyError if no trip uses this vehicle. Times are hours from plan start and are PLANNED, not tracked."""
    routes = [r for r in solution["routes"] if r["vehicleId"] == vehicle_id]
    if not routes:
        raise KeyError(vehicle_id)
    snap = plan["input_snapshot"]
    farmers = {f["id"]: f for f in snap["farmers"]}
    veh = next((v for v in snap["fleet"] if v["id"] == vehicle_id), None)
    trips = []
    for r in routes:
        ev = [e for e in solution["simulationEvents"] if e["tripId"] == r["id"]]
        dispatch = next((e["timestamp"] for e in ev if e["type"] == "dispatch"), None)
        eta = {("farmer", e["locationId"]): e["timestamp"] for e in ev if e["type"] == "arrive_farmer"}
        eta.update({("market", e["locationId"]): e["timestamp"] for e in ev if e["type"] == "arrive_market"})
        kg = {e["locationId"]: e["loadChangeKg"] for e in ev if e["type"] == "pickup"}
        stops, load = [], 0.0
        for i, st in enumerate(r["stops"], start=1):
            t = eta.get((st["type"], st["id"]))
            row = {"seq": i, "type": "pickup" if st["type"] == "farmer" else "dropoff", "id": st["id"],
                   "lat": st["lat"], "lng": st["lng"], "eta_hr": t, "eta": _hhmm(t) if t is not None else None,
                   "maps_link": _maps_link(st["lat"], st["lng"])}
            if st["type"] == "farmer":
                row.update(crop=farmers[st["id"]]["crop"], kg=kg.get(st["id"], farmers[st["id"]]["qty_kg"]))
                load += row["kg"]
            else:
                row.update(kg=load)
            stops.append(row)
        wp = "|".join(f"{s['lat']:.6f},{s['lng']:.6f}" for s in stops[:-1])
        last = stops[-1]
        trips.append({
            "trip_id": r["id"], "dispatch_hr": dispatch, "dispatch": _hhmm(dispatch) if dispatch is not None else None,
            "total_kg": load, "distance_km": r["distanceKm"], "refrigerated": r["refrigerated"], "stops": stops,
            "route_link": ("https://www.google.com/maps/dir/?api=1&travelmode=driving"
                           f"&destination={last['lat']:.6f},{last['lng']:.6f}" + (f"&waypoints={wp}" if wp else ""))})
    trips.sort(key=lambda t: (t["dispatch_hr"] is None, t["dispatch_hr"]))
    return {"vehicle_id": vehicle_id, "vehicle_type": veh["type_name"] if veh else None,
            "capacity_kg": veh["capacity_kg"] if veh else None, "trips": trips,
            "note": "Times are hours:minutes from the start of the plan (hour 0) and are planned estimates, not "
                    "live tracking. distance_km is the plan's one-way pickup-to-mandi distance."}


# ----------------------------------------------------------------------
# #3  Farmer cards (what the farmer-facing app may show)
# ----------------------------------------------------------------------
def farmer_cards(plan, solution, published_at, previous_plan=None, fpo_phone=None):
    """{farmer_id: card}. A card holds ONLY that farmer's own facts: no other farmer's id, quantity or payout,
    and no trip-level revenue or cost (those would let a farmer back out what co-riders earn). Built once when an
    operator publishes a plan, so a farmer's request reads one card and never touches the plan itself.
    `solution` = the ILO solution from the visualization payload (for planned pickup times).
    `previous_plan`, if given, adds `changed` (plain-language reasons) for farmers the re-plan touched."""
    snap, ilo = plan["input_snapshot"], plan["integrated_logistics_optimization"]
    markets = {m["id"]: m for m in snap["markets"]}
    fleet = {v["id"]: v for v in snap["fleet"]}
    pickup_eta = {}
    for r in solution["routes"]:
        ev = [e for e in solution["simulationEvents"] if e["tripId"] == r["id"]]
        for e in ev:
            if e["type"] == "arrive_farmer":
                pickup_eta[e["locationId"]] = e["timestamp"]
    changes = {}
    if previous_plan is not None:
        changes = {c["farmer_id"]: c["why"] for c in diff_plans(previous_plan, plan)["changed"]}

    cards = {}
    for st in payout_statements(plan)["statements"]:
        fid = st["farmer_id"]
        f = next(x for x in snap["farmers"] if x["id"] == fid)
        trip = None
        if st["status"] == "hauled":
            pool = _pool_for(ilo["pools"], fid)
            veh = fleet.get(pool["vehicle_id"])
            eta = pickup_eta.get(fid)
            trip = {"pickup_eta_hr": eta, "pickup_eta": _hhmm(eta) if eta is not None else None,
                    "dispatch_hr": pool.get("dispatch_hr"),
                    "vehicle_type": veh["type_name"] if veh else "spot_truck",
                    "refrigerated": bool(veh["refrigerated"]) if veh else None,
                    "farmers_on_trip": len(pool["farmer_ids"]),
                    "mandis": [{"id": m, "lat": markets[m]["lat"], "lng": markets[m]["lng"]}
                               for m in pool["markets_used"] if m in markets]}
        cards[fid] = {
            "farmer_id": fid, "crop": f["crop"], "qty_kg": f["qty_kg"], "status": st["status"],
            "ready_hr": f["ready_hr"], "deadline_hr": f["deadline_hr"],
            "payout": {"total_inr": st["total_inr"], "lines": st["lines"]},
            "trip": trip, "changed": changes.get(fid) if previous_plan is not None else None,
            "published_at": published_at,
            # lets the app answer "haul or sell?" on the phone, offline: haul if the trader's quote is BELOW this
            "break_even_per_kg": (st["total_inr"] / f["qty_kg"]) if st["status"] == "hauled" else None,
            "doorstep_per_kg": next(l["value"] for l in st["lines"] if l["key"] == "doorstep_per_kg"),
            "fpo_phone": fpo_phone,
            "note": "Times are hours:minutes from the start of the plan and are planned estimates. Prices marked "
                    "'assumed' are estimates of the doorstep price, not quotes.",
        }
    return cards
