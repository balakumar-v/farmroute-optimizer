# Real-data pipeline (Agmarknet to Farmroute)

Builds the real-market scenarios from Indian mandi data. Everything here lives under `backend/real_data/`; the planner and the API do not need these dependencies.

## Why a bulk CSV and not a scraper

Agmarknet's report API answers `TOKEN_OR_CAPTCHA_REQUIRED`, so automated download is blocked, and this project deliberately does not bypass it. The same Agmarknet data is published as a bulk dataset on the India Data Portal (daily, market-centre level, **with latitude and longitude**, arrivals in tonnes, modal price in INR per quintal). `scrape_agmarknet.py` is kept only for `--probe` and `--diagnose`.

## What is real and what is synthetic

| Item | Source | Status |
|---|---|---|
| Price per crop (Rs/kg) | modal price, median over the window, quintal to kg | **Real (dated snapshot)** |
| Capacity per crop (kg/day) | reported daily arrivals, median | **Real (proxy, not a hard cap)** |
| Market lat/lng | the dataset's own coordinates (or a geocoder or manual override) | **Real; spot-check** |
| Farmers, fleet costs and speeds, spoilage rates | `logistics_lib_v2.py` | Synthetic or assumed |

**The data is dated, not live.** The portal updates daily but each state lags (for Bihar the latest date in the export was 2026-04-01), so prices are not today's. Pick the window that matches the season you want; one downloaded file supports any window. The output prints `data window` and stores it in `real_markets.json` under `meta`. For fresher prices, data.gov.in's mandi API (free personal key) gives current-day prices only, with no arrivals and no coordinates.

## Run (from `backend/`)

1. Download once, by hand: indiadataportal.com, dataset "Agriculture Marketing", resource "APMC arrivals and prices (Agmarknet)", sign in, Download Data, choose the state and purpose, Download CSV File.
2. Build and load:
   ```
   pip install -r requirements.txt -r real_data/requirements-realdata.txt
   python real_data/import_idp_csv.py path/to/file.csv --state Bihar --from 2025-12-01 --to 2026-02-28
   python real_data/build_real_markets.py            # writes data/real_markets.json
   uvicorn main:app --port 8000 --env-file .env      # separate terminal
   python real_data/load_real_scenario.py --reset
   ```
   `import_idp_csv.py` prints the dates the file actually covers and says so if your window is empty. If it reports "missing expected columns", extend `ALIASES` with the header names it lists.

## Safeguards

- Markets with zero or blank coordinates, or a point outside the state's bounding box, are **dropped and listed**, never mis-placed.
- Several markets in one district with the identical point (likely a district centroid) trigger a printed warning.
- A (market, crop) pair needs at least 5 days with both price and arrival; arrivals are taken once per day, not summed over varieties.
- Unrecognised units are dropped, not guessed. `data/mandi_coords_overrides.csv` (same columns as `mandi_coords.csv`) always wins.
- `geocode_mandis.py` (OpenStreetMap) is only a fallback for markets lacking coordinates.

## Capacity

In the Bihar file, reported daily arrivals per mandi for potato and onion are small (roughly 1 to 60 tonnes a day), so capacity can genuinely bind for a pool. In states or mandis with much larger arrivals it may not. `build_real_markets.py --capacity-scale` rescales it; that is a modelling choice and is recorded in the JSON `meta`.

## Coverage

Bihar mandis report few commodities: in the export only **potato and onion** of the six crops (no tomato, cauliflower, mango or spinach). More crops need other states' data; the regional presets use the Karnataka, Uttar Pradesh, Maharashtra and Madhya Pradesh files.

## Fleet size (an assumption, not data)

`load_real_scenario.py` reuses the project's synthetic fleet rule (about 1 vehicle per 40 farmers, at least 1 per type). With about 34 potato and onion farmers that is 4 vehicles at full utilisation and about 19% of produce gets no truck. `--fleet-multiplier 2` doubles it. To report the dependence, run the API and:

```
python real_data/fleet_sensitivity.py --csv fleet_sensitivity.csv     # wipes loaded data; re-run the loader afterwards
```

The model charges nothing for idle vehicles, so a larger fleet never costs extra; say so when you report it.

## Economic dispatch

The planner withholds trips that lose money and re-plans so those trucks and market capacity go to profitable trips (`run_our_system_v2(..., withhold_uneconomic=True)`, the default). Withheld produce is not counted as sold, and the app labels such pools "withheld: unprofitable". Details and measurements: `docs/ALGORITHM_AND_RESULTS.md`, section 17.

## Adding a preset to the app

The preset dropdown groups scenarios by `category`: **Synthetic scenarios** and **Real data**. Real means the mandis' prices, capacities and coordinates; synthetic means the farmers and fleet (each preset's description says so).

For a single-state dataset, generate an entry and paste it into `SCENARIOS` in `frontend/src/lib/scenarios.ts`; it appears under "Real data" automatically (`SCENARIO_CATEGORIES` at the top of that section lists the categories; empty ones stay hidden):

```
python real_data/make_preset_block.py --id my_new_id --label "Shown in dropdown" --blurb "REAL: ... SYNTHETIC: ..."
```

### Regional presets from a whole-state CSV (`build_regional_presets.py`)

For a state-wide India Data Portal "APMC Arrivals and Prices" CSV that carries the portal's own mandi coordinates:

```
python real_data/build_regional_presets.py --list
python real_data/build_regional_presets.py --preset karnataka_bengaluru --csv <Karnataka csv>
```

It cleans the rows (bad prices, min/max conflicts, arrival typos, unit confusion), validates coordinates, flags and raises placeholder capacities, picks the nearest mandis to a hub, builds synthetic farmers and a fleet with explicit counts, and writes `data/regional/<preset>.js` (paste into `SCENARIOS` in `frontend/src/lib/scenarios.ts`) and `<preset>.json` (every count and assumption). The module docstring lists each rule and constant. To add another region, add an entry to `PRESETS` (state, window, hub mandi, seed).

## Tests

From `backend/`: `python -m pytest real_data/tests tests -q`. They run offline; all numbers in them are synthetic fixtures.
