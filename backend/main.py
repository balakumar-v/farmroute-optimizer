"""
main.py
-------
FastAPI app for the FPO decision-layer course demo backend.

Endpoints:
    POST /farmers            GET /farmers
    POST /vehicles           GET /vehicles
    POST /markets             GET /markets
    POST /plan/compute
    GET  /plan/{plan_id}
    POST /sensors/reading
    POST /reset

See README.md for example request/response JSON.
"""

import copy
import dataclasses
import datetime
import json
import os
from typing import Optional, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from database import get_conn, init_db
from logistics_lib_v2 import (
    Farmer as LibFarmer,
    Vehicle as LibVehicle,
    Market as LibMarket,
    CROPS,
    VEHICLE_TYPES,
    fresh_capacity,
)
from schemas import (
    FarmerIn, FarmerOut,
    VehicleIn, VehicleOut,
    MarketIn, MarketOut,
    SensorReadingIn, SensorReadingOut,
)
import roads
from visualization_adapter import ALGO_KEYS, build_plan_visualization

VEHICLE_TYPES_BY_NAME = {t[0]: t for t in VEHICLE_TYPES}

app = FastAPI(title="FPO Decision Layer API", version="0.1.0")

# The frontend is a static index.html/app.js pair opened either straight
# from disk (file://) or via a local dev server on some other port than
# the API's :8000 -- both are cross-origin from the browser's point of
# view, so without this the frontend's fetch() calls fail silently with
# a CORS error before they ever reach a route below. Local course demo,
# no auth -- wide open is fine here.
# ALLOWED_ORIGINS: comma-separated frontend origins (no trailing slash), e.g.
# "https://my-app.onrender.com". Unset = "*" (any site), fine for local dev.
_allowed_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    init_db()


# =========================================================================
# farmers
# =========================================================================

@app.post("/farmers", response_model=FarmerOut)
def create_farmer(farmer: FarmerIn):
    needs_refrig = farmer.needs_refrigeration
    if needs_refrig is None:
        needs_refrig = CROPS[farmer.crop]["needs_refrigeration"]

    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO farmers (lat, lng, crop, qty_kg, ready_hr, deadline_hr, needs_refrigeration) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (farmer.lat, farmer.lng, farmer.crop, farmer.qty_kg,
             farmer.ready_hr, farmer.deadline_hr, int(needs_refrig)),
        )
        conn.commit()
        fid = cur.fetchone()["id"]

    return FarmerOut(
        id=fid, lat=farmer.lat, lng=farmer.lng, crop=farmer.crop,
        qty_kg=farmer.qty_kg, ready_hr=farmer.ready_hr, deadline_hr=farmer.deadline_hr,
        needs_refrigeration=needs_refrig,
    )


@app.get("/farmers", response_model=List[FarmerOut])
def list_farmers():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM farmers ORDER BY id").fetchall()
    return [
        FarmerOut(
            id=r["id"], lat=r["lat"], lng=r["lng"], crop=r["crop"], qty_kg=r["qty_kg"],
            ready_hr=r["ready_hr"], deadline_hr=r["deadline_hr"],
            needs_refrigeration=bool(r["needs_refrigeration"]),
        )
        for r in rows
    ]


# =========================================================================
# vehicles
# =========================================================================

@app.post("/vehicles", response_model=List[VehicleOut])
def create_vehicles(vehicle: VehicleIn):
    _, cap, refrig, fixed_cost, per_km_cost = VEHICLE_TYPES_BY_NAME[vehicle.type_name]

    created_ids = []
    with get_conn() as conn:
        for _ in range(vehicle.count):
            cur = conn.execute(
                "INSERT INTO vehicles (type_name, capacity_kg, refrigerated, fixed_cost, per_km_cost) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (vehicle.type_name, cap, int(refrig), fixed_cost, per_km_cost),
            )
            created_ids.append(cur.fetchone()["id"])
        conn.commit()

    return [
        VehicleOut(id=vid, type_name=vehicle.type_name, capacity_kg=cap,
                   refrigerated=refrig, fixed_cost=fixed_cost, per_km_cost=per_km_cost)
        for vid in created_ids
    ]


