# Farmroute Optimizer

A decision layer for farmer produce pooling and market allocation. Small farmers each need a truck and a market; this system decides who rides together, on which vehicle, to which mandi [wholesale produce market], and what each farmer ends up with. Then it explains every decision on a map.

Course project (first-semester design thinking). A prototype on synthetic farmers and dated real mandi data, not a production system.

## What it decides

Given farmers (location, crop, quantity, ready and deadline hours, refrigeration need), a vehicle fleet, and markets (price and capacity per crop), the optimizer returns a plan: which farmers pool onto which trips, which trips are worth running at all, and where each load sells.

Two numbers have to be read together:

- Farmer value (₹): net return of the trips that run (revenue minus transport cost), plus the farm-gate value of produce the plan did not haul. Farm-gate means selling at the doorstep to a trader. Counting it matters because a farmer who sells at the doorstep would otherwise score zero.
- Produce sold (%): the share of the harvest that reached a mandi.

The farm-gate price is an assumption, not data: 20% below the median mandi price for that crop. The UI says so wherever the number appears.

### Example result

Bihar preset (real mandi prices, 34 synthetic farmers, 8 vehicles, 8 mandis), default 20% farm-gate discount:

| Approach | Farmer value | Sold at a market |
|---|---|---|
| **ILO** (ours) | ₹208,586 | 64.5% |
| Proximity Pooling | ₹146,705 | 10.5% |
| Individual Transport | ₹135,417 | 10.5% |

ILO is 42% ahead of Proximity Pooling and 54% ahead of Individual Transport. The baselines sell little at a market because the nearest buying mandi is a median 44 km (potato) and 51 km (onion) away, so their rules rarely trigger a haul. The size of the lead depends on the assumed discount: against the best of all baselines in this project, ILO leads by 12% at a 5% discount and by 54% at 40% (`ALGORITHM_AND_RESULTS_V2.md`, section 20).

Not every scenario is a win. On the synthetic Cold chain scenario ILO and Proximity Pooling tie (₹56,190 against ₹56,113). With spoilage counted from pickup, the refrigeration effect is small at those distances, and the scenario's blurb says so. Treat all of these as single runs on synthetic farmers.

## Live demo

https://farmroute-optimizer-frontend.onrender.com/

The frontend is hosted on Render and the database is Neon Postgres. A free Render service sleeps when idle, so the first request after a pause can take a while to wake up.

## Quick start

