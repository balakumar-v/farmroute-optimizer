# Backend

FastAPI + Postgres. Local demo: no authentication, no hosted-deployment configuration.

## Setup

Run every command from inside this `backend/` folder. The app imports `database`, `schemas`, `logistics_lib_v2` and the planner modules as plain same-directory modules, not as a package, so starting `uvicorn` from the repository root will not find them.

```bash
docker compose up -d db              # from the repository root; or use any Postgres
cp .env.example .env                 # set DATABASE_URL (the default matches the Docker database)
pip install -r requirements.txt
uvicorn main:app --reload --port 8000 --env-file .env
```

Tables are created on startup. Interactive API docs are at http://localhost:8000/docs. The frontend (`../frontend`) expects the API at `http://localhost:8000` by default.

`python3 verify_setup.py` exercises every endpoint through a FastAPI `TestClient` and needs the database.

## Configuration

Environment variables, normally set in `.env` (see `.env.example`).

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres connection string. Required. |
| `ALLOWED_ORIGINS` | Comma-separated frontend origins for CORS. Default: any origin. |
| `ROUTING_PROVIDER` | Map road geometry: `osrm`, `ors` or `off`. Default `ors` if `ORS_API_KEY` is set, else `osrm`. |
| `ORS_API_KEY` | openrouteservice key (free tier, about 2,000 directions a day). |
| `OSRM_BASE_URL` | Your own OSRM server. The public demo server is non-commercial, rate-limited and has no uptime guarantee. |
| `ROUTING_PROFILE` | `driving-car` or `driving-hgv` (ors), `driving` (osrm). |
| `ROAD_PLANNING` | `off` stops the planner from using road distances. |
| `ROAD_MATRIX_MAX_POINTS` | Largest road matrix to fetch (default 200). Bigger scenarios use a road factor measured on a sample. |
| `FARMROUTE_ROAD_CIRCUITY` | Road-km to straight-km factor used when road distances are off (default 1.0). |

## Endpoints

### `POST /farmers`, `GET /farmers`

`needs_refrigeration` is optional on input; if omitted it is derived from the crop (`CROPS` in `logistics_lib_v2.py`).

```json
// POST /farmers
{"lat": 25.61, "lng": 84.92, "crop": "tomato", "qty_kg": 320,
 "ready_hr": 1.0, "deadline_hr": 9.0}

// 200 response
{"id": 1, "lat": 25.61, "lng": 84.92, "crop": "tomato", "qty_kg": 320,
 "ready_hr": 1.0, "deadline_hr": 9.0, "needs_refrigeration": true}
```

### `POST /vehicles`, `GET /vehicles`

Vehicles are added by type; capacity, refrigeration and costs come from the `VEHICLE_TYPES` table, so a vehicle's type and its attributes cannot drift apart. `count` adds several of the same type in one call. Valid types: `mini_pickup`, `van`, `reefer_van`, `truck_2t`, `reefer_2t`, `truck_5t`, `reefer_5t`.

```json
// POST /vehicles
{"type_name": "reefer_2t", "count": 2}

// 200 response
[{"id": 1, "type_name": "reefer_2t", "capacity_kg": 2000, "refrigerated": true,
  "fixed_cost": 2200, "per_km_cost": 24},
 {"id": 2, "type_name": "reefer_2t", "capacity_kg": 2000, "refrigerated": true,
  "fixed_cost": 2200, "per_km_cost": 24}]
```

### `POST /markets`, `GET /markets`

`price` (Rs/kg) and `capacity_kg` are `{crop: value}` dictionaries. A market must quote every crop that the farmers grow. Valid crops: `tomato`, `onion`, `potato`, `cauliflower`, `mango`, `spinach`.

```json
// POST /markets
{"lat": 25.70, "lng": 85.00,
 "price": {"tomato": 20.5, "potato": 11.0},
 "capacity_kg": {"tomato": 5000, "potato": 5000}}
```

### `POST /plan/compute`

Reads every farmer, vehicle and market in the database, runs ILO and the baselines on them, stores the run and returns all of it, not just the winner. `400` if farmers, vehicles or markets are missing.

| Query parameter | Meaning |
|---|---|
| `mode` | `returns` (default): maximise farmer value. `spoilage`: least spoilage within `max_value_sacrifice` of the returns plan; slower, because it runs the planner several times. |
| `max_value_sacrifice` | Fraction in [0, 1), default 0.10. Only used with `mode=spoilage`. |
| `road_distances` | `true` (default): plan on measured road distances between every farmer and market (OSRM, cached in the database), falling back to straight lines if road data is unavailable. `false`: skip the road lookup. |
| `road_circuity` | Float in [1, 3]: use this fixed road-km to straight-km factor for every distance. Fit one with `calibrate_circuity.py`. |

The response contains `id`, `created_at`, `distance_model` (what the plan was optimized on), then `integrated_logistics_optimization`, `individual_transport` and `proximity_pooling`, each with `pools` and a `summary`, plus `realistic_baselines`:

