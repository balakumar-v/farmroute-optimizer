# Farmroute Optimizer

A decision layer for farmer produce pooling and market allocation. Small farmers each need a truck and a market; this system decides who rides together, on which vehicle, to which mandi (wholesale produce market), and what each farmer ends up with. Then it explains every decision on a map.

It is a prototype on synthetic farmers and dated real mandi data, not a production system. [What is real and what is not](#what-is-real-and-what-is-not) says exactly where the line is.

## The problem

A smallholder farmer with a few hundred kilos usually sells at the farm gate to a trader, at a discount, because hauling one small lot to a distant mandi does not pay. Pooling lots on shared trucks could change that, but only if someone checks the arithmetic: truck cost including the empty return leg, spoilage in transit, pickup windows, mandi capacity, and whether the trader's doorstep price is already good enough. Farmroute is that decision layer for the coordinator of a farmer producer organisation (FPO).

## What it decides

Given farmers (location, crop, quantity, ready and deadline hours, refrigeration need), a vehicle fleet, and markets (price and capacity per crop), the optimizer returns a plan: which farmers pool onto which trips, which trips are worth running at all, and where each load sells.

Two numbers have to be read together:

- **Farmer value (₹)**: net return of the trips that run (revenue minus transport cost), plus the farm-gate value of the produce the plan did not haul. Farm-gate means selling at the doorstep to a trader. Counting it matters because a farmer who sells at the doorstep would otherwise score zero.
- **Produce sold (%)**: the share of the harvest that reached a mandi.

The farm-gate price is an assumption, not data: 20% below the median mandi price for that crop. The UI says so wherever the number appears.

## Headline result

Bihar preset (real mandi prices, 34 synthetic farmers, 8 vehicles, 8 mandis), default 20% farm-gate discount:

| Approach | Farmer value | Sold at a market |
|---|---|---|
| **ILO** (ours) | ₹208,586 | 64.5% |
| Proximity Pooling (behavioural baseline) | ₹146,705 | 10.5% |
| Individual Transport (behavioural baseline) | ₹135,417 | 10.5% |

The two behavioural baselines model what farmers do without a planner, so they are the natural comparison but also the easiest to beat. Against the strongest baseline in the project (rational neighbour pooling, exact economics, returned by the API under `realistic_baselines` but not shown in the UI) ILO leads by **24.3%** at the default discount. The lead depends on the assumed farm-gate discount: against the best baseline it is 12% at a 5% discount and 54% at 40%. A stronger rational baseline that picks the best mandi per farmer or group still trails ILO by about 15% at the default (`docs/ALGORITHM_AND_RESULTS.md`, section 20).

Not every scenario is a win. On the synthetic Cold chain scenario ILO and Proximity Pooling tie (₹56,190 against ₹56,113): with spoilage counted from pickup, the refrigeration effect is small at those distances, and the scenario's blurb says so. All of these are single runs on synthetic farmers.

These benchmark figures use the library's default straight-line distances. The API plans on measured road distances by default (see below), so a run in the app can differ from the table.

## Quick start

Needs Python 3.10+ (developed on 3.12), Node 18+, and a Postgres database. Docker is the easiest way to get one; a hosted Postgres such as Neon works too.

```bash
# 1. database (skip if you use a hosted Postgres)
docker compose up -d db

# 2. backend: run from inside backend/
cd backend
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # already points at the Docker database
uvicorn main:app --reload --port 8000 --env-file .env

# 3. frontend: second terminal, from frontend/
cd frontend
npm install
npm run dev
```

Open http://localhost:5173, pick a scenario on the first screen and press Run. It loads the data, computes the plan and opens the map. Interactive API docs are at http://localhost:8000/docs. The backend URL defaults to `http://localhost:8000` and can be changed from the connection chip in the top-right of the page.

- Tables are created on startup; there is nothing to migrate by hand.
- To use a hosted database, set `DATABASE_URL` in `backend/.env` (Neon needs `?sslmode=require` on the URL).
- Planning and the map fetch road data from a public OSRM server, so they need internet. Without it the planner falls back to straight-line distances and the map still renders on a plain background.
- A large scenario takes a few seconds to compute. The first run of a scenario also fetches road distances, which are then cached.

## The app

| Tab | What it shows |
|---|---|
| Scenarios | Eight ready-made scenarios. One click loads the data, computes the plan and opens the map. |
| Data | The farmers, vehicles and markets the optimizer sees. Add rows by hand. |
| Plan | The ILO plan as a ledger: net return, produce not hauled and sold at the farm gate, farmer value, harvest sold, spoilage, and one row per pool. An "Optimise for" selector switches between farmer value and least spoilage. If ILO found nothing better than a simpler plan, the page says which plan it recommends instead. |
| Compare | ILO against the two behavioural baselines: farmer value and produce sold side by side, a delta against ILO, and a full breakdown table. |
| Map | The plan on a map: 7 presentation stages, a playable timeline, a step-by-step story, details for anything you select, compare mode, 3D, chase camera, and a full-screen walkthrough. Farmers who sell at the farm gate are slate; farmers who wanted a truck and got none are red. |

### Scenarios

Three synthetic scenarios, each built to isolate one mechanism, and five built on real mandi data.

| Scenario | Farmers / vehicles / mandis | What it isolates |
|---|---|---|
| 1. Cold chain | 11 / 4 / 2 | One reefer (refrigerated truck) against plain trucks. A mechanism demo, not a win. |
| 2. Market allocation | 10 / 4 / 3 | Price and capacity differences between mandis |
| 3. Fleet scarcity | 15 / 3 / 2 | Few trucks and clashing pickup windows |
| Bihar, Dec 2025 to Feb 2026 | 34 / 8 / 8 | Potato and onion; the farmers' own district |
| Karnataka, around Bengaluru, Feb to Apr 2026 | 61 / 16 / 8 | Tomato, onion, potato, cauliflower, mango |
| Uttar Pradesh, around Aligarh, Nov 2025 to Jan 2026 | 59 / 15 / 8 | Potato, onion, tomato, cauliflower, spinach |
| Maharashtra, around Junnar (Pune), Feb to Apr 2026 | 60 / 14 / 8 | Onion, tomato, potato, cauliflower, spinach |
| Madhya Pradesh, around Indore, Feb to Apr 2026 | 57 / 13 / 11 | Onion, potato, tomato, cauliflower |

In the real-data scenarios the mandi locations, prices and daily arrivals come from Agmarknet via the India Data Portal. The farmers and the fleet are synthetic, because no farmer-level data exists. Each scenario's "About the data" note lists what was cleaned and which counts are assumptions.

## How the optimizer works

ILO (Integrated Logistics Optimization) lives in `backend/ilo_v3.py` and is the plan the UI recommends. Its goal is one number: farmer value, with the same prices and accounting for every approach. The empty return leg is charged and spoilage runs from pickup.

1. **Honest objective.** Dispatch a trip only if it beats the farm-gate value of its members, not merely if its net return is above zero.
2. **Pool consolidation.** For each (mandi, crop) pair, a Clarke-Wright savings pass (a classic route-merging heuristic) merges farmers heading to the same mandi into full trucks.
3. **Set partitioning.** Candidate trips (single farmers, ILO's own pools, neighbour groups, merged routes) go into an exact 0/1 program, solved with SciPy's HiGHS, that picks disjoint trips maximising total gain, with mandi capacity as a constraint. Each candidate becomes columns of (trip, vehicle class, start slot), and the program also limits how many vehicles of each class are busy in any 15-minute cell, so it chooses vehicles as well as trips. Market allocation (an LP) and economic dispatch then run on those pools.
4. **Safeguard.** ILO returns the best of its own plans and every baseline under the same accounting, and records which one it chose (`ilo_meta.chosen`). The fleet-blind plan competes too, so the final value cannot drop.
5. **Farmer-level no-loss.** Surplus from each trip is shared so every farmer gets at least their own farm-gate value. This value-gain split is what `per_farmer_net` reports.

`backend/algorithms_v2.py` supplies the lower-level pieces: k-means depots, DBSCAN pools, the market LP and dispatch. For small instances an exact MILP gives a ground truth (`backend/integrated_milp.py`, `docs/MILP_GROUND_TRUTH.md`).

### Distances

By default `POST /plan/compute` plans on measured road distances: for every farmer and market pair it asks an OSRM table service for the road km (cached in the database), and every planner distance follows it. Each plan stores which distance model it used, so the map replays exactly what the optimizer saw. Alternatives: `road_distances=false` for straight lines, or `road_circuity=k` for a fixed road-km to straight-km factor (fit one with `backend/calibrate_circuity.py`). Only road distance and geometry are used; the provider's travel times are ignored and the plan's own constant-speed model (32 km/h) runs the clock, because OpenStreetMap speed tags are patchy in India.

### Options

Every dispatched trip carries `breakeven`: the doorstep Rs/kg per crop below which hauling still pays, its cushion in percent, and the smallest true discount at which it pays. The intended operating rule is to dispatch only if the trader's live quote is below that price.

| Option | What it does | Default |
|---|---|---|
| `mode=spoilage` (`max_value_sacrifice`) | Least produce spoiled in transit among plans within a value budget of the normal plan. Runs the planner several times, so it is slower. | `mode=returns` |
| `price_impact`, `true_price_impact`, `markets_per_trip` | Volume-dependent mandi prices (`backend/price_impact.py`); belief drives the MILP, truth drives simulation and scoring | off |
| `stress_discounts` | Re-value the plan at other true farm-gate discounts (5/10/20/30/35%); adds `meta["discount_stress"]` | on |
| `mc_draws`, `mc_min_prob`, `mc_kwargs` | Monte Carlo replay of the finished plan (`backend/stress.py`); optionally withhold fragile trips | off |

### What the experiments showed

Synthetic scenarios, a few seeds each; `docs/ALGORITHM_AND_RESULTS.md` sections 22 to 25 have the tables and caveats.

- **Road distance matters.** Planning with straight-line distances when roads are 1.4x longer cost about 17% of the gain and left 15 of 65 trips below the farm-gate price; planning with the right factor cut that to 2 of 58. Underestimating the factor by 0.2 costs about 2%, overestimating by 0.2 costs about 14%.
- **Fleet-aware planning** adds 0 to 2.5% of final value, small because the synthetic fleet is small relative to the farmers. It also prices vehicles: one extra reefer was worth about ₹4.7k in one scenario.
- **Price response.** With elasticities estimated from the Agmarknet files (lower bounds), scoring with price response cuts reported gain by about 17%. Planning with it adds nothing measurable at those elasticities and about 7% when the true response is 3.5x stronger. Wrong beliefs hurt.
- **Farm-gate discount.** Assuming 20% to 30% and using the live-quote rule had a worst-case regret of 8% to 11% across true discounts of 5% to 35%.
- **Mandi capacity is the lever.** It binds in 3 of 5 presets and tripling it adds 15% to 39%, so report capacity sensitivity with any gain. Multi-mandi trips are not worth building; mixed-crop trips add about 0 to 5% and are noisy.
- **Spoilage.** ILO beat every baseline under every spoilage variant tried (lead 4% to 9%), but doubling the hourly spoilage rate cut the gain by 25%. The per-crop hourly rates are the parameter worth measuring.
- **Robustness.** In a Monte Carlo replay (travel ±20%, readiness delays up to about 1 h, prices ±8%) the plan kept about 88% of its nominal gain on average and about 49% in the worst 5% of draws, and never lost money overall.

The guarantee is narrow: returned value is at least the best baseline, measured with the prices and accounting the planner was given. It says nothing about real farmers, and it is only as good as the farm-gate price input.

### Baselines

The two shown in the UI model what farmers do without a planner (`backend/baselines_v3.py`). Nobody checks the arithmetic, so some trips lose money and some profitable ones are skipped.

- **Individual Transport:** a farmer hires a spot truck to the nearest buying mandi if it is within 40 km and its posted price beats the trader's offer by 10%. Otherwise they sell at the farm gate.
- **Proximity Pooling:** the same rule for groups of up to 4 neighbours within 5 km sharing one truck. The group waits for its last member, and a pickup after anyone's deadline is a no-show.

Spot trucks cost 1.15 times the usual rate, arrive one hour after the request, and are not the FPO's own fleet. The 40 km, 10%, 5 km, 1.15x and 1 h values are assumptions held in one `Behaviour` dataclass.

## What is real and what is not

- **Real:** mandi coordinates (the portal's own, never geocoded or invented), prices and reported daily arrivals; road distances and route geometry from OpenStreetMap routing.
- **Synthetic:** every farmer, lot size, ready time and the fleet. Farmer counts (about 60 pickups per regional preset, a typical collection round for one FPO) and vehicle sizes are modelling choices.
- **Assumed:** the farm-gate price (20% under the median mandi price), the baseline behaviour parameters, spoilage rates, and mandi capacity. Capacity is the median reported daily arrival; where one value repeats on over 70% of days it is a reporting default, so it is raised to the lower quartile of that state's other mandis for the crop (never lowered).
- **Dropped, not guessed:** mandis with no coordinates (Maharashtra 5, Madhya Pradesh 27), implausible price or arrival units, and mandi-crop series absorbing under 1 t per day.
- **Reconstructed:** per-stop times are rebuilt with the algorithm's own timing constants, not replayed from its internals.
- **Stored only:** ESP32 temperature and humidity readings. The planner cannot yet recompute spoilage from live readings, and the UI never simulates sensor data.

## Repository layout

```
backend/
  main.py                    FastAPI app and endpoints
  ilo_v3.py                  ILO, the recommended planner
  algorithms_v2.py           lower-level building blocks and the earlier planner
  baselines_v3.py            behavioural and rational baselines, farm-gate pricing
  roads.py                   OSRM/ORS road distances (planning) and road geometry (map)
  price_impact.py            volume-dependent mandi price model (off by default)
  stress.py                  Monte Carlo replay of a finished plan
  calibrate_circuity.py      fit the road-circuity factor from real road distances
  logistics_lib_v2.py        data model: 6 crops, 7 vehicle types, costs, spoilage
  visualization_adapter.py   reshapes a stored plan for the map (no recomputation)
  integrated_milp.py         exact MILP ground truth for small instances
  database.py, schemas.py    Postgres access and request/response models
  verify_setup.py            endpoint smoke test
  benchmark_*.py             ILO against every baseline, scale and comparison runs
  tests/                     planner, baseline, road and adapter tests
  experiments_v3_1/          scripts behind the sensitivity results (own README)
  experiments_v4/            planner-variant study and its results (own README)
  real_data/                 Agmarknet pipeline, regional preset builder, data (own README)
frontend/                    React + TypeScript + Vite app (own README)
docs/
  ALGORITHM_AND_RESULTS.md   design history, benchmarks, assumptions
  MILP_GROUND_TRUTH.md       exact-benchmark method and results
  PRODUCT.md, DESIGN.md      who the UI is for, and its design system
  CHANGELOG.md
docker-compose.yml           local Postgres
.github/workflows/ci.yml     backend tests, frontend typecheck, tests and build
```

## API

Full request and response shapes are in [`backend/README.md`](backend/README.md) and at `/docs` on a running server.

| Endpoint | Purpose |
|---|---|
| `POST /farmers`, `GET /farmers` | Add and list farmers |
| `POST /vehicles`, `GET /vehicles` | Add vehicles by type and count |
| `POST /markets`, `GET /markets` | Add markets (per-crop price and capacity) |
| `POST /plan/compute` | Run ILO and the baselines on the current data and store the run. Query: `mode`, `max_value_sacrifice`, `road_distances`, `road_circuity` |
| `GET /plan/{id}` | A stored run, with its input snapshot |
| `GET /plan/{id}/visualization` | The same run reshaped for the map |
| `POST /plan/{id}/roads` | Fetch and cache real-road geometry for a stored plan's routes (display only) |
| `POST /sensors/reading`, `GET /sensors/readings` | Store and list ESP32 temperature and humidity readings |
| `POST /reset` | Clear all data |

Crops: `tomato`, `onion`, `potato`, `cauliflower`, `mango`, `spinach`. Vehicle types: `mini_pickup`, `van`, `reefer_van`, `truck_2t`, `reefer_2t`, `truck_5t`, `reefer_5t`. There is no authentication; this is a local demo.

### Configuration

All optional except `DATABASE_URL`. Backend settings go in `backend/.env` (see `backend/.env.example`).

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres connection string |
| `ALLOWED_ORIGINS` | Comma-separated frontend origins for CORS (default: any) |
| `ROUTING_PROVIDER` | `osrm`, `ors` or `off` for map road geometry (default `ors` if `ORS_API_KEY` is set, else `osrm`) |
| `OSRM_BASE_URL` | Your own OSRM server instead of the public demo server |
| `ROAD_PLANNING` | `off` to stop planning on road distances |
| `FARMROUTE_ROAD_CIRCUITY` | Fixed road-km to straight-km factor used when road distances are off |
| `VITE_API_BASE` | Frontend build-time backend URL |

## Tests and benchmarks

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest tests real_data/tests -q        # no database or internet needed
python verify_setup.py                           # endpoint smoke test; needs the database

python benchmark_ilo_v3.py grid                  # win/tie/loss map across scenarios
python benchmark_ilo_v3.py robust                # planner assumes 20% discount, truth differs
python benchmark_ilo_v3.py bihar                 # the Bihar preset

cd ../frontend
npm test                                         # simulation-engine tests
npm run build                                    # typecheck and production build
```

The CI workflow runs the backend tests and the frontend typecheck, tests and build on every push.

## Real-data pipeline

The India Data Portal's Agmarknet export is a bulk CSV you download by hand (the Agmarknet site itself is captcha-protected, and this project does not bypass it). The repo includes the five state CSVs used here under `backend/real_data/data/raw/`, about 15 MB in all.

```bash
cd backend
python3 real_data/build_regional_presets.py --list
python3 real_data/build_regional_presets.py --preset karnataka_bengaluru --csv <state csv>
```

This writes a `.js` block to paste into `SCENARIOS` in `frontend/src/lib/scenarios.ts` and a `.json` record of every count, cleaning step and assumption under `backend/real_data/data/regional/`. Steps and safeguards are in [`backend/real_data/README.md`](backend/real_data/README.md).

## Known limitations

- All farmers and the fleet are synthetic. ILO's lead depends on the assumed farm-gate discount and on a few high-priced mandis (Sheohar in Bihar).
- Price response to extra volume is modelled only if `price_impact` is switched on; its elasticities are lower bounds, and fixed-price numbers overstate gains by roughly 17% at those values.
- Road distances come from OpenStreetMap via OSRM. The public demo server is non-commercial with no uptime guarantee; point `OSRM_BASE_URL` at your own instance for anything beyond a demo. Speed is a constant 32 km/h.
- In the fleet model a vehicle is busy for the pickup leg plus turnaround; the delivery leg does not occupy it.
- Spoilage is a linear, uncalibrated model with a binary refrigeration switch, and its hourly rates move results a lot. Trips are single-mandi and single-crop for consolidation. The plan covers one day with no carry-over.
- Mandi capacity is a hard cap built from median daily arrivals; it binds in 3 of 5 presets and the cap assumption moves reported gain by 7% to 26%. A soft cap exists (`PriceImpact.soft`), but planning with it is not yet reliable.
- The Monte Carlo shock sizes and the farm-gate discount scenarios are judgement calls, not calibrated. Experiment results come from 2 to 6 synthetic seeds per setting, so treat the percentages as indications.
- In the regional presets the farmer cluster is centred on a mandi hub, so hauling pays far more often than in Bihar. Do not read lead sizes across presets as a statement about the regions.
- Six Bihar mandi-crop capacities are reporting defaults, not measurements, and Madhya Pradesh lost 27 mandis to missing coordinates.
- The exact MILP ground truth only scales to about 5 to 7 farmers.
- No authentication or hosted-deployment configuration; Docker Compose runs the database only.

## Documentation

- [`docs/ALGORITHM_AND_RESULTS.md`](docs/ALGORITHM_AND_RESULTS.md): design history, benchmarks and assumptions
- [`docs/MILP_GROUND_TRUTH.md`](docs/MILP_GROUND_TRUTH.md): the exact-benchmark method and results
- [`docs/PRODUCT.md`](docs/PRODUCT.md) and [`docs/DESIGN.md`](docs/DESIGN.md): who the UI is for and its design system
- [`docs/CHANGELOG.md`](docs/CHANGELOG.md)
- [`backend/README.md`](backend/README.md), [`frontend/README.md`](frontend/README.md), [`backend/real_data/README.md`](backend/real_data/README.md)
