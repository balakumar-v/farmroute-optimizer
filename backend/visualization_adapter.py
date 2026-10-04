"""
visualization_adapter.py
-------------------------
Converts the raw optimizer output already stored in `plan_runs` (a plan's
input_snapshot + each algorithm's {pools, summary}) into a stable,
frontend-facing "VisualizationSolution" shape, plus a deterministic
SimulationEvent timeline per dispatched trip.

This file is a CONSUMER of the optimizer's output, never a re-implementation
of it. It imports only constants/helpers from logistics_lib_v2 (the same
haversine + timing constants algorithms_v2.py itself uses) so that recomputed
distances/timings use the exact same model -- it does not invent a different
physics. Nothing here mutates or re-runs the optimizer.

Honesty rules this module follows (see the project brief it was written
against):
  - A pool with vehicle_id=None never got a truck. It is NOT rendered as a
    "route" -- its farmers are reported in `unserved_farmer_ids` instead.
  - Route polyline geometry is a straight line between real stops (farmer /
    market coordinates already in the data). This project has no road
    network, so that's the best honest geometry available. `geometry` is
    always reported as "straight_line", never implied to be a real road.
  - distanceKm is *recomputed* via haversine over that same straight-line
    geometry (the same function algorithms_v2.py uses internally), not
    invented. It is reported alongside `distance_is_derived: true`.
  - Per-stop timestamps are a deterministic RECONSTRUCTION (see
    _reconstruct_trip_timeline below), not the optimizer's literal internal
    trace. It approximates but does not byte-for-byte replicate
    assign_fleet()'s feasibility bookkeeping. Flagged via `timing_model:
    "reconstructed"` on every solution.
  - Per-market received-kg breakdown is only ever populated when it can be
    computed EXACTLY from data the optimizer actually produced:
      * individual_transport: always exact (one farmer -> one market/pool).
      * integrated_logistics_optimization: exact only if the optimizer was
        run with return_trace=True and that trace was persisted (see
        main.py) -- otherwise omitted, never estimated/split proportionally.
      * proximity_pooling: not implemented (its pools can span multiple
        markets per crop with no persisted per-market split) -- always
        omitted. `market_breakdown_available` says which of these applies.
"""

from collections import defaultdict
from typing import Any, Dict, List, Optional

from logistics_lib_v2 import (
    AVG_SPEED_KMPH,
    DISPATCH_OVERHEAD_HR,
    STOP_OVERHEAD_HR,
    TURNAROUND_HR,
    haversine,
)

ALGO_KEYS = (
    "integrated_logistics_optimization",
    "individual_transport",
    "proximity_pooling",
)

ALGO_LABELS = {
    "integrated_logistics_optimization": "Our System (ILO)",
    "individual_transport": "Individual Transport",
    "proximity_pooling": "Proximity Pooling",
}


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _route_distance_km(points: List[Dict[str, float]]) -> float:
    """Same summation algorithms_v2._route_distance uses, generalized to
    farmer+market points. `points` is an ordered list of {"lat","lng"}."""
    total = 0.0
    for a, b in zip(points, points[1:]):
        total += haversine(a["lat"], a["lng"], b["lat"], b["lng"])
    return total


def _vehicle_color_seed(vehicle_id: Optional[int]) -> int:
    """A stable integer to hash into a color client-side. Not a color
    itself -- the frontend owns the actual palette/assignment logic (a
    presentation concern), this just guarantees the same vehicle always
    seeds the same way."""
    return -1 if vehicle_id is None else int(vehicle_id)


# ---------------------------------------------------------------------------
# per-market exact receipts, where derivable without guessing
# ---------------------------------------------------------------------------

def _exact_market_receipts_individual(pools: List[dict], farmers_by_id: Dict[int, dict]):
    """individual_transport: each pool is exactly one farmer sold (partly or
    fully) to exactly one market. sold_kg = total_qty_kg - unsold_kg is
    already an exact figure the optimizer produced; which single crop/market
    it went to is unambiguous (farmer's own crop, pool's one markets_used
    entry). Keyed by POOL INDEX (not farmer id) so callers can look it up
    the same way regardless of algorithm."""
    receipts = defaultdict(lambda: defaultdict(float))  # market_id -> crop -> kg
    per_route_alloc = {}
    for i, pool in enumerate(pools):
        if pool.get("vehicle_id") is None or not pool.get("markets_used"):
            continue
        fid = pool["farmer_ids"][0]
        farmer = farmers_by_id[fid]
        market_id = pool["markets_used"][0]
        sold_kg = max(0.0, pool["total_qty_kg"] - pool["unsold_kg"])
        if sold_kg > 0:
            receipts[market_id][farmer["crop"]] += sold_kg
            per_route_alloc[i] = [{
                "market_id": market_id, "crop": farmer["crop"],
                "kg": sold_kg, "price": None,
            }]
    return receipts, per_route_alloc