```json
{
  "id": 1,
  "created_at": "2026-10-20T11:40:00",
  "distance_model": {"type": "road_matrix", "...": "..."},
  "integrated_logistics_optimization": {
    "pools": [
      {"farmer_ids": [1, 8, 0], "vehicle_id": 3, "markets_used": [1, 2],
       "total_qty_kg": 2650.6, "revenue": 32370.6, "transport_cost": 6313.1,
       "spoilage_loss_kg": 803.4, "unsold_kg": 0.0, "net_return": 26057.5,
       "per_farmer_net": {"1": 2441.8, "8": 2655.7}, "breakeven": {"...": "..."}}
    ],
    "summary": {"net_return": 90812.2, "net_return_incl_farmgate": 99000.0, "pct_qty_served": 73.3, "...": "..."}
  },
  "individual_transport": {"pools": ["..."], "summary": {"...": "..."}},
  "proximity_pooling": {"pools": ["..."], "summary": {"...": "..."}},
  "realistic_baselines": {"ilo_meta": {"chosen": "...", "mode": "returns"}, "farmgate_only": {"...": "..."},
                          "self_haul_rational": {"...": "..."}, "neighbour_pooling_rational": {"...": "..."}}
}
```

Notes on reading it:

- Every summary carries `net_return_incl_farmgate`, the number to compare across approaches: produce a plan did not haul is valued at the doorstep price. That price is an assumption (`farmgate_discount` below the median mandi price) and is echoed in every summary.
- `pct_qty_served` always travels with `net_return`; neither should be shown without the other. `unsold_kg` (reached a market, did not sell) and `unserved_no_vehicle_kg` (never got a vehicle) are kept distinct.
- The two shown baselines are the behavioural ones in `baselines_v3.py`; `realistic_baselines` also holds the rational variants, a farm-gate-only reference and the earlier planner's results for reference.
- `realistic_baselines.ilo_meta.chosen` says which plan ILO returned: its own or a baseline's.
- Values in the example above are illustrative.

### `GET /plan/{id}`

A stored run in the shape above, plus `input_snapshot` (the exact farmers, fleet, markets and distance model used). `404` if the id does not exist.

### `GET /plan/{id}/visualization`

The same stored plan reshaped for the map (`visualization_adapter.py`): farmers, vehicles, markets, routes, simulation events and a summary per algorithm, so the frontend never deals with pools, fleets or LP allocation edges. Nothing is recomputed. Routes whose real-road geometry is already cached carry `roadLegs` and `geometry: "road"`; the rest stay straight lines, and `roads.pending` says how many each algorithm still lacks. See the module docstring for which fields are optimizer output and which are labelled derived or reconstructed display data.

### `POST /plan/{id}/roads`

Fetches and caches real-road geometry for one algorithm's routes (`?algo=` and `?budget_s=`, default 15 s, capped at 25). The frontend calls it repeatedly until `pending` reaches 0. Display only: it never touches the optimizer or its numbers.

### `POST /sensors/reading`, `GET /sensors/readings`

```json
{"pool_id": "1:3", "temperature": 6.4, "humidity": 82.0, "timestamp": 3.5}
```

Stores and returns a reading; `GET` lists them (optional `?pool_id=` filter, ordered by `timestamp`; `[]` when nothing has been posted). `pool_id` is a free-form string; `"<plan_run_id>:<vehicle_id>"` is a sensible convention. Readings are stored only: the planner cannot yet recompute spoilage from live sensor data, and nothing is simulated.

### `POST /reset`

Clears every farmer, vehicle, market, plan run and sensor reading and restarts the id counters at 1. The road-geometry cache is deliberately kept, because it is keyed by stop coordinates and stays valid across plans.

## Files

| File | Purpose |
|---|---|
| `main.py` | FastAPI app, all routes, CORS |
| `database.py` | Postgres connection and schema |
| `schemas.py` | Pydantic request and response models |
| `logistics_lib_v2.py` | Data model (`Farmer`, `Vehicle`, `Market`, `CROPS`, `VEHICLE_TYPES`), distances, costs, spoilage |
| `ilo_v3.py` | ILO, the recommended planner: candidates, fleet-aware set partition, repair, value-gain sharing, break-even, discount stress, optional Monte Carlo |
| `ilo_v3_ext.py` | Experimental extensions, off by default (switched on by environment variables) |
| `algorithms_v2.py` | Lower-level building blocks (depots, pools, market LP, dispatch) and the earlier planner |
| `baselines_v3.py` | Behavioural and rational baselines, farm-gate pricing |
| `roads.py` | Road distances for planning and road geometry for the map (OSRM / openrouteservice) |
| `price_impact.py` | Volume-dependent mandi price model and elasticity estimator (off by default) |
| `stress.py` | Monte Carlo replay of a finished plan; `withhold_fragile()` |
| `calibrate_circuity.py` | Fit the road-circuity factor from a CSV of real road distances |
| `integrated_milp.py`, `milp_benchmark.py` | Exact MILP ground truth for small instances |
| `visualization_adapter.py` | Reshapes a stored plan for the map. Pure consumer of planner output |
| `verify_setup.py` | Endpoint smoke test |
| `benchmark_*.py` | ILO against the baselines across scenarios and scales. `benchmark_v2.py` needs `pandas` |
| `tests/` | Planner, baseline, road and adapter tests (no database or internet needed) |
| `experiments_v3_1/`, `experiments_v4/` | Experiment scripts and results (each has a README) |
| `real_data/` | Agmarknet pipeline and regional preset builder (own README) |

## Known simplifications

The planner layer uses distances (measured road km, or straight-line km times a circuity factor), a constant vehicle speed, a flat turnaround buffer and a greedy fleet assignment. This backend stores and serves whatever the planner returns. The full list of limitations is in the repository README.