@app.get("/vehicles", response_model=List[VehicleOut])
def list_vehicles():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM vehicles ORDER BY id").fetchall()
    return [
        VehicleOut(
            id=r["id"], type_name=r["type_name"], capacity_kg=r["capacity_kg"],
            refrigerated=bool(r["refrigerated"]), fixed_cost=r["fixed_cost"],
            per_km_cost=r["per_km_cost"],
        )
        for r in rows
    ]


# =========================================================================
# markets
# =========================================================================

@app.post("/markets", response_model=MarketOut)
def create_market(market: MarketIn):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO markets (lat, lng, price, capacity_kg) VALUES (%s, %s, %s, %s) RETURNING id",
            (market.lat, market.lng, json.dumps(market.price), json.dumps(market.capacity_kg)),
        )
        conn.commit()
        mid = cur.fetchone()["id"]

    return MarketOut(id=mid, lat=market.lat, lng=market.lng,
                      price=market.price, capacity_kg=market.capacity_kg)


@app.get("/markets", response_model=List[MarketOut])
def list_markets():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM markets ORDER BY id").fetchall()
    return [
        MarketOut(id=r["id"], lat=r["lat"], lng=r["lng"],
                  price=json.loads(r["price"]), capacity_kg=json.loads(r["capacity_kg"]))
        for r in rows
    ]


# =========================================================================
# plan compute
# =========================================================================

@app.post("/plan/compute")
def compute_plan(road_circuity: Optional[float] = None, road_distances: bool = True, mode: str = "returns",
                 max_value_sacrifice: float = 0.10):
    """Computes and stores a plan. How distance is measured (stored with the plan as `distance_model`):

    - default: measured ROAD distances between every farmer/market pair (OpenStreetMap via OSRM, cached) so the
      plan itself changes when roads do; if road data is unavailable it falls back to straight lines.
    - road_distances=false: skip the road lookup (legacy straight-line / FARMROUTE_ROAD_CIRCUITY behaviour).
    - road_circuity=k: use a fixed road-km / straight-km factor for every distance (fit one with calibrate_circuity.py).

    What the optimizer aims for (stored in ilo_meta["mode"]):
    - mode=returns (default): maximise farmer value (net return plus the farm-gate value of what is not hauled).
    - mode=spoilage: minimise produce spoiled in transit, giving up at most `max_value_sacrifice` (a fraction,
      default 0.10) of the returns-mode value. Slower: it runs the planner several times.
    """
    if mode not in ("returns", "spoilage"):
        raise HTTPException(400, "mode must be 'returns' or 'spoilage'.")
    if not 0 <= max_value_sacrifice < 1:
        raise HTTPException(400, "max_value_sacrifice must be between 0 and 1 (e.g. 0.10 for 10%).")
    from logistics_lib_v2 import _check_circuity
    if road_circuity is not None:
        try:
            road_circuity = _check_circuity(road_circuity)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    return _compute_plan_impl(road_circuity, road_distances, mode, max_value_sacrifice)


