# Real-data pipeline (Agmarknet data -> FarmRoute)

Replaces the **synthetic markets** with real Indian mandi data. The pipeline itself only adds files under `backend/real_data/`.
Separately, this round also changed the planner (see "Planner change" below): `backend/algorithms_v2.py`, `frontend/app.js` (pool card for
withheld pools; preset categories + the Bihar preset), `ALGORITHM_AND_RESULTS_V2.md` (section 17) and new tests in `backend/tests/`.

## Why a bulk CSV and not a scraper
Agmarknet's report API now answers `TOKEN_OR_CAPTCHA_REQUIRED` (captcha), so automated download is
blocked, and this project deliberately does not bypass it. The same Agmarknet data is published as a
bulk dataset on India Data Portal (daily, market-centre level, **with latitude/longitude**, arrivals in
tonnes, modal price INR/quintal). `scrape_agmarknet.py` is kept only for `--probe/--diagnose`.

## What is real vs. synthetic

| Item | Source | Status |
|---|---|---|
| Price per crop (Rs/kg) | modal price, median over the window, quintal -> kg | **REAL (dated snapshot)** |
| Capacity per crop (kg/day) | reported daily arrivals, median | **REAL (proxy, not a hard cap)** |
| Market lat/lng | the dataset's own coordinates (or geocoder / manual override) | **REAL - spot-check** |
| Farmers, fleet costs/speeds, spoilage rates | `logistics_lib_v2.py` | synthetic / assumed |

**The data is dated, not live**: the portal updates daily but each state lags (for Bihar the latest date in the real export was 2026-04-01). Prices are NOT today's.
Pick the window that matches the season you want (e.g. latest 30 days, or the same months a year earlier - one downloaded file supports any window); the output prints `data window` and stores it
in `real_markets.json -> meta`. For fresher prices later, data.gov.in's mandi API (free personal key) gives
current-day prices only (no arrivals, no coordinates).

## Run (from `backend/`)
1. Download once, by hand: indiadataportal.com -> dataset "Agriculture Marketing" -> resource
   "APMC arrivals and prices (Agmarknet)" -> sign in -> Download Data -> state purpose -> Download CSV File.
2. ```
   pip install -r requirements.txt -r real_data/requirements-realdata.txt
   python real_data/import_idp_csv.py path\to\file.csv --state Bihar --from 2024-09-01 --to 2024-09-30
   python real_data/build_real_markets.py            # -> data/real_markets.json
   uvicorn main:app --port 8000                      # separate terminal
   python real_data/load_real_scenario.py --reset
   ```
   `import_idp_csv.py` prints the dates the file actually covers; if your window is empty it tells you.
   If it reports "missing expected columns", paste the header list and extend `ALIASES`.

## Safeguards
* Markets with zero/blank coordinates, or a point outside the state's bounding box, are **dropped and listed**, never mis-placed.
* Several markets in one district with the identical point (likely a district centroid) trigger a printed warning.
* A (market, crop) pair needs >= 5 days with both price and arrival; arrivals are taken once per day, not summed over varieties.
* Unrecognised units are dropped, not guessed. `data/mandi_coords_overrides.csv` (same columns as `mandi_coords.csv`) always wins.
* `geocode_mandis.py` (OpenStreetMap) is now only a fallback for markets lacking coordinates.

## Capacity note
In the real Bihar file (Oct 2025-Apr 2026) reported daily arrivals per mandi for potato/onion are small
(roughly 1-60 tonnes/day), so capacity can genuinely bind for a pool. In states/mandis with much larger
arrivals it may not; `build_real_markets.py --capacity-scale` lets you rescale (a modelling choice, recorded in the JSON meta).

## Coverage you should expect
Bihar mandis report only a few commodities: in the real export only **potato and onion** of your six crops
(no tomato, cauliflower, mango, spinach). More crops need neighbouring states (e.g. Uttar Pradesh) in the same download.

## Fleet size (an assumption - not data)
The loader reuses the project's synthetic fleet rule (~1 vehicle per 40 farmers, min 1 per type). With only
potato+onion farmers kept (~34), that is 4 vehicles at 100% utilisation and ~19% of produce gets no truck.
`load_real_scenario.py --fleet-multiplier 2` doubles it. To report the dependence, run the API and:
```
python real_data/fleet_sensitivity.py --csv fleet_sensitivity.csv     # wipes loaded data; re-run the loader after
```
The model charges nothing for idle vehicles, so a larger fleet never costs extra here - say so when you report it.

## Planner change (economic dispatch)
`algorithms_v2.py` now withholds trips that lose money and re-plans so those trucks and market capacity go to profitable
trips (`run_our_system_v2(..., withhold_uneconomic=True)`, default; pass `False` for the previous behaviour). Details,
measurements and the provenance note are in `ALGORITHM_AND_RESULTS_V2.md` section 17. Withheld produce is NOT counted
as sold. Pool cards in the app now show "withheld: unprofitable" for such pools.

## Frontend presets (Synthetic vs Real data)
The preset dropdown groups presets by `category`: **Synthetic scenarios** (the 3 original mechanism demos, unchanged)
and **Real data** (currently *Bihar mandis, Mar 2026: potato & onion*). Real = 7 mandis' prices/capacities/coordinates;
synthetic = the 34 farmers and the 8-vehicle fleet (stated in the preset's description).
To add another real dataset: run the pipeline for it, then
```
python real_data/make_preset_block.py --id my_new_id --label "Shown in dropdown" --blurb "REAL: ... SYNTHETIC: ..."
```
and paste the printed entry into `SCENARIOS` in `frontend/app.js`. It appears under "Real data" automatically
(`SCENARIO_CATEGORIES` at the top of that section lists the categories; empty ones stay hidden).

## Tests
`python -m pytest real_data/tests tests -q` (from `backend/`) - offline; all numbers in the tests are synthetic fixtures.


## Regional presets from a whole-state CSV (`build_regional_presets.py`)

For a state-wide India Data Portal "APMC Arrivals and Prices" CSV that carries the portal's own mandi coordinates:

    python real_data/build_regional_presets.py --list
    python real_data/build_regional_presets.py --preset karnataka_bengaluru --csv <Karnataka csv>

It cleans the rows (bad prices, min/max conflicts, arrival typos, unit confusion), validates coordinates, flags and raises
placeholder capacities, picks the nearest mandis to a hub, builds synthetic farmers and a fleet with explicit counts, and writes
`data/regional/<preset>.js` (paste into `SCENARIOS` in `frontend/app.js`) and `<preset>.json` (every count and assumption).
The module docstring lists each rule and constant. Farmers, fleet and counts are synthetic; mandi data is real. To add another
region, add an entry to `PRESETS` (state, window, hub mandi, seed). Tests: `real_data/tests/test_regional_presets.py`.
