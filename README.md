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

## Quick start

Needs Python 3.10+ (developed on 3.12) and a browser. No build step, no Node.

```bash
# 1. backend (run from inside backend/)
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# 2. frontend (second terminal)
cd frontend
python3 -m http.server 8080
```

Open http://localhost:8080. Pick a scenario on the first screen and press Run. It loads the data, computes the plan, and opens the map. Opening `frontend/index.html` directly also works.

The backend URL defaults to `http://localhost:8000`; change it from the connection chip in the top-right of the page. Interactive API docs are at `http://localhost:8000/docs`. A large scenario can take a few seconds to compute (the project's benchmarks put ILO at 0.5 to 3.8 s on the regional presets).

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
5. Farmer-level no-loss. Surplus from each trip is shared so every farmer gets at least their own farm-gate value.

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
  ilo_v3.py                  ILO v3, the recommended planner
  algorithms_v2.py           ILO v2 building blocks and legacy baselines
  baselines_v3.py            behavioural and rational baselines, farm-gate pricing
  logistics_lib_v2.py        data model: 6 crops, 7 vehicle types, costs, spoilage
  visualization_adapter.py   reshapes a stored plan for the map (no recomputation)
  integrated_milp.py         exact MILP ground truth for small instances
  database.py, schemas.py    SQLite storage and request/response models
  verify_setup.py            endpoint sanity check
  verify_visualization.py    map-adapter check (see Known issues)
  benchmark_ilo_v3.py        ILO v3 against every baseline, many scenarios
  benchmark_*.py             other scale and comparison benchmarks
  tests/                     dispatch, baselines, ILO v3, visualization
  real_data/                 Agmarknet pipeline, regional preset builder, data (own README)
frontend/
  index.html, style.css, app.js
  config.js                  map tile settings
  vis/                       map, simulation engine, narrator, panels, theater
  vendor/                    MapLibre GL, deck.gl, self-hosted fonts
ALGORITHM_AND_RESULTS_V2.md  design history, benchmarks, assumptions (sections 19 to 21 cover v3 and the presets)
MILP_GROUND_TRUTH.md         exact-benchmark method and results
PRODUCT.md, DESIGN.md        who the UI is for, and its design system
CHANGELOG.md
```

## API

Full request and response shapes are in `backend/README.md`.

| Endpoint | Purpose |
|---|---|
| `POST /farmers`, `GET /farmers` | Add and list farmers |
| `POST /vehicles`, `GET /vehicles` | Add vehicles by type and count |
| `POST /markets`, `GET /markets` | Add markets (per-crop price and capacity) |
| `POST /plan/compute` | Run ILO and the baselines on the current data and store the run |
| `GET /plan/{id}` | A stored run, with its input snapshot |
| `GET /plan/{id}/visualization` | The same run reshaped for the map |
| `POST /sensors/reading`, `GET /sensors/readings` | Store ESP32 temperature and humidity readings |
| `POST /reset` | Clear all data |

`/plan/compute` returns `integrated_logistics_optimization`, `individual_transport` and `proximity_pooling`, each with `pools` and a `summary` that includes `net_return_incl_farmgate`, plus `realistic_baselines` as above. Crops: `tomato`, `onion`, `potato`, `cauliflower`, `mango`, `spinach`. Vehicle types: `mini_pickup`, `van`, `reefer_van`, `truck_2t`, `reefer_2t`, `truck_5t`, `reefer_5t`. There is no authentication; this is a local demo.

## What is real and what is not

- Real: mandi coordinates (the portal's own, never geocoded or invented), prices and reported daily arrivals.
- Synthetic: every farmer, lot size, ready time and the fleet. Farmer counts (about 60 pickups per regional preset, a typical collection round for one FPO) and vehicle sizes are modelling choices.
- Assumed: the farm-gate price (20% under the median mandi price), the baseline behaviour parameters, and mandi capacity. Capacity is the median reported daily arrival, and where one value repeats on over 70% of days it is a reporting default, so it is raised to the lower quartile of that state's other mandis for the crop (never lowered).
- Dropped, not guessed: mandis with no coordinates (Maharashtra 5, Madhya Pradesh 27), implausible price or arrival units, and mandi-crop series absorbing under 1 t per day.
- Routes are straight lines between real stop coordinates. There is no road network and no depot data.
- Per-stop times are reconstructed with the algorithm's own timing constants, not replayed from its internals.
- Sensor readings are stored only. The planner cannot yet recompute spoilage from live readings, and the UI never simulates sensor data.

## Map tiles

The map always renders a limewash background with a lat/lng grid, so it works offline. Street tiles load on top when the internet is available (Esri gray canvas by default, no key). To use another provider, such as CARTO with a free key, edit `frontend/config.js`.

## Tests and benchmarks

```bash
cd backend
python3 verify_setup.py
pip install pytest -r real_data/requirements-realdata.txt
python3 -m pytest tests real_data/tests          # 103 tests, about a minute

python3 benchmark_ilo_v3.py grid      # win/tie/loss map across scenarios
python3 benchmark_ilo_v3.py robust    # planner assumes 20% discount, truth differs
python3 benchmark_ilo_v3.py bihar     # the Bihar preset
```

Without `real_data/requirements-realdata.txt`, the real-data tests fail on a missing `agmarknet` module; the API does not need it.

## Real-data pipeline

The India Data Portal's Agmarknet export is a bulk CSV you download by hand (the Agmarknet site itself is captcha-protected). The repo includes the five state CSVs used here under `backend/real_data/data/raw/`, about 15 MB of data in all.

```bash
# regional preset (any of the four non-Bihar states)
python3 real_data/build_regional_presets.py --list
python3 real_data/build_regional_presets.py --preset karnataka_bengaluru --csv <state csv>
```

This writes a `.js` block to paste into `SCENARIOS` in `frontend/app.js` and a `.json` record of every count, cleaning step and assumption under `real_data/data/regional/`. Bihar uses the older `import_idp_csv.py`, `build_real_markets.py` and `make_preset_block.py` path. Steps and safeguards are in `backend/real_data/README.md`.

## Known issues and limitations

- `verify_visualization.py` currently fails. Its check that served plus unserved farmers cover everyone predates farm-gate farmers, who are now a third group (`farmgateFarmerIds`). It also needs an empty database. The pytest suite, including `test_visualization_baselines.py`, passes.
- All farmers and the fleet are synthetic, and ILO's lead depends on the assumed farm-gate discount and on a few high-priced mandis (Sheohar in Bihar). No price response to extra volume is modelled.
- In the regional presets the farmer cluster is centred on a mandi hub, so hauling pays far more often than in Bihar. Do not read the lead sizes across presets as a statement about the regions.
- Six Bihar mandi-crop capacities are reporting defaults, not measurements. Madhya Pradesh lost 27 mandis to missing coordinates, which thins its mandi set.
- MILP ground truth only scales to about 5 to 7 farmers.
- No authentication, deployment config or Docker.
