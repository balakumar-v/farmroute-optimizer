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
import datetime
import json
from typing import List

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
from visualization_adapter import build_plan_visualization

VEHICLE_TYPES_BY_NAME = {t[0]: t for t in VEHICLE_TYPES}

app = FastAPI(title="FPO Decision Layer API", version="0.1.0")

# The frontend is a static index.html/app.js pair opened either straight
# from disk (file://) or via a local dev server on some other port than
# the API's :8000 -- both are cross-origin from the browser's point of
# view, so without this the frontend's fetch() calls fail silently with
# a CORS error before they ever reach a route below. Local course demo,
# no auth -- wide open is fine here.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (farmer.lat, farmer.lng, farmer.crop, farmer.qty_kg,
             farmer.ready_hr, farmer.deadline_hr, int(needs_refrig)),
        )
        conn.commit()
        fid = cur.lastrowid

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
                "VALUES (?, ?, ?, ?, ?)",
                (vehicle.type_name, cap, int(refrig), fixed_cost, per_km_cost),
            )
            created_ids.append(cur.lastrowid)
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
            "INSERT INTO markets (lat, lng, price, capacity_kg) VALUES (?, ?, ?, ?)",
            (market.lat, market.lng, json.dumps(market.price), json.dumps(market.capacity_kg)),
        )
        conn.commit()
        mid = cur.lastrowid

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
def compute_plan():
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
        from baselines_v3 import (
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
    res_ilo, trace_ilo = run_ilo_v2(farmers, copy.deepcopy(fleet_template), markets, return_trace=True)
    res_ind = run_individual_transport_v2(
        farmers, copy.deepcopy(fleet_template), markets, fresh_capacity(markets)
    )
    res_prox = run_proximity_pooling_v2(
        farmers, copy.deepcopy(fleet_template), markets, fresh_capacity(markets)
    )
    # Realistic status-quo baselines (baselines_v3.py). ADDITIVE: the three keys above keep their legacy
    # meaning so the existing frontend/visualization adapter are untouched; these are returned and stored
    # under a separate key. Every summary here also carries net_return_incl_farmgate (produce the plan did
    # not haul is valued at the farm-gate price) -- compare THAT number across algorithms.
    res_selfhaul = run_self_haul_v2(farmers, fleet_template, markets, fresh_capacity(markets))
    res_neighbour = run_neighbour_pooling_v2(farmers, fleet_template, markets, fresh_capacity(markets))
    res_farmgate = run_farmgate_baseline_v2(farmers, markets)

    # JSON object keys are always strings, so pool_id is stringified here
    # rather than left as PoolTrace's native int -- visualization_adapter.py
    # expects that (it reads this same column back after a json round trip).
    ilo_trace_json = {
        str(pt.pool_id): {"crop_allocations": dict(pt.crop_allocations)}
        for pt in trace_ilo.values()
    }

    n_farmers, fleet_size = len(farmers), len(fleet_template)
    result_payload = {
        "integrated_logistics_optimization": {"pools": res_ilo, "summary": summarize(res_ilo, n_farmers, fleet_size)},
        "individual_transport": {"pools": res_ind, "summary": summarize(res_ind, n_farmers, fleet_size)},
        "proximity_pooling": {"pools": res_prox, "summary": summarize(res_prox, n_farmers, fleet_size)},
    }

    fs = len(fleet_template)
    realistic_baselines = {
        "ilo_with_farmgate": summarize_with_farmgate(res_ilo, farmers, markets, fs),
        "individual_transport_legacy_with_farmgate": summarize_with_farmgate(res_ind, farmers, markets, fs),
        "proximity_pooling_legacy_with_farmgate": summarize_with_farmgate(res_prox, farmers, markets, fs),
        "farmgate_only": {"pools": res_farmgate, "summary": summarize_with_farmgate(res_farmgate, farmers, markets, fs)},
        "self_haul": {"pools": res_selfhaul, "summary": summarize_with_farmgate(res_selfhaul, farmers, markets, fs)},
        "neighbour_pooling": {"pools": res_neighbour, "summary": summarize_with_farmgate(res_neighbour, farmers, markets, fs)},
    }

    input_snapshot = {
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
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
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
        plan_id = cur.lastrowid

    return {"id": plan_id, "created_at": created_at, **result_payload,
            "realistic_baselines": realistic_baselines}


@app.get("/plan/{plan_id}")
def get_plan(plan_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM plan_runs WHERE id = ?", (plan_id,)).fetchone()

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


@app.get("/plan/{plan_id}/visualization")
def get_plan_visualization(plan_id: int):
    """Adapter endpoint (see visualization_adapter.py): the same stored plan
    run as GET /plan/{plan_id}, reshaped into one payload the map/simulation
    frontend can consume directly -- farmers/vehicles/markets/routes/
    simulation events/summary per algorithm, so the frontend never has to
    know about pools, fleets, or LP allocation edges itself. Nothing here
    is recomputed by the optimizer; it's a pure reshape of what
    /plan/compute already produced and stored."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM plan_runs WHERE id = ?", (plan_id,)).fetchone()

    if row is None:
        raise HTTPException(404, f"No plan run with id {plan_id}")

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

    payload = build_plan_visualization(input_snapshot, results_by_algo, ilo_trace=ilo_trace)
    return {"id": row["id"], "created_at": row["created_at"], **payload}


# =========================================================================
# sensors
# =========================================================================

@app.post("/sensors/reading", response_model=SensorReadingOut)
def post_sensor_reading(reading: SensorReadingIn):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO sensor_readings (pool_id, temperature, humidity, timestamp) VALUES (?, ?, ?, ?)",
            (reading.pool_id, reading.temperature, reading.humidity, reading.timestamp),
        )
        conn.commit()
        rid = cur.lastrowid

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
                "SELECT * FROM sensor_readings WHERE pool_id = ? ORDER BY timestamp", (pool_id,)
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
    fpo.db by hand. Resets the autoincrement counters too, so a fresh load
    afterwards gets clean IDs starting from 1."""
    tables = ("sensor_readings", "plan_runs", "farmers", "vehicles", "markets")
    with get_conn() as conn:
        cleared = {}
        for table in tables:
            cleared[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            conn.execute(f"DELETE FROM {table}")
        conn.execute(
            "DELETE FROM sqlite_sequence WHERE name IN (?, ?, ?, ?, ?)", tables
        )
        conn.commit()
    return {"cleared": cleared}
