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

See README.md for example request/response JSON and the one known gap
(algorithms_v2.py is not bundled with this delivery -- see below).
"""

import copy
import datetime
import json
from typing import List

from fastapi import FastAPI, HTTPException

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

VEHICLE_TYPES_BY_NAME = {t[0]: t for t in VEHICLE_TYPES}

app = FastAPI(title="FPO Decision Layer API", version="0.1.0")


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

    # algorithms_v2.py is NOT bundled with this backend delivery (see
    # README) -- imported lazily here so every other endpoint still works
    # without it, and so the error is a clear 500 instead of a startup crash.
    try:
        from algorithms_v2 import (
            run_our_system_v2,
            run_individual_transport_v2,
            run_proximity_pooling_v2,
            summarize,
        )
    except ImportError as exc:
        raise HTTPException(
            500,
            "algorithms_v2 module is not present in the backend directory. This backend "
            "was built against the CONTRACT.md interface spec, but the real algorithms_v2.py "
            "implementation (from the Algorithm sub-agent) was not part of this delivery -- "
            "copy the actual algorithms_v2.py next to logistics_lib_v2.py in this folder and "
            f"restart the server. (import error: {exc})",
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

    # Exact call pattern from CONTRACT.md: run_our_system_v2 takes no
    # capacity ledger; the two baselines each get their own fresh_capacity()
    # ledger; every call gets its own copy.deepcopy(fleet).
    res_ours = run_our_system_v2(farmers, copy.deepcopy(fleet_template), markets)
    res_ind = run_individual_transport_v2(
        farmers, copy.deepcopy(fleet_template), markets, fresh_capacity(markets)
    )
    res_prox = run_proximity_pooling_v2(
        farmers, copy.deepcopy(fleet_template), markets, fresh_capacity(markets)
    )

    n_farmers, fleet_size = len(farmers), len(fleet_template)
    result_payload = {
        "our_system": {"pools": res_ours, "summary": summarize(res_ours, n_farmers, fleet_size)},
        "individual_transport": {"pools": res_ind, "summary": summarize(res_ind, n_farmers, fleet_size)},
        "proximity_pooling": {"pools": res_prox, "summary": summarize(res_prox, n_farmers, fleet_size)},
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
            "(created_at, input_snapshot, result_our_system, result_individual_transport, result_proximity_pooling) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                created_at,
                json.dumps(input_snapshot),
                json.dumps(result_payload["our_system"]),
                json.dumps(result_payload["individual_transport"]),
                json.dumps(result_payload["proximity_pooling"]),
            ),
        )
        conn.commit()
        plan_id = cur.lastrowid

    return {"id": plan_id, "created_at": created_at, **result_payload}


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
        "our_system": json.loads(row["result_our_system"]),
        "individual_transport": json.loads(row["result_individual_transport"]),
        "proximity_pooling": json.loads(row["result_proximity_pooling"]),
    }


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