def _compute_plan_impl(road_circuity: Optional[float] = None, road_distances: bool = True, mode: str = "returns",
                       max_value_sacrifice: float = 0.10):
    with get_conn() as conn:
        farmer_rows = conn.execute("SELECT * FROM farmers ORDER BY id").fetchall()
        vehicle_rows = conn.execute("SELECT * FROM vehicles ORDER BY id").fetchall()
        market_rows = conn.execute("SELECT * FROM markets ORDER BY id").fetchall()

    if not farmer_rows:
        raise HTTPException(400, "No farmers in the database yet -- add some via POST /farmers first.")
    if not vehicle_rows:
        raise HTTPException(400, "No vehicles in the database yet -- add some via POST /vehicles first.")
    if not market_rows:
        raise HTTPException(400, "No markets in the database yet -- add some via POST /markets first.")

    farmers = [
        LibFarmer(
            id=r["id"], lat=r["lat"], lng=r["lng"], crop=r["crop"], qty_kg=r["qty_kg"],
            ready_hr=r["ready_hr"], deadline_hr=r["deadline_hr"],
            needs_refrigeration=bool(r["needs_refrigeration"]),
        )
        for r in farmer_rows
    ]
    # Fresh Vehicle objects every call -- available_at_hr starts at 0.0 and
    # is mutated in place by the algorithm, so this template is deep-copied
    # independently for each of the three calls below (never shared).
    fleet_template = [
        LibVehicle(
            id=r["id"], type_name=r["type_name"], capacity_kg=r["capacity_kg"],
            refrigerated=bool(r["refrigerated"]), fixed_cost=r["fixed_cost"],
            per_km_cost=r["per_km_cost"], available_at_hr=0.0,
        )
        for r in vehicle_rows
    ]
    markets = [
        LibMarket(
            id=r["id"], lat=r["lat"], lng=r["lng"],
            price=json.loads(r["price"]), capacity_kg=json.loads(r["capacity_kg"]),
        )
        for r in market_rows
    ]

    # How distance is measured for THIS plan. Chosen once, stored with the plan, and replayed by the map.
    if road_circuity is not None:
        model, matrix = {"type": "circuity", "k": road_circuity, "source": "manual"}, None
    else:
        with get_conn() as conn:
            model, matrix = roads.plan_distance_model(conn, farmers, markets, enabled=road_distances)
    from logistics_lib_v2 import road_circuity as _rc, use_road_matrix
    with (use_road_matrix(matrix) if matrix is not None else _rc(model["k"])):
        return _run_plan(farmers, fleet_template, markets, model, mode, max_value_sacrifice)