Needs Python 3.10+ (developed on 3.12), Node 18+ and a Postgres database. The easiest is a free [Neon](https://neon.tech) project; a local Postgres works too.

```bash
# 1. backend (run from inside backend/)
cd backend
pip install -r requirements.txt
cp .env.example .env              # then put your Postgres connection string in DATABASE_URL
uvicorn main:app --reload --port 8000 --env-file .env

# 2. frontend (second terminal)
cd frontend
npm install
npm run dev
```

The backend will not start without `DATABASE_URL`. Tables are created on first start (`init_db`), so there is no migration step.

Open http://localhost:5173. Pick a scenario on the first screen and press Run. It loads the data, computes the plan, and opens the map.

The backend URL defaults to `http://localhost:8000`; change it from the connection chip in the top-right of the page, or set `VITE_API_BASE` when building the frontend. Interactive API docs are at `http://localhost:8000/docs`. A large scenario can take a few seconds to compute (the project's benchmarks put ILO at 0.5 to 3.8 s on the regional presets).

## Deployment (Render + Neon)

| Part | Where | Settings that matter |
|---|---|---|
| Database | Neon Postgres | Use the connection string as `DATABASE_URL`. The code disables prepared statements, so Neon's pooled endpoint works. |
| Backend | A Render web service, root directory `backend/` | Build `pip install -r requirements.txt`; start `uvicorn main:app --host 0.0.0.0 --port $PORT` |
| Frontend | Render static site, root directory `frontend/` | Build `npm ci && npm run build`; publish `dist`; set `VITE_API_BASE` to the backend's public URL |

Backend environment variables:

| Variable | Purpose | Default |
|---|---|---|
| `DATABASE_URL` | Postgres connection string (required) | none |
| `ADMIN_TOKEN` | Secret that every admin route requires (`Authorization: Bearer <token>`). Required for the farmer portal to work. | unset: admin routes are open |
| `ADMIN_AUTH` | `off` opens the admin routes without a token while keeping the farmer portal working. For demos and early pilots only: anyone who can reach the backend can then read everything, reset it, and issue a PIN for any farmer (which is logging in as them). | `on` |
| `FPO_PHONE` | Phone number the farmer app's "Call your FPO" button dials, copied into each card when you publish a plan | none (button hidden) |
| `FARMROUTE_SECRET` | Key that signs farmer login tokens. Set it to a long random string; without it tokens are signed with a per-process key and stop working on every restart. | random per process |
| `ALLOWED_ORIGINS` | Comma-separated frontend origins allowed by CORS, no trailing slash, e.g. `https://farmroute-optimizer-frontend.onrender.com` | `*` (any site) |
| `ROUTING_PROVIDER` | `osrm`, `ors`, or `off` to skip road lookups | `ors` if `ORS_API_KEY` is set, else `osrm` |
| `ORS_API_KEY` | OpenRouteService key | unset |
| `OSRM_BASE_URL` | Self-hosted or alternative OSRM server | the public demo server |
| `ROAD_PLANNING` | `off` to plan on straight lines without a road matrix | `auto` |
| `ROAD_MATRIX_MAX_POINTS` | Largest scenario (farmers + mandis) that gets a road matrix | 200 |
| `FARMROUTE_ROAD_CIRCUITY` | Fixed road-km / straight-km factor when road lookups are off | 1.0 |
| `SMS_PROVIDER` | How SMS goes out: `dry` (log only), `twilio` or `msg91`. Needs that provider's credentials (see `backend/notify.py`). | `dry` |
| `WHATSAPP_PROVIDER` | How WhatsApp goes out: `dry`, `meta` (WhatsApp Cloud API) or `twilio`. | `dry` |
| `DEFAULT_COUNTRY_CODE` | Digits added to phone numbers typed without a country code | `91` |
| `NOTIFY_DEMO_SHOW_OTP` | `on` returns the SMS code in the API response while `SMS_PROVIDER=dry`, so a demo can be completed without sending SMS. Never use with real farmers. | `off` |

Set `ALLOWED_ORIGINS`, `ADMIN_TOKEN` and `FARMROUTE_SECRET` in production: the defaults accept requests from any site and leave the admin routes open.

The current frontend is the admin console and does not send an `ADMIN_TOKEN` yet, so setting it on a deployment that serves that frontend will make the console's requests fail with 401 until a token field is added to it.

## The app

| Tab | What it shows |
|---|---|
| Scenarios | Eight ready-made scenarios. One click loads the data, computes the plan and opens the map. |
| Data | The farmers, vehicles and markets the optimizer sees. Add rows by hand. |
| Plan | The ILO plan as a ledger: net return, produce not hauled and sold at the farm gate, farmer value, harvest sold, spoilage, and one row per pool. If ILO found nothing better than a simpler plan, the page says which plan it recommends instead. |
| Compare | ILO against two behavioural baselines, with farmer value and produce sold side by side, a delta against ILO, and a full breakdown table. |
| Map | The plan on a map: 7 presentation stages, a playable timeline, a step-by-step story, details for anything you select, compare mode, 3D, chase camera, and a full-screen walkthrough. Farmers who sell at the farm gate are slate; farmers who wanted a truck and got none are red. |

### Scenarios

Three synthetic scenarios, each built to isolate one mechanism, and five built on real mandi data.

| Scenario | Farmers / vehicles / mandis | What it isolates |
|---|---|---|
| 1. Cold chain | 11 / 4 / 2 | One reefer [refrigerated truck] against plain trucks. A mechanism demo, not a win (see above). |
| 2. Market allocation | 10 / 4 / 3 | Price and capacity differences between mandis |
| 3. Fleet scarcity | 15 / 3 / 2 | Few trucks and clashing pickup windows |
| Bihar, Dec 2025 to Feb 2026 | 34 / 8 / 8 | Potato and onion; the farmers' own district |
| Karnataka, around Bengaluru, Feb to Apr 2026 | 61 / 16 / 8 | Tomato, onion, potato, cauliflower, mango |
| Uttar Pradesh, around Aligarh, Nov 2025 to Jan 2026 | 59 / 15 / 8 | Potato, onion, tomato, cauliflower, spinach |
| Maharashtra, around Junnar (Pune), Feb to Apr 2026 | 60 / 14 / 8 | Onion, tomato, potato, cauliflower, spinach |
| Madhya Pradesh, around Indore, Feb to Apr 2026 | 57 / 13 / 11 | Onion, potato, tomato, cauliflower |

In the real-data scenarios the mandi locations, prices and daily arrivals come from Agmarknet via the India Data Portal. The farmers and the fleet are synthetic, because no farmer-level data exists. Each scenario's "About the data" note lists what was cleaned and which counts are assumptions.

## How the optimizer works

ILO (Integrated Logistics Optimization) v3 lives in `backend/ilo_v3.py` and is the plan the UI recommends. Its goal is one number: farmer value, with the same prices and accounting for every approach. The empty return leg is charged and spoilage runs from pickup.

1. Honest objective. Dispatch a trip only if it beats the farm-gate value of its members, not merely if its net return is above zero.
2. Pool consolidation. For each (mandi, crop) pair, a Clarke-Wright savings pass [a classic route-merging heuristic] merges farmers heading to the same mandi into full trucks.
3. Set partitioning. Candidate trips (single farmers, ILO's own pools, neighbour groups, merged routes) go into an exact 0/1 program [solved with SciPy's HiGHS] that picks disjoint trips maximising total gain, with mandi capacity as a constraint. The planner then runs market allocation (an LP [linear program]) and economic dispatch on those pools.
4. Safeguard. ILO returns the best of its own plans and every baseline under the same accounting, and records which one it chose (`ilo_meta.chosen`).
5. Farmer-level no-loss. Surplus from each trip is shared so every farmer gets at least their own farm-gate value. This value-gain split is what `per_farmer_net` reports for ILO v3.

Step 3 is fleet-aware since v3.1: each candidate trip becomes columns (trip, vehicle class, start slot) and the program also limits how many vehicles of each class are busy in any 15-minute cell, so it chooses vehicles as well as trips. The old fleet-blind plan still competes in step 4, so the final value cannot drop.

#### v3.1 options (all off or neutral by default)

| Option | What it does | Default |
|---|---|---|
| `fleet_aware`, `keep_blind_plan` | fleet-aware set partition; keep the old plan as a fallback | on, on |
| `road_circuity` (API query) / `set_road_circuity(k)` / `FARMROUTE_ROAD_CIRCUITY` | planner distance = k x straight-line km (and time with it) | the API plans on measured road distances (see Distances below); k applies when road lookups are off or you pass it |
| `price_impact`, `true_price_impact`, `markets_per_trip` | volume-dependent mandi prices (`price_impact.PriceImpact`; `capacity_multiple=3` makes the capacity soft); belief drives the MILP, truth drives simulation and scoring; with a belief, each trip is offered at up to 3 mandis | off, off, 3 when a belief is set |
| `stress_discounts` | re-value the plan at other true farm-gate discounts; adds `meta["discount_stress"]` | 5/10/20/30/35% |
| `mc_draws`, `mc_min_prob`, `mc_kwargs` | Monte Carlo replay of the finished plan (`stress.py`); optionally withhold fragile trips; shock sizes incl. `spoilage_rate_sd` | off, off, default shocks |

Every dispatched trip also carries `breakeven`: the doorstep Rs/kg per crop below which hauling still pays, its cushion in percent, and the smallest true discount at which it pays. The intended rule is to dispatch only if the trader's live quote is below that price.

What these showed (synthetic scenarios, few seeds; `ALGORITHM_AND_RESULTS_V2.md` section 22 has the tables and caveats):
- Planning with straight-line distances when roads are 1.4x longer cost about 17% of the gain and left 15 of 65 trips below the farm-gate price. Planning with the right factor cut that to 2 of 58. Underestimating the factor by 0.2 costs about 2%; overestimating by 0.2 costs about 14%.
- Fleet-aware planning adds 0 to 2.5% of final value; the gain is small because the synthetic fleet is small relative to the farmers. It also prices vehicles: one extra reefer was worth about Rs 4.7k in one scenario.
- Price impact: with elasticities estimated from your Agmarknet files (lower bounds), scoring with price response cuts reported gain by about 17%. Planning with it adds nothing measurable at those elasticities (-2%, inside model error) and about +7% when the true response is 3.5x stronger. Wrong beliefs hurt: assuming 2x the truth gave +0.1%.
- Farm-gate discount: assuming 20% to 30% and using the live-quote rule had a worst-case regret of 8% to 11% across true discounts of 5% to 35%. Without the rule, assuming 30% lost money when the true discount was 5%.
- Trip structure: multi-mandi trips and the top-3 mandi cut are not worth building; mixed-crop trips add about 0 to 5% and are noisy. Mandi capacity is the lever: it binds in 3 of 5 presets, and tripling it adds 15% to 39% (section 24). Capacity is a weak input, so report capacity sensitivity with any gain.
- Soft capacity (section 25): scoring with a soft mandi capacity (volume up to 3x a normal day at falling prices) instead of a hard cap raises reported gain by 7% to 26% in 8 of 10 cases. Planning with it is not reliably better than ignoring price impact (6 of 10 cases better, 4 worse by up to 10%), so use it for scoring and sensitivity, not planning.
- Spoilage: ILO beat every baseline under every spoilage variant tried (lead 4% to 9%), but doubling the hourly spoilage rate cut the gain by 25% and changed about half of the hauled farmers; the refrigeration multiplier mattered less (3 -> 6: -12%). The per-crop hourly rates are the parameter worth measuring.
- Monte Carlo (100 draws, travel +-20%, readiness delays up to about 1 h, prices +-8%): the plan kept about 88% of its nominal gain on average and about 49% in the worst 5% of draws; it never lost money overall. Withholding trips with `p_beat` below 0.7 to 0.9 lowered both the mean and the 5th percentile, so it is off.

The guarantee is narrow: returned value is at least the best baseline, measured with the prices and accounting the planner was given. It says nothing about real farmers, and it is only as good as the farm-gate price input.

ILO v2 (`algorithms_v2.py`) still supplies the lower-level pieces (k-means [clustering that picks k centre points] depots, DBSCAN [density-based clustering] pools, market LP, dispatch). It is also computed as a reference under `realistic_baselines.legacy_ilo_v2`. For small instances an exact MILP [mixed-integer linear program] gives a ground truth (`integrated_milp.py`, `MILP_GROUND_TRUTH.md`).

### Baselines

The two shown in the UI model what farmers do without a planner (`baselines_v3.py`). Nobody checks the arithmetic, so some trips lose money and some profitable ones are skipped.

- Individual Transport: a farmer hires a spot truck to the nearest buying mandi if it is within 40 km and its posted price beats the trader's offer by 10%. Otherwise they sell at the farm gate.
- Proximity Pooling: the same rule for groups of up to 4 neighbours within 5 km sharing one truck. The group waits for its last member, and a pickup after anyone's deadline is a no-show.

Spot trucks cost 1.15 times the usual rate, arrive one hour after the request, and are not the FPO's [farmer producer organisation's] own fleet. The 40 km, 10%, 5 km, 1.15x and 1 h values are assumptions held in one `Behaviour` dataclass.

The API also returns, under `realistic_baselines`, a rational variant of each (exact economics, hauls only if it beats the farm gate), a farm-gate-only reference, the old `legacy_individual_transport` and `legacy_proximity_pooling`, and `ilo_meta`. The UI does not show these.

## Repository layout

```
backend/
  main.py                    FastAPI app and endpoints
  ilo_v3.py, ilo_v3_ext.py   ILO v3, the recommended planner, and its column-generation extension
  algorithms_v2.py           ILO v2 building blocks and legacy baselines
  baselines_v3.py            behavioural and rational baselines, farm-gate pricing
  advisor.py                 read-only views of a stored plan: fleet advice, quote check, impact,
                             payout statements, plan diff, driver sheet
  farmer_upload.py           csv/xlsx farmer-list parsing and validation
  auth.py                    admin token, farmer PIN login, signed tokens, lockout
  roads.py                   road distances (OSRM / OpenRouteService), matrix and route-geometry cache
  price_impact.py            volume-dependent mandi price model and eta estimator (off by default)
  stress.py                  Monte Carlo replay of a finished plan; withhold_fragile()
  calibrate_circuity.py      fit the road-circuity factor from real road distances
  logistics_lib_v2.py        data model: 6 crops, 7 vehicle types, costs, spoilage
  visualization_adapter.py   reshapes a stored plan for the map (no recomputation)
  integrated_milp.py, milp_benchmark.py   exact MILP ground truth for small instances
  database.py, schemas.py    Postgres storage (psycopg) and request/response models
  verify_setup.py            endpoint sanity check
  verify_visualization.py    map-adapter check (see Known issues)
  benchmark_ilo_v3.py        ILO v3 against every baseline, many scenarios
  benchmark_*.py             other scale and comparison benchmarks
  experiments_v3_1/, experiments_v4/   scripts behind the reported numbers (v3.1 has its own README)
  tests/                     dispatch, baselines, ILO v3, roads, advisors, upload, visualization
  real_data/                 Agmarknet pipeline, regional preset builder, data (own README)
farmer-app/                  the farmers' installable PWA (own README); no build step
frontend/                    React + TypeScript + Vite admin console (own README)
  src/                       views, state, API client, scenario data (lib/scenarios.ts), map engine (vis/)
  index.html, package.json, vite.config.ts
  app.js, style.css, vis/, vendor/, config.js   the pre-React frontend; no longer loaded by index.html
```
EXTENDING.md                 where to plug in new views, prices, objectives, constraints and presets
ALGORITHM_AND_RESULTS_V2.md  design history, benchmarks, assumptions (sections 19 to 21 cover v3 and the presets, 22 to 25 cover v3.1)
MILP_GROUND_TRUTH.md         exact-benchmark method and results
PRODUCT.md, DESIGN.md        who the UI is for, and its design system
CHANGELOG.md
```

## API

Full request and response shapes are in `backend/README.md`.

| Endpoint | Purpose |
|---|---|
| `POST /farmers`, `GET /farmers` | Add and list farmers |
| `POST /farmers/upload` | Bulk-add farmers from a `.csv` or `.xlsx` (all-or-nothing validation; `?dry_run=true` checks without saving) |
| `POST /vehicles`, `GET /vehicles` | Add vehicles by type and count |
| `POST /markets`, `GET /markets` | Add markets (per-crop price and capacity) |
| `POST /plan/compute` | Run ILO and the baselines on the current data and store the run |
| `GET /plan/{id}` | A stored run, with its input snapshot |
| `GET /plan/{id}/visualization` | The same run reshaped for the map |
| `POST /plan/{id}/roads` | Fetch and cache real-road geometry for a plan's routes (display only) |
| `GET /plan/{id}/fleet-advice` | What one extra vehicle of each class is worth (LP shadow value) |
| `POST /plan/{id}/quote-check` | A trader's doorstep offer for one farmer vs their planned take-home: haul or sell |
| `GET /plan/{id}/impact` | kg reaching buyers, rupees gained vs doing nothing, km and CO2 saved by pooling |
| `GET /plan/{id}/payout`, `/payout/{farmer_id}` | Per-farmer payout statements (totals reconcile to the plan value) |
| `GET /plan/{id}/diff/{old_plan_id}` | Which farmers a re-plan changed, and why |
| `GET /plan/{id}/driver-sheet/{vehicle_id}` | One vehicle's trips in order, with planned times, kg and map links |
| `POST /sensors/reading`, `GET /sensors/readings` | Store ESP32 temperature and humidity readings |
| `POST /reset` | Clear all data |
| `POST /farmers/pins`, `POST /farmers/{id}/pin` | Issue farmer PINs (shown once, stored hashed). `pins` issues for everyone without one; `?only_missing=false` re-issues for all |
| `POST /plan/{id}/publish`, `GET /published`, `DELETE /published` | Choose the one plan farmers can see (or hide it) |
| `POST /farmer/login` | Farmer ID + 6-digit PIN, returns a 12-hour token |
| `GET /farmer/me` | The logged-in farmer's own card from the published plan (farmer token only) |

`POST /plan/compute` options:
- `road_distances` (default `true`): plan on measured road distances between every farmer and mandi (OpenStreetMap via OSRM, cached in the database). If road data is unavailable it falls back to straight lines. The distance model used is stored with the plan as `distance_model`.
- `road_circuity=1.3`: plan and score with road distance = 1.3 x straight line instead (400 outside 1 to 3).
- `mode` = `returns` (default, maximise farmer value) or `spoilage` (least spoiled produce within `max_value_sacrifice`, default 0.10, of the best returns plan; slower).

`/plan/compute` returns `integrated_logistics_optimization`, `individual_transport` and `proximity_pooling`, each with `pools` and a `summary` that includes `net_return_incl_farmgate`, plus `distance_model` and `realistic_baselines` as above. Crops: `tomato`, `onion`, `potato`, `cauliflower`, `mango`, `spinach`. Vehicle types: `mini_pickup`, `van`, `reefer_van`, `truck_2t`, `reefer_2t`, `truck_5t`, `reefer_5t`. ### Roles and access

| Who | Gets in with | Can use |
|---|---|---|
| Admin (operator) | `ADMIN_TOKEN` as a bearer token | every route except the `/farmer/` ones |
| Farmer | farmer ID + PIN, then a signed token | `GET /farmer/me` only, which returns that farmer's card and nothing else |
| Anyone | nothing | `/docs`, `/openapi.json`, `POST /farmer/login` |

Admin access is default-deny: any route outside `/farmer/` requires the token, including ones added later. If `ADMIN_TOKEN` is not set the admin routes stay open (local development) and the farmer routes return 503, so farmers cannot be reached on an open backend by accident. Setting `ADMIN_AUTH=off` makes that choice on purpose; see the warning in the env table. A farmer's token cannot call any admin route, and the admin token is not accepted as a farmer token.

Farmers only see a plan an operator has published. Publishing builds one card per farmer holding only that farmer's own crop, quantity, status, payout lines and trip details (no other farmer's id, and no trip revenue or cost). Re-publishing marks which farmers' cards changed and why. PINs are stored as salted scrypt hashes, five wrong PINs lock that farmer for 15 minutes, and issuing a new PIN logs out the old sessions.

Limits: someone who knows a farmer ID can lock that farmer out for 15 minutes (an admin issuing a new PIN clears it); there is no per-IP rate limit because behind Render's proxy all callers share one address; there is one shared admin token, not per-operator accounts. Do not put real farmer details on a deployment before `ADMIN_TOKEN` is set.

## What is real and what is not

- Real: mandi coordinates (the portal's own, never geocoded or invented), prices and reported daily arrivals.
- Synthetic: every farmer, lot size, ready time and the fleet. Farmer counts (about 60 pickups per regional preset, a typical collection round for one FPO) and vehicle sizes are modelling choices.
- Assumed: the farm-gate price (20% under the median mandi price), the baseline behaviour parameters, and mandi capacity. Capacity is the median reported daily arrival, and where one value repeats on over 70% of days it is a reporting default, so it is raised to the lower quartile of that state's other mandis for the crop (never lowered).
- Dropped, not guessed: mandis with no coordinates (Maharashtra 5, Madhya Pradesh 27), implausible price or arrival units, and mandi-crop series absorbing under 1 t per day.
- Plans use measured road distances when OSRM is reachable, and straight lines otherwise (`distance_model` says which). The map draws real-road geometry once it has been fetched and straight lines until then. There is no depot data.
- Per-stop times are reconstructed with the algorithm's own timing constants, not replayed from its internals.
- Sensor readings are stored only. The planner cannot yet recompute spoilage from live readings, and the UI never simulates sensor data.

## Map tiles

The map always renders a limewash background with a lat/lng grid, so it works offline. Street tiles load on top when the internet is available (Esri gray canvas by default, no key). To use another provider, such as CARTO with a free key, edit `frontend/src/config.ts`.

## Tests and benchmarks

```bash
cd backend
pip install pytest
export DATABASE_URL=postgresql://...   # the endpoint tests need a Postgres; without it they are skipped
python3 -m pytest tests                # 178 tests; the full run takes about five minutes

python3 verify_setup.py                # endpoint sanity check against your DATABASE_URL (it ends by resetting the data)

python3 benchmark_ilo_v3.py grid      # win/tie/loss map across scenarios
python3 benchmark_ilo_v3.py robust    # planner assumes 20% discount, truth differs
python3 benchmark_ilo_v3.py bihar     # the Bihar preset
```

Use a throwaway database for tests: the endpoint tests call `POST /reset`, which empties every table. Road lookups need internet access; without it plans fall back to straight lines and the tests still pass.

`python3 -m pytest real_data/tests` additionally needs `pip install -r real_data/requirements-realdata.txt`; without it those tests fail on a missing `agmarknet` module. The API does not need it.

Frontend: `cd frontend && npm test` (simulation engine) and `npm run build` (typecheck plus production build).

## Real-data pipeline

The India Data Portal's Agmarknet export is a bulk CSV you download by hand (the Agmarknet site itself is captcha-protected). The repo includes the five state CSVs used here under `backend/real_data/data/raw/`, about 15 MB of data in all.

```bash
# regional preset (any of the four non-Bihar states)
python3 real_data/build_regional_presets.py --list
python3 real_data/build_regional_presets.py --preset karnataka_bengaluru --csv <state csv>
```

This writes a `.js` block of preset data to adapt into `SCENARIOS` in `frontend/src/lib/scenarios.ts` and a `.json` record of every count, cleaning step and assumption under `real_data/data/regional/`. Bihar uses the older `import_idp_csv.py`, `build_real_markets.py` and `make_preset_block.py` path. Steps and safeguards are in `backend/real_data/README.md`.

## Known issues and limitations

- `verify_visualization.py` currently fails. Its check that served plus unserved farmers cover everyone predates farm-gate farmers, who are now a third group (`farmgateFarmerIds`). It also needs an empty database. The pytest suite, including `test_visualization_baselines.py`, passes.
- All farmers and the fleet are synthetic, and ILO's lead depends on the assumed farm-gate discount and on a few high-priced mandis (Sheohar in Bihar). Price response to extra volume is modelled only if `price_impact` is switched on (default off); its elasticities are lower bounds, and fixed-price numbers overstate gains by roughly 17% at those values.
- Distances are measured road km (OSRM, cached) when reachable, else straight-line km times a circuity factor, at a constant 32 km/h for time. The public OSRM demo server is rate-limited and has no uptime guarantee, so a deployment that must not fall back should host its own (`OSRM_BASE_URL`). Road km do not capture road quality, so travel time is still approximate.
- In the fleet model a vehicle is busy for the pickup leg plus turnaround; the delivery leg does not occupy it (inherited from the simulator).
- Spoilage is still a linear, uncalibrated model with a binary refrigeration switch; its hourly rates move results a lot (section 23) and should be measured. Trips are single-mandi and single-crop for consolidation. The plan covers one day with no carry-over.
- Mandi capacity is a hard cap by default, built from median daily arrivals (some Bihar values are reporting defaults); it binds in 3 of 5 presets and the cap assumption moves reported gain by 7% to 26% (sections 24 and 25). A soft cap exists (`PriceImpact.soft`), but planning with it is not yet reliable.
- The Monte Carlo shock sizes and the farm-gate discount scenarios are judgement calls, not calibrated.
- v3.1 results come from 2 to 6 synthetic seeds per setting. Treat the percentages as indications.
- In the regional presets the farmer cluster is centred on a mandi hub, so hauling pays far more often than in Bihar. Do not read the lead sizes across presets as a statement about the regions.
- Six Bihar mandi-crop capacities are reporting defaults, not measurements. Madhya Pradesh lost 27 mandis to missing coordinates, which thins its mandi set.
- MILP ground truth only scales to about 5 to 7 farmers.
- No Docker image or CI yet. Deployment is by hand on Render and Neon (see Deployment). The admin routes are open unless `ADMIN_TOKEN` is set; the admin console frontend has no login field for it yet.