def _exact_market_receipts_from_trace(trace: Dict[str, Any]):
    """integrated_logistics_optimization, only when a trace was persisted
    (see main.py's return_trace=True call). trace: {pool_id(str) ->
    {"crop_allocations": {crop -> [{"market_id","price","kg","dist_km"}]}}}."""
    receipts = defaultdict(lambda: defaultdict(float))
    per_route_alloc = {}
    for pool_id, pt in trace.items():
        edges_by_crop = pt.get("crop_allocations", {})
        flat = []
        for crop, edges in edges_by_crop.items():
            for e in edges:
                receipts[e["market_id"]][crop] += e["kg"]
                flat.append({
                    "market_id": e["market_id"], "crop": crop,
                    "kg": e["kg"], "price": e.get("price"),
                    "dist_km": e.get("dist_km"),
                })
        per_route_alloc[pool_id] = flat
    return receipts, per_route_alloc


# ---------------------------------------------------------------------------
# deterministic trip timeline reconstruction
# ---------------------------------------------------------------------------

def _reconstruct_trip_timeline(pool_idx, pool, farmers_by_id, markets_by_id,
                                vehicle_next_available, market_alloc_for_trip,
                                market_breakdown_available):
    """Builds an ordered list of SimulationEvent dicts for one dispatched
    trip (pool with a real vehicle_id), plus the trip's stop list and
    display coordinates.

    Deterministic reconstruction, not the optimizer's literal internal
    trace: uses the SAME per-stop constants algorithms_v2.py uses
    (DISPATCH_OVERHEAD_HR, STOP_OVERHEAD_HR, AVG_SPEED_KMPH, TURNAROUND_HR).

    One deliberate departure from assign_fleet()'s own bookkeeping: the
    real optimizer frees a vehicle up TURNAROUND_HR after it finishes its
    PICKUP leg, ignoring the time it then spends actually driving to
    market -- a known simplification in algorithms_v2.py (route_duration
    is computed pickup-only; see assign_fleet's docstring), not something
    this adapter should silently "fix" in the optimizer. But replaying
    that exact rule for DISPLAY timing means a vehicle's next trip can be
    shown dispatching before its previous trip's market delivery has
    animated -- the same vehicle icon in two places at once, which is a
    display bug, not a faithful visualization of a real decision (WHO
    goes with WHOM and in WHAT order is unchanged either way; only the
    clock face a viewer watches is affected). So here, a vehicle becomes
    next-available TURNAROUND_HR after this trip's full completion
    (pickups + every market leg), guaranteeing no two of the same
    vehicle's reconstructed trips ever overlap on screen.
    `vehicle_next_available` is a dict this function mutates in place
    (vehicle_id -> hour it's next free), shared across calls for all of
    one algorithm's trips so multi-trip sequencing stays consistent.
    """
    vehicle_id = pool["vehicle_id"]
    farmer_ids = pool["farmer_ids"]
    if not farmer_ids:
        return [], [], []

    ready_hr = min(farmers_by_id[fid]["ready_hr"] for fid in farmer_ids)
    t_avail = vehicle_next_available.get(vehicle_id, 0.0)
    dispatch_start = max(t_avail, ready_hr)

    events = []
    stops = []
    coords = []

    trip_id = f"trip-{pool_idx}"
    events.append({"tripId": trip_id, "vehicleId": vehicle_id, "type": "dispatch",
                    "timestamp": round(dispatch_start, 3)})

    t = dispatch_start + DISPATCH_OVERHEAD_HR
    prev = None
    for fid in farmer_ids:
        f = farmers_by_id[fid]
        if prev is not None:
            t += haversine(prev["lat"], prev["lng"], f["lat"], f["lng"]) / AVG_SPEED_KMPH
        t = max(t, f["ready_hr"])
        events.append({"tripId": trip_id, "vehicleId": vehicle_id, "type": "arrive_farmer",
                        "timestamp": round(t, 3), "locationId": fid,
                        "lat": f["lat"], "lng": f["lng"]})
        events.append({"tripId": trip_id, "vehicleId": vehicle_id, "type": "pickup",
                        "timestamp": round(t, 3), "locationId": fid,
                        "loadChangeKg": round(f["qty_kg"], 2)})
        stops.append({"type": "farmer", "id": fid, "lat": f["lat"], "lng": f["lng"]})
        coords.append([f["lng"], f["lat"]])
        t += STOP_OVERHEAD_HR
        prev = f

    for market_id in sorted(pool.get("markets_used") or []):
        m = markets_by_id[market_id]
        t += haversine(prev["lat"], prev["lng"], m["lat"], m["lng"]) / AVG_SPEED_KMPH
        events.append({"tripId": trip_id, "vehicleId": vehicle_id, "type": "arrive_market",
                        "timestamp": round(t, 3), "locationId": market_id,
                        "lat": m["lat"], "lng": m["lng"]})
        delivered_kg = None
        if market_breakdown_available:
            crops_here = market_alloc_for_trip.get(market_id)
            if crops_here is not None:
                delivered_kg = round(sum(crops_here.values()), 2)
        delivery_evt = {"tripId": trip_id, "vehicleId": vehicle_id, "type": "delivery",
                         "timestamp": round(t, 3), "locationId": market_id}
        if delivered_kg is not None:
            delivery_evt["loadChangeKg"] = -delivered_kg
        events.append(delivery_evt)
        stops.append({"type": "market", "id": market_id, "lat": m["lat"], "lng": m["lng"]})
        coords.append([m["lng"], m["lat"]])
        prev = m

    events.append({"tripId": trip_id, "vehicleId": vehicle_id, "type": "complete",
                    "timestamp": round(t, 3)})

    # See the docstring above: freed up after the FULL trip (pickups + every
    # market leg), not just after pickups, so this vehicle's next
    # reconstructed trip can never visually start before this one finishes.
    vehicle_next_available[vehicle_id] = t + TURNAROUND_HR
    return events, stops, coords