def _run_plan(farmers, fleet_template, markets, model, mode="returns", max_value_sacrifice=0.10):
    # Imported lazily here (not at module load) so a problem with
    # algorithms_v2.py or one of its dependencies (numpy/scipy -- see
    # requirements.txt) only breaks this one endpoint, not the whole API.
    try:
        from algorithms_v2 import (
            run_ilo_v2,
            run_individual_transport_v2,
            run_proximity_pooling_v2,
            summarize,
        )
        from ilo_v3 import run_ilo_v3, run_ilo_v3_spoilage_first
        from baselines_v3 import (
            DEFAULT_BEHAVIOUR,
            FARMGATE_DISCOUNT,
            run_farmgate_baseline_v2,
            run_neighbour_pooling_v2,
            run_self_haul_v2,
            summarize_with_farmgate,
        )
    except ImportError as exc:
        raise HTTPException(
            500,
            "Could not import algorithms_v2.py. Make sure its dependencies "
            f"(numpy, scipy -- see requirements.txt) are installed. (import error: {exc})",
        )

    # Exact call pattern from CONTRACT.md: run_ilo_v2 (formerly named
    # run_integrated_logistics_optimization_v2 -- renamed to run_our_system_v2
    # internally, aliased as run_ilo_v2; signature unchanged) takes no
    # capacity ledger; the two baselines each get their own fresh_capacity()
    # ledger; every call gets its own copy.deepcopy(fleet).
    #
    # return_trace=True asks run_ilo_v2 for the same per-crop market-
    # allocation edges it already computes internally (allocate_markets_lp's
    # output) instead of letting _finalize() collapse them into the flat
    # pool_result. This does not change what ILO decides or how -- it's the
    # existing "live sensor-override hook" (see algorithms_v2.py) mechanism,
    # repurposed to also give the visualization layer an exact per-market kg
    # breakdown instead of only the aggregate revenue/cost numbers below.
    # The recommended plan is ILO v3 (ilo_v3.py): value-based planner that only hauls what beats the farm-gate
    # price, merges farmers heading to the same mandi into full trucks, picks the trip set with an exact solver,
    # and returns the best of its own plans and every baseline under identical accounting (meta["chosen"] says
    # which). ILO v2 is still computed, only as a legacy reference under realistic_baselines.
    if mode == "spoilage":
        res_ilo, ilo_meta, ilo_trace_json = run_ilo_v3_spoilage_first(
            farmers, fleet_template, markets, max_value_sacrifice=max_value_sacrifice, return_meta=True,
            return_trace=True)
    else:
        res_ilo, ilo_meta, ilo_trace_json = run_ilo_v3(farmers, fleet_template, markets, return_meta=True,
                                                       return_trace=True)
        ilo_meta["mode"] = "returns"
    res_ilo_v2 = run_ilo_v2(farmers, copy.deepcopy(fleet_template), markets)
    # The two comparison baselines are the BEHAVIOURAL farmer baselines from baselines_v3.py, not the old
    # strawmen: "individual_transport" = each farmer hires a spot truck to the nearest mandi if it is within
    # reach and clearly pays more than the trader (no profit calculation), else sells at the farm gate;
    # "proximity_pooling" = up to 4 neighbours within 5 km share one hired truck on the same rule. They hire
    # spot vehicles (negative vehicle ids, flagged spot_hire), not the FPO fleet, so the fleet is not used.
    # The old versions are kept under realistic_baselines (legacy_*) for reference. Rational variants
    # (exact economics, hauls only if it beats the farm gate) are the upper-bound yardstick.
    # ILO v3 and the baselines share the same accounting: the empty return leg is charged and spoilage is
    # counted from pickup. (ILO v2, the legacy reference below, does neither, which is why it is not the
    # recommended plan any more.)
    like = {}
    res_ind = run_self_haul_v2(farmers, fleet_template, markets, fresh_capacity(markets), **like)
    res_prox = run_neighbour_pooling_v2(farmers, fleet_template, markets, fresh_capacity(markets), **like)
    res_ind_legacy = run_individual_transport_v2(
        farmers, copy.deepcopy(fleet_template), markets, fresh_capacity(markets)
    )
    res_prox_legacy = run_proximity_pooling_v2(
        farmers, copy.deepcopy(fleet_template), markets, fresh_capacity(markets)
    )
    res_selfhaul_rat = run_self_haul_v2(farmers, fleet_template, markets, fresh_capacity(markets),
                                        behaviour=None, **like)
    res_neighbour_rat = run_neighbour_pooling_v2(farmers, fleet_template, markets, fresh_capacity(markets),
                                                 behaviour=None, **like)
    res_farmgate = run_farmgate_baseline_v2(farmers, markets)

    fs = len(fleet_template)
    # Every summary carries the farm-gate fields: produce a plan did not haul (withheld, no truck, or a farmer
    # who chose the farm gate) is valued at the doorstep price, so net_return_incl_farmgate is the number to
    # compare across approaches. The doorstep price is an ASSUMPTION (FARMGATE_DISCOUNT below the median
    # mandi price); it is echoed in every summary as farmgate_discount so the UI can say so.
    S = lambda res: summarize_with_farmgate(res, farmers, markets, fs)  # noqa: E731
    result_payload = {
        "integrated_logistics_optimization": {"pools": res_ilo, "summary": S(res_ilo)},
        "individual_transport": {"pools": res_ind, "summary": S(res_ind)},
        "proximity_pooling": {"pools": res_prox, "summary": S(res_prox)},
    }
    realistic_baselines = {
        "assumptions": {"farmgate_discount": FARMGATE_DISCOUNT, "behaviour": dataclasses.asdict(DEFAULT_BEHAVIOUR),
                        "baselines_use_ilo_accounting": False},
        "ilo_meta": ilo_meta,
        "legacy_ilo_v2": {"pools": res_ilo_v2, "summary": S(res_ilo_v2)},
        "farmgate_only": {"pools": res_farmgate, "summary": S(res_farmgate)},
        "self_haul_rational": {"pools": res_selfhaul_rat, "summary": S(res_selfhaul_rat)},
        "neighbour_pooling_rational": {"pools": res_neighbour_rat, "summary": S(res_neighbour_rat)},
        "legacy_individual_transport": {"pools": res_ind_legacy, "summary": S(res_ind_legacy)},
        "legacy_proximity_pooling": {"pools": res_prox_legacy, "summary": S(res_prox_legacy)},
    }

    input_snapshot = {
        "distance_model": model,
        "farmers": [f.__dict__ for f in farmers],
        "fleet": [
            {"id": v.id, "type_name": v.type_name, "capacity_kg": v.capacity_kg,
             "refrigerated": v.refrigerated, "fixed_cost": v.fixed_cost, "per_km_cost": v.per_km_cost}
            for v in fleet_template
        ],
        "markets": [
            {"id": m.id, "lat": m.lat, "lng": m.lng, "price": m.price, "capacity_kg": m.capacity_kg}
            for m in markets
        ],
    }

    created_at = datetime.datetime.utcnow().isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO plan_runs "
            "(created_at, input_snapshot, result_integrated_logistics_optimization, "
            " result_individual_transport, result_proximity_pooling, result_ilo_trace, "
            " result_realistic_baselines) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                created_at,
                json.dumps(input_snapshot),
                json.dumps(result_payload["integrated_logistics_optimization"]),
                json.dumps(result_payload["individual_transport"]),
                json.dumps(result_payload["proximity_pooling"]),
                json.dumps(ilo_trace_json),
                json.dumps(realistic_baselines),
            ),
        )
        conn.commit()
        plan_id = cur.fetchone()["id"]

    return {"id": plan_id, "created_at": created_at, "distance_model": model, **result_payload,
            "realistic_baselines": realistic_baselines}


