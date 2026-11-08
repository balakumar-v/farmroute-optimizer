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
    GET  /plan/{plan_id}/fleet-advice | impact | payout | payout/{farmer_id}
         | driver-sheet/{vehicle_id} | diff/{old_plan_id}        POST /plan/{plan_id}/quote-check
    POST /farmers/upload     (csv/xlsx bulk add)
    POST /sensors/reading
    POST /reset
    /farmer/push[/key|/subscribe|/unsubscribe]  (farmer: phone notifications, see push.py)
    GET  /health             (public, no token: liveness + database check; 503 if the database is down)
    GET/DELETE /farmers/phones   DELETE /farmers/{id}/phone   (admin: phone numbers)
    /farmer/phone[/start|/verify]  (farmer: register a number by code)
    POST /farmer/chat   POST /farmer/requests/{id}/confirm|withdraw   GET /farmer/requests   (farmer: change requests)
    GET /change-requests   POST /change-requests/preview|approve   POST /change-requests/{id}/reject
    GET/PUT /change-window                                           (admin: decide change requests)

See README.md for example request/response JSON.
"""

import copy
import dataclasses
import datetime
import json
import os
from typing import Optional, List

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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
    LoginIn, PhoneStartIn, PhoneVerifyIn, PushSubscribeIn, PushUnsubscribeIn, QuoteCheckIn,
    FarmerIn, FarmerOut,
    VehicleIn, VehicleOut,
    MarketIn, MarketOut,
    SensorReadingIn, SensorReadingOut,
)
import advisor
import auth
import change_requests
import chat_llm
import farmer_upload
import notify
import phones
import push
import roads
from change_requests import ApproveIn, ChangeError, ChatIn, IdsIn, RejectIn, WindowIn
from visualization_adapter import ALGO_KEYS, build_plan_visualization

VEHICLE_TYPES_BY_NAME = {t[0]: t for t in VEHICLE_TYPES}

app = FastAPI(title="FPO Decision Layer API", version="0.1.0",
              dependencies=[Depends(auth.admin_guard)])   # default-deny: see auth.py

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
# health
# =========================================================================

@app.get("/health")
def health():
    """Public liveness/readiness probe (exempt from the admin token, see auth.PUBLIC_PATHS).
    200 {"status": "ok"} when the database answers SELECT 1, else 503 {"status": "degraded"}.
    Never echoes the error text: it can contain the connection string."""
    try:
        with get_conn() as conn:
            conn.execute("SELECT 1").fetchone()
        db = "ok"
    except Exception:
        db = "unavailable"
    body = {"status": "ok" if db == "ok" else "degraded", "database": db, "version": app.version,
            "time": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
    return JSONResponse(body, status_code=200 if db == "ok" else 503)


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


@app.post("/farmers/upload")
async def upload_farmers(file: UploadFile = File(...), dry_run: bool = False):
    """Bulk-add farmers from a .csv or .xlsx (columns: lat, lng, crop, qty_kg, ready_hr, deadline_hr, and optional
    needs_refrigeration). All-or-nothing: any invalid row returns 422 with every error and stores nothing.
    dry_run=true validates without storing."""
    data = await file.read(farmer_upload.MAX_BYTES + 1)
    farmers, errors = farmer_upload.parse_farmers(file.filename or "", data)
    if errors:
        raise HTTPException(422, {"message": f"{len(errors)} problem(s) found; nothing was added.", "errors": errors})
    if not dry_run:
        with get_conn() as conn:
            for f in farmers:
                refrig = f.needs_refrigeration if f.needs_refrigeration is not None \
                    else CROPS[f.crop]["needs_refrigeration"]
                conn.execute(
                    "INSERT INTO farmers (lat, lng, crop, qty_kg, ready_hr, deadline_hr, needs_refrigeration) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (f.lat, f.lng, f.crop, f.qty_kg, f.ready_hr, f.deadline_hr, int(refrig)))
            conn.commit()
    return {"farmers": len(farmers), "stored": not dry_run}


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
                       max_value_sacrifice: float = 0.10, farmer_overrides: Optional[dict] = None):
    """`farmer_overrides` ({farmer_id: {column: value}}) plans as if those farmer values were already saved, without
    writing them: used to preview and apply farmer change requests. The farmers table is not touched here."""
    with get_conn() as conn:
        farmer_rows = conn.execute("SELECT * FROM farmers ORDER BY id").fetchall()
        vehicle_rows = conn.execute("SELECT * FROM vehicles ORDER BY id").fetchall()
        market_rows = conn.execute("SELECT * FROM markets ORDER BY id").fetchall()

    if farmer_overrides:
        farmer_rows = [{**r, **farmer_overrides.get(r["id"], {})} for r in farmer_rows]
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
# plan advisors (read-only views over a stored plan; see advisor.py)
# =========================================================================

@app.get("/plan/{plan_id}/fleet-advice")
def plan_fleet_advice(plan_id: int):
    """What one extra vehicle of each class is worth to this plan (the solver's LP shadow value)."""
    plan = get_plan(plan_id)
    ilo_meta = (plan["realistic_baselines"] or {}).get("ilo_meta")
    return advisor.fleet_advice(plan["input_snapshot"], plan["integrated_logistics_optimization"], ilo_meta)


@app.post("/plan/{plan_id}/quote-check")
def plan_quote_check(plan_id: int, body: QuoteCheckIn):
    """A trader's doorstep offer for one farmer vs that farmer's take-home from the planned trip."""
    plan = get_plan(plan_id)
    try:
        return advisor.quote_check(plan, body.farmer_id, body.quote_per_kg)
    except KeyError:
        raise HTTPException(404, f"Farmer {body.farmer_id} is not part of plan {plan_id}.")


@app.get("/plan/{plan_id}/payout")
def plan_payout(plan_id: int):
    """Every farmer's payout statement; the totals add up to the plan's farmer value."""
    return advisor.payout_statements(get_plan(plan_id))


@app.get("/plan/{plan_id}/payout/{farmer_id}")
def plan_farmer_payout(plan_id: int, farmer_id: int):
    out = advisor.payout_statements(get_plan(plan_id))
    st = next((s for s in out["statements"] if s["farmer_id"] == farmer_id), None)
    if st is None:
        raise HTTPException(404, f"Farmer {farmer_id} is not part of plan {plan_id}.")
    return st


@app.get("/plan/{plan_id}/diff/{old_plan_id}")
def plan_diff(plan_id: int, old_plan_id: int):
    """What changed for whom between an older plan and this one (only changed farmers need a message)."""
    return advisor.diff_plans(get_plan(old_plan_id), get_plan(plan_id))


@app.get("/plan/{plan_id}/driver-sheet/{vehicle_id}")
def plan_driver_sheet(plan_id: int, vehicle_id: int):
    """One vehicle's trips in order (stops, planned arrival times, kg to collect, map links) for the driver."""
    plan = get_plan(plan_id)
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM plan_runs WHERE id = %s", (plan_id,)).fetchone()
        solution = _straight_viz_payload(row, conn)["solutions"]["integrated_logistics_optimization"]
    try:
        return advisor.driver_sheet(plan, solution, vehicle_id)
    except KeyError:
        raise HTTPException(404, f"Vehicle {vehicle_id} has no trips in plan {plan_id}.")


@app.get("/plan/{plan_id}/impact")
def plan_impact(plan_id: int):
    """kg moved to mandi, rupees gained vs doing nothing, km and CO2 saved by pooling (assumptions echoed)."""
    plan = get_plan(plan_id)
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM plan_runs WHERE id = %s", (plan_id,)).fetchone()
        routes = _straight_viz_payload(row, conn)["solutions"]["integrated_logistics_optimization"]["routes"]
        with roads.distance_context(conn, plan["input_snapshot"]):
            return advisor.impact(plan, routes)


# =========================================================================
# farmer portal: PINs, publishing, and the farmer's own card (see auth.py)
# =========================================================================

@app.post("/farmers/pins")
def issue_pins(response: Response, only_missing: bool = True):
    """Issue PINs for every farmer (or only those without one). The PINs are returned ONCE here and stored only
    as hashes; hand them out and do not keep the response. Re-issuing replaces the old PIN and logs that farmer out."""
    response.headers["Cache-Control"] = "no-store"
    with get_conn() as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM farmers ORDER BY id").fetchall()]
        have = {r["farmer_id"] for r in conn.execute("SELECT farmer_id FROM farmer_credentials").fetchall()}
        out = [{"farmer_id": fid, "pin": auth.set_pin(conn, fid)} for fid in ids if not (only_missing and fid in have)]
        conn.commit()
    return {"issued": len(out), "pins": out}


@app.post("/farmers/{farmer_id}/pin")
def issue_pin(farmer_id: int, response: Response):
    """A fresh PIN for one farmer (also clears a lockout). Returned once."""
    response.headers["Cache-Control"] = "no-store"
    with get_conn() as conn:
        if conn.execute("SELECT 1 FROM farmers WHERE id = %s", (farmer_id,)).fetchone() is None:
            raise HTTPException(404, f"No farmer with id {farmer_id}")
        pin = auth.set_pin(conn, farmer_id)
        conn.commit()
    return {"farmer_id": farmer_id, "pin": pin}


@app.post("/plan/{plan_id}/publish")
def publish_plan(plan_id: int, background: BackgroundTasks):
    """Make this plan the one farmers see. Cards are built now, once; the previous published plan is kept so each
    farmer's card can say what changed for them. Farmers never see unpublished plans."""
    plan = get_plan(plan_id)
    published_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM plan_runs WHERE id = %s", (plan_id,)).fetchone()
        solution = _straight_viz_payload(row, conn)["solutions"]["integrated_logistics_optimization"]
        cur = conn.execute("SELECT plan_id, previous_plan_id FROM published_plan WHERE id = 1").fetchone()
        prev_id = None if cur is None else (cur["plan_id"] if cur["plan_id"] != plan_id else cur["previous_plan_id"])
        prev_plan = None
        if prev_id is not None:
            try:
                prev_plan = get_plan(prev_id)
            except HTTPException:
                prev_id = None
        cards = advisor.farmer_cards(plan, solution, published_at, prev_plan, os.environ.get("FPO_PHONE") or None)
        conn.execute(
            "INSERT INTO published_plan (id, plan_id, previous_plan_id, published_at, cards) VALUES (1, %s, %s, %s, %s) "
            "ON CONFLICT (id) DO UPDATE SET plan_id = EXCLUDED.plan_id, previous_plan_id = EXCLUDED.previous_plan_id, "
            "published_at = EXCLUDED.published_at, cards = EXCLUDED.cards",
            (plan_id, prev_id, published_at, json.dumps(cards)))
        have = {r["farmer_id"] for r in conn.execute("SELECT farmer_id FROM farmer_credentials").fetchall()}
        conn.commit()
    # SMS / WhatsApp: farmers with a verified number whose card changed (everyone with a number when nothing was
    # published before). Sent after this response, so a slow or failing provider never holds up or breaks publishing.
    targets = phones.plan_targets(cards, only_changed=cur is not None)
    background.add_task(phones.send_batch, targets, plan_id)
    # Web Push to the farmers' phones: same rule (changed cards only), same background task treatment.
    push_targets = push.plan_targets(cards, only_changed=cur is not None)
    background.add_task(push.send_batch, push_targets, plan_id)
    prov = notify.describe_providers()
    return {"plan_id": plan_id, "previous_plan_id": prev_id, "published_at": published_at, "farmers": len(cards),
            "farmers_without_pin": sorted(set(cards) - have),
            "farmers_with_changes": sum(1 for c in cards.values() if c["changed"]),
            "phone_updates": {"farmers_messaged": len(targets), "sms": prov["sms"]["provider"],
                              "whatsapp": prov["whatsapp"]["provider"],
                              "dry_run": not (prov["sms"]["live"] or prov["whatsapp"]["live"])},
            "push_updates": {"enabled": push.enabled(), "devices_notified": len(push_targets)}}


@app.get("/published")
def get_published():
    with get_conn() as conn:
        r = conn.execute("SELECT plan_id, previous_plan_id, published_at, cards FROM published_plan WHERE id = 1").fetchone()
    if r is None:
        return {"published": False}
    return {"published": True, "plan_id": r["plan_id"], "previous_plan_id": r["previous_plan_id"],
            "published_at": r["published_at"], "farmers": len(json.loads(r["cards"]))}


@app.get("/published/cards")
def get_published_cards(response: Response):
    """Every published farmer card, for the admin console's printable cards (farmers without a phone). Admin-only
    like the rest of the admin routes; farmers never reach it (they only get their own card from /farmer/me).
    Cards hold no PINs."""
    response.headers["Cache-Control"] = "no-store"
    with get_conn() as conn:
        r = conn.execute("SELECT plan_id, published_at, cards FROM published_plan WHERE id = 1").fetchone()
    if r is None:
        raise HTTPException(404, "No plan has been published yet.")
    cards = json.loads(r["cards"])
    return {"plan_id": r["plan_id"], "published_at": r["published_at"],
            "cards": [cards[k] for k in sorted(cards, key=int)]}


@app.delete("/published")
def unpublish():
    with get_conn() as conn:
        conn.execute("DELETE FROM published_plan WHERE id = 1")
        conn.commit()
    return {"published": False}


@app.post("/farmer/login")
def farmer_login(body: LoginIn):
    token = auth.login(body.farmer_id, body.pin)
    return {"token": token, "token_type": "bearer", "expires_in": auth.TOKEN_TTL_S}


@app.get("/farmer/me")
def farmer_me(response: Response, farmer_id: int = Depends(auth.current_farmer)):
    """The logged-in farmer's own card from the published plan. There is deliberately no id parameter: the id
    comes only from the verified token."""
    response.headers["Cache-Control"] = "private, no-cache"
    with get_conn() as conn:
        r = conn.execute("SELECT cards FROM published_plan WHERE id = 1").fetchone()
    if r is None:
        raise HTTPException(404, "No plan has been published yet.")
    card = json.loads(r["cards"]).get(str(farmer_id))
    if card is None:
        raise HTTPException(404, "You are not part of the published plan.")
    card["phone"] = phones.status(farmer_id)       # lets the app ask for a number only when there is none
    return card


@app.get("/farmer/push/key")
def farmer_push_key():
    """The public VAPID key the browser needs to subscribe. Not secret; no login needed. enabled=false: keys not set."""
    return {"enabled": push.enabled(), "public_key": push.public_key() or None}


@app.get("/farmer/push")
def farmer_push_status(response: Response, farmer_id: int = Depends(auth.current_farmer)):
    response.headers["Cache-Control"] = "no-store"
    return push.status(farmer_id)


@app.post("/farmer/push/subscribe")
def farmer_push_subscribe(body: PushSubscribeIn, farmer_id: int = Depends(auth.current_farmer)):
    return push.subscribe(farmer_id, body.subscription, body.lang)


@app.post("/farmer/push/unsubscribe")
def farmer_push_unsubscribe(body: PushUnsubscribeIn, farmer_id: int = Depends(auth.current_farmer)):
    return push.unsubscribe(farmer_id, body.endpoint)


@app.get("/farmer/phone")
def farmer_phone(response: Response, farmer_id: int = Depends(auth.current_farmer)):
    response.headers["Cache-Control"] = "no-store"
    return phones.status(farmer_id)


@app.post("/farmer/phone/start")
def farmer_phone_start(body: PhoneStartIn, response: Response, farmer_id: int = Depends(auth.current_farmer)):
    """Texts a 6-digit code to the number. Nothing is stored against the farmer until /farmer/phone/verify."""
    response.headers["Cache-Control"] = "no-store"
    return phones.start(farmer_id, body.phone, body.lang)


@app.post("/farmer/phone/verify")
def farmer_phone_verify(body: PhoneVerifyIn, background: BackgroundTasks, response: Response,
                        farmer_id: int = Depends(auth.current_farmer)):
    """Stores the number if the code is right, then sends the farmer their current plan once."""
    response.headers["Cache-Control"] = "no-store"
    st = phones.verify(farmer_id, body.code)
    background.add_task(phones.send_welcome, farmer_id)
    return st


@app.delete("/farmer/phone")
def farmer_phone_remove(response: Response, farmer_id: int = Depends(auth.current_farmer)):
    """The farmer stops SMS / WhatsApp updates: their number is deleted."""
    response.headers["Cache-Control"] = "no-store"
    phones.remove(farmer_id)
    return phones.status(farmer_id)


# ---- admin side of phone numbers (not under /farmer/, so the admin token is required)
@app.get("/farmers/phones")
def admin_phones(response: Response):
    """Who has a number (masked), how sending is configured, the last messages. Full numbers are never returned."""
    response.headers["Cache-Control"] = "no-store"
    return phones.summary()


@app.delete("/farmers/phones")
def admin_reset_phones(confirm: bool = False):
    """Clears EVERY stored phone number. Farmers are asked for theirs again the next time they open the app.
    Needs ?confirm=true so a stray request cannot do it."""
    if not confirm:
        raise HTTPException(400, "Add ?confirm=true to clear every stored phone number.")
    return {"cleared": phones.reset_all()}


@app.delete("/farmers/{farmer_id}/phone")
def admin_clear_phone(farmer_id: int):
    return {"cleared": phones.remove(farmer_id)}


# =========================================================================
# farmer change requests (see change_requests.py): chat in, admin decides, plan recomputed
# =========================================================================

@app.exception_handler(change_requests.RequestNotFound)
def _request_not_found(request: Request, exc: change_requests.RequestNotFound):
    msg = exc.args[0] if exc.args and isinstance(exc.args[0], str) else "No such request."
    return JSONResponse({"detail": msg}, status_code=404)


@app.exception_handler(change_requests.RequestConflict)
def _request_conflict(request: Request, exc: change_requests.RequestConflict):
    return JSONResponse({"detail": str(exc)}, status_code=409)


@app.post("/farmer/chat")
def farmer_chat(body: ChatIn, farmer_id: int = Depends(auth.current_farmer)):
    """The farmer's message (or the form fallback) -> what we understood, to confirm. Always one of `status`:
    confirm (a draft was saved: show `changes`, then POST /farmer/requests/{request_id}/confirm), clarify (the
    LLM needs one more fact), invalid (the numbers do not make a sensible plan), llm_unavailable (use the form).
    The farmer id is the token's, never the body's or the LLM's. Nothing here changes any plan."""
    with get_conn() as conn:
        if not change_requests.window_open(conn):
            raise HTTPException(409, "Changes are closed right now. Please call your FPO.")
        if change_requests.published_plan_id(conn) is None:
            raise HTTPException(409, "No plan has been published yet, so there is nothing to change.")
        current = change_requests.fetch_current(conn, farmer_id)
    if current is None:
        raise HTTPException(404, "You are not part of this plan.")
    if not change_requests.rate_limit_ok(farmer_id):
        raise HTTPException(429, "Too many messages. Please wait a while, or call your FPO.",
                            headers={"Retry-After": "3600"})
    if body.structured is not None:
        parse, raw = body.structured, "[form]"
    else:
        try:
            parse, raw = chat_llm.parse_message(body.message, current), body.message
        except chat_llm.LLMUnavailable:
            return {"status": "llm_unavailable",
                    "message": "I could not read that right now. Please use the form instead."}
    if not parse.changes:
        return {"status": "clarify", "code": "llm" if parse.clarify else "empty", "message": parse.clarify or
                "I can only help change your quantity, ready time or deadline. What would you like to change?"}
    try:
        proposed = change_requests.resolve(parse, current)
    except ChangeError as e:
        return {"status": "invalid", "code": e.code, "params": e.params, "message": str(e)}
    with get_conn() as conn:
        request_id = change_requests.create_draft(conn, farmer_id, raw, parse, current, proposed)
        conn.commit()
    return {"status": "confirm", "request_id": request_id, "changes": change_requests.change_lines(current, proposed),
            "summary": change_requests.summary(current, proposed)}


@app.post("/farmer/requests/{request_id}/confirm")
def farmer_confirm_request(request_id: int, farmer_id: int = Depends(auth.current_farmer)):
    with get_conn() as conn:
        if not change_requests.window_open(conn):
            raise HTTPException(409, "Changes are closed right now. Please call your FPO.")
        out = change_requests.confirm(conn, farmer_id, request_id)
        conn.commit()
    return out


@app.post("/farmer/requests/{request_id}/withdraw")
def farmer_withdraw_request(request_id: int, farmer_id: int = Depends(auth.current_farmer)):
    with get_conn() as conn:
        out = change_requests.withdraw(conn, farmer_id, request_id)
        conn.commit()
    return out


@app.get("/farmer/requests")
def farmer_requests(response: Response, farmer_id: int = Depends(auth.current_farmer)):
    """This farmer's own latest requests and where each stands."""
    response.headers["Cache-Control"] = "private, no-cache"
    with get_conn() as conn:
        out = change_requests.list_for_farmer(conn, farmer_id)
        conn.commit()
    return {"requests": out}


def _replan_options(plan: dict) -> dict:
    """compute options that plan the way `plan` was planned (mode, and how distance was measured), so a preview
    differs from the published plan only by the farmer change, not by a different setting."""
    meta = (plan.get("realistic_baselines") or {}).get("ilo_meta") or {}
    model = (plan.get("input_snapshot") or {}).get("distance_model") or {}
    opts = {"mode": meta["mode"] if meta.get("mode") in ("returns", "spoilage") else "returns"}
    if isinstance(meta.get("max_value_sacrifice"), (int, float)):
        opts["max_value_sacrifice"] = meta["max_value_sacrifice"]
    if model.get("type") == "circuity" and model.get("source") == "manual":
        opts["road_circuity"] = model["k"]
    elif "switched off" in (model.get("note") or ""):
        opts["road_distances"] = False
    return opts


def _published_id_or_409(conn) -> int:
    pid = change_requests.published_plan_id(conn)
    if pid is None:
        raise HTTPException(409, "No plan has been published yet.")
    return pid


@app.get("/change-requests")
def list_change_requests(status: str = "pending"):
    if status not in change_requests.STATUSES:
        raise HTTPException(400, f"status must be one of {list(change_requests.STATUSES)}")
    with get_conn() as conn:
        out = change_requests.list_by_status(conn, status)
        info = {"window_open": change_requests.window_open(conn),
                "published_plan_id": change_requests.published_plan_id(conn)}
        conn.commit()
    return {"requests": out, **info}


@app.post("/change-requests/preview")
def preview_change_requests(body: IdsIn):
    """What the published plan would become if these requests were approved. Computes a new, unpublished plan with
    the farmers' new values applied in memory; no farmer row and no published plan changes. `collateral` lists
    farmers who did not ask for anything but are moved anyway."""
    with get_conn() as conn:
        rows = change_requests.load_pending(conn, body.ids)
        base_id = _published_id_or_409(conn)
    base = get_plan(base_id)
    overrides = change_requests.overrides_of(rows)
    plan = _compute_plan_impl(**_replan_options(base), farmer_overrides=overrides)
    diff = advisor.diff_plans(base, get_plan(plan["id"]))
    collateral = [c for c in diff["changed"] if c["farmer_id"] not in overrides]
    return {"base_plan_id": base_id, "preview_plan_id": plan["id"], "requested_farmer_ids": sorted(overrides),
            "diff": diff, "collateral_count": len(collateral)}


@app.post("/change-requests/approve")
def approve_change_requests(body: ApproveIn, background: BackgroundTasks):
    """Approve one or several requests with one recompute and one publish. Refused (409) if the published plan is
    no longer `base_plan_id`. Order: compute with the new values, then in one transaction save them and mark the
    requests approved, then publish (which messages only the farmers whose card changed). If publish fails after
    the save, publishing the returned plan_id again finishes the job."""
    with get_conn() as conn:
        rows = change_requests.load_pending(conn, body.ids)
        if _published_id_or_409(conn) != body.base_plan_id:
            raise change_requests.RequestConflict(
                "The published plan changed since you previewed. Preview again before approving.")
    base = get_plan(body.base_plan_id)
    plan = _compute_plan_impl(**_replan_options(base), farmer_overrides=change_requests.overrides_of(rows))
    with get_conn() as conn:
        change_requests.apply_approved(conn, rows, plan["id"], body.base_plan_id)
        conn.commit()
    published = publish_plan(plan["id"], background)
    diff = advisor.diff_plans(base, get_plan(plan["id"]))
    return {"approved": sorted(r["id"] for r in rows), "plan_id": plan["id"], "published": published,
            "farmers_changed": diff["farmers_changed"]}


@app.post("/change-requests/{request_id}/reject")
def reject_change_request(request_id: int, body: RejectIn):
    with get_conn() as conn:
        change_requests.reject(conn, request_id, body.reason_code)
        conn.commit()
    return {"id": request_id, "status": "rejected", "reason_code": body.reason_code}


@app.get("/change-window")
def get_change_window():
    with get_conn() as conn:
        return {"is_open": change_requests.window_open(conn)}


@app.put("/change-window")
def put_change_window(body: WindowIn):
    with get_conn() as conn:
        change_requests.set_window(conn, body.is_open)
        conn.commit()
    return {"is_open": body.is_open}


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
    tables = ("sensor_readings", "plan_runs", "farmers", "vehicles", "markets",
              "farmer_credentials", "published_plan", "farmer_phones", "phone_otps", "notification_log", "push_subscriptions",
              "change_requests", "change_window")
    with get_conn() as conn:
        cleared = {}
        for table in tables:
            cleared[table] = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        conn.execute(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY")
        conn.commit()
    return {"cleared": cleared}