# ---------------------------------------------------------------------------
# main entry point: one algorithm's {pools, summary} -> VisualizationSolution
# ---------------------------------------------------------------------------

def build_visualization_solution(algo_key: str, input_snapshot: dict, algo_result: dict,
                                  trace: Optional[dict] = None) -> dict:
    farmers = input_snapshot["farmers"]
    fleet = input_snapshot["fleet"]
    markets = input_snapshot["markets"]
    pools = algo_result["pools"]
    summary = algo_result["summary"]

    farmers_by_id = {f["id"]: f for f in farmers}
    markets_by_id = {m["id"]: m for m in markets}
    fleet_by_id = {v["id"]: v for v in fleet}

    # ---- market receipts, only where exactly derivable ----
    market_breakdown_available = False
    receipts_by_market: Dict[int, Dict[str, float]] = {}
    alloc_by_pool: Dict[Any, list] = {}
    if algo_key == "individual_transport":
        receipts_by_market, alloc_by_pool = _exact_market_receipts_individual(pools, farmers_by_id)
        market_breakdown_available = True
    elif algo_key == "integrated_logistics_optimization" and trace:
        receipts_by_market, alloc_by_pool = _exact_market_receipts_from_trace(trace)
        market_breakdown_available = True
        # trace keys were serialized as strings (JSON object keys); pool
        # index lookups below use the same string form.

    # ---- farmers ----
    farmer_to_trip: Dict[int, str] = {}
    unserved_farmer_ids: List[int] = []
    for i, pool in enumerate(pools):
        trip_id = f"trip-{i}"
        if pool.get("vehicle_id") is None:
            unserved_farmer_ids.extend(pool["farmer_ids"])
        else:
            for fid in pool["farmer_ids"]:
                farmer_to_trip[fid] = trip_id

    farmers_out = []
    for f in farmers:
        served = f["id"] in farmer_to_trip
        farmers_out.append({
            "id": f["id"], "lat": f["lat"], "lng": f["lng"], "crop": f["crop"],
            "loadKg": f["qty_kg"], "needsRefrigeration": f["needs_refrigeration"],
            "timeWindow": {"start": f["ready_hr"], "end": f["deadline_hr"]},
            "tripId": farmer_to_trip.get(f["id"]),
            "served": served,
        })

    # ---- routes (dispatched trips only) + simulation events ----
    vehicle_next_available: Dict[int, float] = {}
    vehicle_trip_ids: Dict[int, List[str]] = defaultdict(list)
    routes_out = []
    all_events = []

    # Process trips in dispatch-readiness order per vehicle so multi-trip
    # reuse reconstructs in a physically consistent sequence (see
    # _reconstruct_trip_timeline's docstring). Grouping preserves each
    # pool's own index as its trip id regardless of processing order.
    by_vehicle: Dict[int, List[int]] = defaultdict(list)
    for i, pool in enumerate(pools):
        if pool.get("vehicle_id") is not None:
            by_vehicle[pool["vehicle_id"]].append(i)
    for vid, idxs in by_vehicle.items():
        idxs.sort(key=lambda i: min(farmers_by_id[fid]["ready_hr"] for fid in pools[i]["farmer_ids"]))
        for i in idxs:
            pool = pools[i]
            trip_id = f"trip-{i}"
            alloc_key = i if algo_key != "integrated_logistics_optimization" else str(i)
            market_alloc_for_trip: Dict[int, Dict[str, float]] = defaultdict(dict)
            for entry in alloc_by_pool.get(alloc_key, alloc_by_pool.get(i, [])):
                market_alloc_for_trip[entry["market_id"]][entry["crop"]] = entry["kg"]

            events, stops, coords = _reconstruct_trip_timeline(
                i, pool, farmers_by_id, markets_by_id, vehicle_next_available,
                market_alloc_for_trip, market_breakdown_available,
            )
            all_events.extend(events)
            vehicle_trip_ids[vid].append(trip_id)

            vehicle = fleet_by_id.get(vid, {})
            distance_km = _route_distance_km(
                [{"lat": s["lat"], "lng": s["lng"]} for s in stops]
            )
            routes_out.append({
                "id": trip_id, "vehicleId": vid,
                "farmerIds": pool["farmer_ids"], "marketIds": sorted(pool.get("markets_used") or []),
                "stops": stops, "coordinates": coords, "geometry": "straight_line",
                "distanceKm": round(distance_km, 2), "distanceIsDerived": True,
                "totalQtyKg": pool["total_qty_kg"], "revenue": pool["revenue"],
                "transportCost": pool["transport_cost"], "netReturn": pool["net_return"],
                "spoilageLossKg": pool["spoilage_loss_kg"], "unsoldKg": pool["unsold_kg"],
                "infeasible": pool.get("infeasible", False),
                "marketAllocations": (
                    alloc_by_pool.get(alloc_key, alloc_by_pool.get(i))
                    if market_breakdown_available else None
                ),
                "refrigerated": vehicle.get("refrigerated"),
            })

    # ---- vehicles (static fleet facts + which trips each one ran) ----
    vehicles_out = []
    for v in fleet:
        trip_ids = vehicle_trip_ids.get(v["id"], [])
        assigned_load = sum(
            r["totalQtyKg"] for r in routes_out if r["vehicleId"] == v["id"]
        )
        vehicles_out.append({
            "id": v["id"], "typeName": v["type_name"], "capacityKg": v["capacity_kg"],
            "refrigerated": v["refrigerated"], "fixedCost": v["fixed_cost"],
            "perKmCost": v["per_km_cost"], "tripIds": trip_ids, "used": len(trip_ids) > 0,
            "colorSeed": _vehicle_color_seed(v["id"]),
            # assignedLoadKg here is the sum across ALL this vehicle's trips
            # today, not "current load right now" (that's a moment-in-time
            # quantity the simulation engine derives client-side from
            # pickup/delivery events during playback).
            "assignedLoadKgTotal": assigned_load,
        })

    # ---- markets (+ exact receipts where available) ----
    markets_out = []
    for m in markets:
        entry = {
            "id": m["id"], "lat": m["lat"], "lng": m["lng"],
            "price": m["price"], "capacityKg": m["capacity_kg"],
        }
        if market_breakdown_available:
            entry["receivedKg"] = dict(receipts_by_market.get(m["id"], {}))
        markets_out.append(entry)

    all_events.sort(key=lambda e: e["timestamp"])

    return {
        "algorithm": algo_key,
        "algorithmLabel": ALGO_LABELS.get(algo_key, algo_key),
        "farmers": farmers_out,
        "vehicles": vehicles_out,
        "markets": markets_out,
        "routes": routes_out,
        "unservedFarmerIds": unserved_farmer_ids,
        "simulationEvents": all_events,
        "summary": summary,
        "marketBreakdownAvailable": market_breakdown_available,
        "timingModel": "reconstructed",
        "notes": (
            "Route lines are straight lines between real stop coordinates "
            "(this project has no road-network data), and distances are "
            "recomputed from those coordinates with the same haversine "
            "formula the optimizer uses internally. Stop timestamps are a "
            "deterministic reconstruction using the optimizer's own timing "
            "constants and real vehicle assignments -- not its literal "
            "internal trace."
        ),
    }


def build_plan_visualization(input_snapshot: dict, results_by_algo: Dict[str, dict],
                              ilo_trace: Optional[dict] = None) -> dict:
    """Adapts every algorithm present in a stored plan run. `results_by_algo`
    keys are the same three ALGO_KEYS main.py already stores."""
    solutions = {}
    for algo_key in ALGO_KEYS:
        if algo_key not in results_by_algo:
            continue
        trace = ilo_trace if algo_key == "integrated_logistics_optimization" else None
        solutions[algo_key] = build_visualization_solution(
            algo_key, input_snapshot, results_by_algo[algo_key], trace=trace
        )
    return {"solutions": solutions}