@app.get("/plan/{plan_id}")
def get_plan(plan_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM plan_runs WHERE id = %s", (plan_id,)).fetchone()

    if row is None:
        raise HTTPException(404, f"No plan run with id {plan_id}")

    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "input_snapshot": json.loads(row["input_snapshot"]),
        "integrated_logistics_optimization": json.loads(row["result_integrated_logistics_optimization"]),
        "individual_transport": json.loads(row["result_individual_transport"]),
        "proximity_pooling": json.loads(row["result_proximity_pooling"]),
        # NULL on plan runs saved before realistic baselines existed.
        "realistic_baselines": (json.loads(row["result_realistic_baselines"])
                                 if row["result_realistic_baselines"] else None),
    }


def _straight_viz_payload(row, conn) -> dict:
    """Plan row -> the adapter's visualization payload (straight-line geometry, no road shapes yet).
    Distances and timings are computed under the distance model the plan was optimized with."""
    input_snapshot = json.loads(row["input_snapshot"])
    results_by_algo = {
        "integrated_logistics_optimization": json.loads(row["result_integrated_logistics_optimization"]),
        "individual_transport": json.loads(row["result_individual_transport"]),
        "proximity_pooling": json.loads(row["result_proximity_pooling"]),
    }
    # Older rows (from before result_ilo_trace existed) have NULL here --
    # build_plan_visualization() handles that by simply not offering an
    # exact per-market breakdown for ILO on those plans.
    raw_trace = row["result_ilo_trace"]
    ilo_trace = json.loads(raw_trace) if raw_trace else None
    with roads.distance_context(conn, input_snapshot):
        payload = build_plan_visualization(input_snapshot, results_by_algo, ilo_trace=ilo_trace)
    model = input_snapshot.get("distance_model") or {"type": "straight", "k": 1.0}
    payload["distanceModel"] = model
    for sol in payload["solutions"].values():
        for r in sol["routes"]:
            r["distanceBasis"] = model["type"]
    return payload


