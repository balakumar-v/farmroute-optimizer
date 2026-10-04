# FPO Decision Layer — Backend

FastAPI + SQLite backend for the farmer-pooling / market-allocation course
project. Local course demo — no auth, no deployment config, no Docker.

## Setup

Run every command from inside this `backend/` folder (the app imports
`database`, `schemas`, `logistics_lib_v2`, `algorithms_v2` as plain
same-directory modules, not a package — running `uvicorn` from the
project root, or `python3 main.py` directly, will not find them).

```bash
cd backend
pip install -r requirements.txt
python3 verify_setup.py   # sanity-checks every endpoint; safe to run any time
uvicorn main:app --reload --port 8000
```

Interactive API docs (from FastAPI automatically): `http://localhost:8000/docs`

The frontend (`../frontend/index.html`) expects the API at
`http://localhost:8000` by default — open it after the server above is
running.

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
must be a subset of the 6 known crops. A single market can quote a price and
capacity for several crops at once.

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

Valid crop keys: `tomato`, `onion`, `potato`, `cauliflower`, `mango`, `spinach`.

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
  "integrated_logistics_optimization": {
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

### `GET /plan/{id}/visualization`
Adapter endpoint for the frontend's Map & simulation tab
(`backend/visualization_adapter.py`) — reshapes the same stored plan into a
frontend-facing form: farmers/vehicles/markets/routes/simulation-events per
algorithm, so the frontend never has to know about pools, fleets, or LP
allocation edges. Nothing is recomputed here; it's a pure reshape of what
`/plan/compute` already stored. `404` if `id` doesn't exist.

```json
{
  "id": 1, "created_at": "2026-09-23T11:40:00",
  "solutions": {
    "integrated_logistics_optimization": {
      "algorithm": "integrated_logistics_optimization",
      "farmers": [{"id": 1, "lat": 25.61, "lng": 84.92, "crop": "tomato",
                   "loadKg": 320, "needsRefrigeration": true,
                   "timeWindow": {"start": 1.0, "end": 9.0},
                   "tripId": "trip-0", "served": true}],
      "vehicles": [{"id": 3, "typeName": "reefer_2t", "capacityKg": 2000,
                     "refrigerated": true, "fixedCost": 2200, "perKmCost": 24,
                     "tripIds": ["trip-0"], "used": true,
                     "assignedLoadKgTotal": 1820.0}],
      "markets": [{"id": 1, "lat": 25.70, "lng": 85.00,
                    "price": {"tomato": 20.5}, "capacityKg": {"tomato": 5000},
                    "receivedKg": {"tomato": 1820.0}}],
      "routes": [{"id": "trip-0", "vehicleId": 3, "farmerIds": [1, 8, 0],
                   "marketIds": [1], "stops": [...], "coordinates": [...],
                   "geometry": "straight_line", "distanceKm": 12.4,
                   "distanceIsDerived": true, "totalQtyKg": 1820.0,
                   "revenue": 32370.6, "transportCost": 6313.1,
                   "netReturn": 26057.5, "spoilageLossKg": 803.4,
                   "unsoldKg": 0.0, "marketAllocations": [...]}],
      "unservedFarmerIds": [4, 9],
      "simulationEvents": [{"tripId": "trip-0", "vehicleId": 3,
                              "type": "dispatch", "timestamp": 1.0}, "..."],
      "summary": { "...same summarize() fields as /plan/compute..." },
      "marketBreakdownAvailable": true, "timingModel": "reconstructed",
      "notes": "..."
    },
    "individual_transport": { "...same shape..." },
    "proximity_pooling": { "...same shape..." }
  }
}
```

See the module docstring in `visualization_adapter.py` for exactly which
fields are real optimizer output vs. deliberately-labeled derived/
reconstructed display data (route geometry, distances, timestamps,
per-market breakdowns) — nothing is fabricated, and everything derived is
computed with the same constants/formulas `algorithms_v2.py` itself uses.

`integrated_logistics_optimization`'s `marketAllocations`/`receivedKg` are
only exact when `/plan/compute` was run after the `result_ilo_trace` column
existed (see `database.py`'s migration note) — older stored plans simply
have `marketBreakdownAvailable: false` for that algorithm instead of a
guessed split.

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

### `GET /sensors/readings`
Added alongside the Map & simulation tab's IoT panel — `POST /sensors/reading`
existed with no way to read readings back. Optional `?pool_id=` filters to
one pool's readings (ordered by `timestamp`); omit it to list everything.
Returns `[]`, not fabricated data, when nothing has been posted yet.

```json
// GET /sensors/readings?pool_id=1:3
[{"id": 1, "pool_id": "1:3", "temperature": 6.4, "humidity": 82.0, "timestamp": 3.5}]
```

### `POST /reset`
Clears every farmer, vehicle, market, plan run and sensor reading, and
resets the autoincrement counters so a fresh load afterwards starts IDs
at 1 again. For starting over between demos without deleting `fpo.db`
by hand.

```json
// 200 response
{"cleared": {"sensor_readings": 2, "plan_runs": 1, "farmers": 11,
             "vehicles": 4, "markets": 2}}
```

## Files

| File | Purpose |
|---|---|
| `main.py` | FastAPI app, all routes, CORS |
| `database.py` | sqlite3 connection + schema (`fpo.db`, created on first run — not committed) |
| `schemas.py` | Pydantic request/response models |
| `logistics_lib_v2.py` | Real data model (`Farmer`, `Vehicle`, `Market`, `CROPS`, `VEHICLE_TYPES`, `fresh_capacity`, etc.) |
| `algorithms_v2.py` | The three allocation algorithms (`run_ilo_v2` -- internally `run_our_system_v2` -- `run_individual_transport_v2`, `run_proximity_pooling_v2`, `summarize`) |
| `visualization_adapter.py` | Reshapes a stored plan run into the Map & simulation tab's frontend-facing schema. Pure consumer of the algorithm output — no optimization logic |
| `verify_setup.py` | Exercises every endpoint via `TestClient`; run after `pip install -r requirements.txt` |
| `verify_visualization.py` | Exercises `GET /plan/{id}/visualization` and `GET /sensors/readings` against a realistic multi-vehicle scenario, including multi-trip vehicle-reuse and served/unserved-farmer edge cases |
| `benchmark_v2.py` | Standalone scale/economics benchmark, not used by the API. Needs `pandas` (`pip install pandas`), which isn't in `requirements.txt` since the app itself doesn't need it. Run with `python3 benchmark_v2.py` from this folder. |

`database.py` adds a `result_ilo_trace` column to `plan_runs` (used by
`visualization_adapter.py` for exact per-market breakdowns on the Our
System/ILO algorithm) and runs a one-line `ALTER TABLE ... ADD COLUMN`
migration on startup for any `fpo.db` created before this column existed —
safe to run repeatedly, and the column is nullable so older stored plans
still load fine, just without that one extra breakdown.


## Known simplifications (inherited, not re-litigated here)

Everything under "Known simplifications" in `CONTRACT.md` (haversine
distance, constant vehicle speed, flat turnaround buffer, no real depot
placement, greedy-heuristic fleet assignment) lives in the algorithm layer,
not this backend — this backend just stores and serves whatever the
algorithm returns.
