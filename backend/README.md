# FPO Decision Layer — Backend

FastAPI + SQLite backend for the farmer-pooling / market-allocation course
project. Local course demo — no auth, no deployment config, no Docker.

## ⚠️ Before you run this: one missing file

This backend was built against `CONTRACT.md`'s verified interface spec, but
the **real `algorithms_v2.py`** (the Algorithm sub-agent's actual
implementation of `run_our_system_v2`, `run_individual_transport_v2`,
`run_proximity_pooling_v2`, and `summarize`) was not part of this delivery —
the file that arrived under that name was actually the dispatch prompt text
for this sub-agent, and `benchmark_v2.py` came through instead of the real
module. Every endpoint below works without it *except* `/plan/compute`,
which will return a `500` with an explanatory message until you:

```bash
cp /path/to/real/algorithms_v2.py backend/algorithms_v2.py
```

(It needs to sit next to `logistics_lib_v2.py` in this folder, since both
are imported by `main.py`.) Everything else in this backend — schema,
endpoints, validation, storage — was written directly from `CONTRACT.md`'s
verified signatures, so no other change should be needed once the real file
is dropped in.

## Setup

```bash
cd backend
pip install -r requirements.txt
python3 verify_setup.py   # sanity-checks every endpoint; safe to run
                           # before or after algorithms_v2.py is added
uvicorn main:app --reload --port 8000
```

Interactive API docs (from FastAPI automatically): `http://localhost:8000/docs`

## Endpoints

### `POST /farmers`, `GET /farmers`
Mirrors the `Farmer` dataclass. `needs_refrigeration` is optional on input —
if omitted, it's derived from the crop (via `CROPS` in `logistics_lib_v2.py`).

```json
// POST /farmers
{"lat": 25.61, "lng": 84.92, "crop": "tomato", "qty_kg": 320,
 "ready_hr": 1.0, "deadline_hr": 9.0}

// 200 response
{"id": 1, "lat": 25.61, "lng": 84.92, "crop": "tomato", "qty_kg": 320,
 "ready_hr": 1.0, "deadline_hr": 9.0, "needs_refrigeration": true}
```

### `POST /vehicles`, `GET /vehicles`
Mirrors `Vehicle`, minus `available_at_hr` (that's per-run mutable state,
rebuilt fresh from these rows on every `/plan/compute` call, not stored).
`capacity_kg`, `refrigerated`, `fixed_cost`, `per_km_cost` are derived from
`type_name` via the same `VEHICLE_TYPES` table `make_fleet()` uses, so a
vehicle's type and its cost/capacity can't drift apart. `count` adds several
of the same type in one call.

```json
// POST /vehicles
{"type_name": "reefer_2t", "count": 2}

// 200 response
[{"id": 1, "type_name": "reefer_2t", "capacity_kg": 2000, "refrigerated": true,
  "fixed_cost": 2200, "per_km_cost": 24},
 {"id": 2, "type_name": "reefer_2t", "capacity_kg": 2000, "refrigerated": true,
  "fixed_cost": 2200, "per_km_cost": 24}]
```

Valid `type_name` values: `mini_pickup`, `van`, `reefer_van`, `truck_2t`,
`reefer_2t`, `truck_5t`, `reefer_5t`.

### `POST /markets`, `GET /markets`
Mirrors `Market`. `price` and `capacity_kg` are `{crop: value}` dicts; keys
must be a subset of the 6 known crops.

```json
// POST /markets
{"lat": 25.70, "lng": 85.00,
 "price": {"tomato": 20.5, "potato": 11.0},
 "capacity_kg": {"tomato": 5000, "potato": 5000}}

// 200 response
{"id": 1, "lat": 25.70, "lng": 85.00,
 "price": {"tomato": 20.5, "potato": 11.0},
 "capacity_kg": {"tomato": 5000, "potato": 5000}}
```