@app.get("/plan/{plan_id}/visualization")
def get_plan_visualization(plan_id: int):
    """Adapter endpoint (see visualization_adapter.py): the same stored plan
    run as GET /plan/{plan_id}, reshaped into one payload the map/simulation
    frontend can consume directly -- farmers/vehicles/markets/routes/
    simulation events/summary per algorithm, so the frontend never has to
    know about pools, fleets, or LP allocation edges itself. Nothing here
    is recomputed by the optimizer; it's a pure reshape of what
    /plan/compute already produced and stored.

    Routes whose real-road geometry is already cached (see roads.py) carry
    roadLegs / roadCoordinates and geometry="road"; the rest stay straight
    lines, and payload["roads"]["pending"] says how many each algorithm still lacks."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM plan_runs WHERE id = %s", (plan_id,)).fetchone()
        if row is None:
            raise HTTPException(404, f"No plan run with id {plan_id}")
        payload = _straight_viz_payload(row, conn)
        roads.attach_cached(conn, payload)
    return {"id": row["id"], "created_at": row["created_at"], **payload}


@app.post("/plan/{plan_id}/roads")
def resolve_plan_roads(plan_id: int, algo: str = "integrated_logistics_optimization", budget_s: float = 15.0):
    """Fetches real-road geometry for one algorithm's routes of a stored plan and caches it.
    Does as many routes as fit in `budget_s` seconds (capped at 25); the frontend calls this
    repeatedly until `pending` is 0. Display only: nothing here touches the optimizer or its numbers."""
    if algo not in ALGO_KEYS:
        raise HTTPException(400, f"Unknown algorithm '{algo}'. Use one of: {', '.join(ALGO_KEYS)}")
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM plan_runs WHERE id = %s", (plan_id,)).fetchone()
        if row is None:
            raise HTTPException(404, f"No plan run with id {plan_id}")
        solution = _straight_viz_payload(row, conn)["solutions"][algo]
        out = roads.resolve_pending(conn, solution, budget_s=max(1.0, min(budget_s, 25.0)))
    return {"algo": algo, **out}


# =========================================================================
# sensors
# =========================================================================

@app.post("/sensors/reading", response_model=SensorReadingOut)
def post_sensor_reading(reading: SensorReadingIn):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO sensor_readings (pool_id, temperature, humidity, timestamp) VALUES (%s, %s, %s, %s) RETURNING id",
            (reading.pool_id, reading.temperature, reading.humidity, reading.timestamp),
        )
        conn.commit()
        rid = cur.fetchone()["id"]

    return SensorReadingOut(id=rid, **reading.model_dump())


@app.get("/sensors/readings", response_model=List[SensorReadingOut])
def list_sensor_readings(pool_id: str | None = None):
    """Added for the IoT panel (section 16 of the visualization brief) --
    /sensors/reading (POST) existed with nothing to read it back with.
    Optional pool_id filter matches the "<plan_id>:<vehicle_id>" convention
    noted in schemas.py, but that convention is a frontend/hardware choice
    this endpoint doesn't enforce, so an exact string match against
    whatever was posted is all it does."""
    with get_conn() as conn:
        if pool_id is not None:
            rows = conn.execute(
                "SELECT * FROM sensor_readings WHERE pool_id = %s ORDER BY timestamp", (pool_id,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM sensor_readings ORDER BY timestamp").fetchall()
    return [
        SensorReadingOut(id=r["id"], pool_id=r["pool_id"], temperature=r["temperature"],
                          humidity=r["humidity"], timestamp=r["timestamp"])
        for r in rows
    ]


# =========================================================================
# admin
# =========================================================================

@app.post("/reset")
def reset_data():
    """Clears every farmer, vehicle, market, plan run and sensor reading --
    for starting a fresh demo without shelling into the backend to delete
    the database by hand. Resets the id counters too, so a fresh load
    afterwards gets clean IDs starting from 1."""
    tables = ("sensor_readings", "plan_runs", "farmers", "vehicles", "markets")
    with get_conn() as conn:
        cleared = {}
        for table in tables:
            cleared[table] = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        conn.execute(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY")
        conn.commit()
    return {"cleared": cleared}