### `POST /plan/compute`
Pulls all farmers/vehicles/markets currently in the DB, runs all three
algorithms following the exact copy/capacity pattern from `CONTRACT.md`
(independent `copy.deepcopy(fleet)` per call; `fresh_capacity(markets)` for
each baseline; no shared mutable state between calls), stores the run, and
returns all three results — not just the winner. `400` if farmers, vehicles,
or markets are empty.

Response shape (fields are the real `pool_result` / `summarize()` fields
from `CONTRACT.md`, not invented ones):

```json
{
  "id": 1,
  "created_at": "2026-09-23T11:40:00",
  "our_system": {
    "pools": [
      {"farmer_ids": [1, 8, 0], "vehicle_id": 3, "markets_used": [1, 2],
       "total_qty_kg": 2650.6, "revenue": 32370.6, "transport_cost": 6313.1,
       "spoilage_loss_kg": 803.4, "unsold_kg": 0.0,
       "unserved_no_vehicle_kg": 0.0, "net_return": 26057.5,
       "per_farmer_net": {"1": 2441.8, "8": 2655.7}, "infeasible": false}
    ],
    "summary": {
      "total_revenue": 115065.4, "total_transport_cost": 24253.2,
      "total_spoilage_kg": 1779.6, "total_unsold_kg": 0.0,
      "total_unserved_no_vehicle_kg": 2411.6, "total_qty_kg": 9039.4,
      "net_return": 90812.2, "net_return_per_farmer": 3027.1,
      "vehicles_used": 3, "vehicle_utilization_pct": 75.0,
      "pools_formed": 8, "pct_qty_served": 73.3
    }
  },
  "individual_transport": { "pools": [...], "summary": {...} },
  "proximity_pooling": { "pools": [...], "summary": {...} }
}
```

`pct_qty_served` is included in every summary alongside `net_return`, per
`CONTRACT.md` — the two are separate axes and neither should be shown
without the other. `unsold_kg` (reached a market, didn't sell) and
`unserved_no_vehicle_kg` (never got a vehicle) are also kept distinct, not
collapsed into one "unsold" number.

### `GET /plan/{id}`
Fetches a stored plan run in the same shape as above, plus `input_snapshot`
(the exact farmers/fleet/markets used for that run).

### `POST /sensors/reading`
```json
{"pool_id": "1:3", "temperature": 6.4, "humidity": 82.0, "timestamp": 3.5}
```
Stores and returns the reading. **Known limitation**: the v2 algorithm does
not yet expose a hook to recompute a plan's spoilage from a live sensor
reading (this was planned but not implemented this round, per the project
brief) — so this endpoint only stores and echoes readings. No spoilage
recalculation logic has been invented here to work around that gap.

`pool_id` is a free-form string: `pool_result` (per `CONTRACT.md`) has no
persistent ID of its own, so there's no single correct convention to enforce
here. `"<plan_run_id>:<vehicle_id>"` is a reasonable one if the frontend/IoT
team wants a suggestion, but that's their call to make, not something this
backend assumes.

## Files

| File | Purpose |
|---|---|
| `main.py` | FastAPI app, all routes |
| `database.py` | sqlite3 connection + schema (`fpo.db`, created on first run) |
| `schemas.py` | Pydantic request/response models |
| `logistics_lib_v2.py` | Real data model (copied as provided — `Farmer`, `Vehicle`, `Market`, `CROPS`, `VEHICLE_TYPES`, `fresh_capacity`, etc.) |
| `algorithms_v2.py` | **Not included — see warning above.** Must be added before `/plan/compute` will work. |
| `verify_setup.py` | Exercises every endpoint via `TestClient`; run after `pip install -r requirements.txt` |

## Known simplifications (inherited, not re-litigated here)

Everything under "Known simplifications" in `CONTRACT.md` (haversine
distance, constant vehicle speed, flat turnaround buffer, no real depot
placement, greedy-heuristic fleet assignment) lives in the algorithm layer,
not this backend — this backend just stores and serves whatever the
algorithm returns.
