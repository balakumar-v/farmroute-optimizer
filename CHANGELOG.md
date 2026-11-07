# Changelog


## WhatsApp OTP and updates
- `OTP_CHANNEL` (sms | whatsapp | both) chooses where the verification code goes; every attempt is logged per channel.
- Meta adapter sends the code with an authentication template (body + copy-code button); `WHATSAPP_MODE=text` for first tests.
- Farmer app wording no longer says the code only comes by SMS. See `WHATSAPP_SETUP.md`.

## Spoilage rates from the weight-loss review (Nov 2026)
- `CROPS` in `logistics_lib_v2.py`: `base_spoil_per_hr` is now the COOLED hourly weight loss and each refrigeration-needing crop has its own `unrefrig_mult` (tomato 3.8x, spinach 25x, cauliflower 5x, mango 4.7x) instead of one global 3x. New rates (cooled): tomato 0.013%, spinach 0.03%, cauliflower 0.03%, mango 0.015% per hour; uncooled 0.05%, 0.75%, 0.15%, 0.07%. Old rates were 1.4% to 3.5% per hour. Onion and potato are unchanged (no source) and likely too high.
- `SPOIL_UNREFRIG_MULT` (3.0) is now only the fallback for a crop with no multiplier; `spoilage_params(unrefrig_mult=...)` still forces one multiplier on every crop.
- Effect (synthetic, 100 farmers, 18 scenarios): ILO's average lead over the best baseline +2.5% -> +5.6%. Cold chain demo: ILO 59,099, tied with rational Neighbour pooling, +1.1% over behavioural. Bihar example unchanged.
- Plans can now send one trip to two mandis more often, so `advisor.driver_sheet` gives each dropoff its own kg only when the plan recorded it (else `null`; one dropoff still gets the full load). The sheet test was loosened accordingly.
- Results in `ALGORITHM_AND_RESULTS_V2.md` sections 20 to 23 were produced with the OLD rates and are not re-run, except the comparison in section 24.
- Not done: a separate quality/rejection-loss parameter.

## SMS and WhatsApp updates, phone numbers (Nov 2026)
Farmers add a phone number in the farmer app, confirm it with an SMS code, and then get their plan updates by SMS and WhatsApp. The admin console can clear every stored number (type-to-confirm) or one farmer's.
- Number capture: typed and confirmed by a 6-digit code, because a web page cannot read the SIM number or open a "choose your number" picker (only a native Android app can). Codes: 10 minutes, 5 guesses, one per minute and 5 per hour per farmer, stored only as a keyed digest.
- Sending: `backend/notify.py` (stdlib only). `SMS_PROVIDER` / `WHATSAPP_PROVIDER` default to `dry`, which logs instead of sending, so everything works with no account. Adapters for Twilio, MSG91 and the WhatsApp Cloud API are written from the providers' API descriptions and are NOT yet run against the live services.
- When: on publish, farmers with a number whose card changed (everyone with a number if nothing was published before), after the publish response so providers cannot slow or break it; plus the current plan once when a farmer confirms a number. Messages are one line in en, te, hi or ta (the language the farmer had selected).
- Admin: phone section in Farmer access (masked numbers, per-farmer clear, reset all, provider status, recent sends). `DELETE /farmers/phones?confirm=true`.
- Tables `farmer_phones`, `phone_otps`, `notification_log` are created on start (`CREATE TABLE IF NOT EXISTS`); `POST /reset` clears them.
- README refreshed against the code: ninth scenario (Tamil Nadu, Vellore), farmer-app and phone-number sections, missing routes, env vars and files, a fixed layout block, and stale notes removed (CI exists; the admin console does ask for the token).
- Tests: `backend/tests/test_phones.py` (pure tests need no database; the API tests need `DATABASE_URL`).

## Spoilage-first mode (Oct 2026)
A second, selectable aim for the optimizer. `POST /plan/compute?mode=spoilage[&max_value_sacrifice=0.10]` (and the "Optimise for" selector on the Plan tab) returns the plan with the least produce spoiled in transit whose farmer value is within `max_value_sacrifice` of the normal net-return plan. The default (`mode=returns`) is unchanged to the last digit.
- Minimising spoilage alone is degenerate (haul nothing and nothing spoils), so it is a trade-off: `run_ilo_v3_spoilage_first` runs ILO v3 at several `spoil_weight` values (extra charge per rupee of spoiled produce, applied in `_eval_trip` scoring and in plan ranking), then picks the lowest-spoilage plan inside the value budget. `ilo_meta["spoilage_first"]["frontier"]` lists every run.
- Cost: about 4 planner runs, so it is several times slower than the default. Lower spoilage usually means hauling less (more produce sold at the farm gate); the Plan tab says so.
- Tests: `backend/tests/test_spoilage_mode.py`.

## Frontend rewrite: React + TypeScript + Vite (Oct 2026)
Replaced the vanilla-JS frontend with a Vite/React/TS app (see `frontend/README.md`). Same look and class names; map engine kept as ES modules behind a typed wrapper. UX: run progress, backend-down banner, toasts, inline validation, stale-plan banner, sortable pools, keyboard shortcuts. Backend untouched. Vitest tests for the simulation engine.

## ILO v3.1: fleet-aware planning, road distance, price impact, break-even and stress tests (Oct 2026)
Five additions to ILO v3, from a review of its weaknesses (`ALGORITHM_AND_RESULTS_V2.md`, section 22). Everything new is
opt-in or additive: with default arguments the planner uses the same distances and prices as v3, and the core
trip and dispatch rules are unchanged. What does change by default is listed first.
- **Changed by default.** ILO v3 now reports value-gain sharing as `per_farmer_net` (own farm-gate value plus a kg-share of
  the trip surplus; never below the doorstep price). The pro-rata split and the `per_farmer_value_gain_sharing` key and
  `farmers_worse_off_under_prorata_split` stat are gone from ILO v3 results; baselines and ILO v2 still use pro-rata.
  The set-partitioning step is fleet-aware (see below) and the old fleet-blind plan competes as a fallback, so final
  value never drops. Every dispatched trip carries `breakeven`, and `meta["discount_stress"]` is added.
  Dispatched pools gain a `dispatch_hr` field.
- **Fleet-aware set partitioning** (`ilo_v3.py`). Columns are (trip, vehicle class, start slot); each (class, 15-minute cell)
  has at most as many busy trips as vehicles. Vehicle choice moves into the MILP; `assign_fleet` honours pinned
  vehicle/start hints (`pool_hints`). LP duals give the value of one extra vehicle per class
  (`meta["fleet_aware"]["shadow_value_per_extra_vehicle"]`). `fleet_aware=False` restores the old behaviour.
- **Road-distance model** (`logistics_lib_v2.py`). `haversine()` now returns `ROAD_CIRCUITY` x straight-line km (default 1.0 = legacy).
  Set with `set_road_circuity(k)`, the `road_circuity(k)` context manager, `FARMROUTE_ROAD_CIRCUITY`, or
  `POST /plan/compute?road_circuity=1.3`. Radius thresholds are road-km. `calibrate_circuity.py` fits k from real road
  distances. The default is NOT changed, so existing benchmarks are comparable; set a calibrated value for real use.
- **Price impact** (`price_impact.py`, off by default). Concave volume-dependent mandi revenue in the MILP (tranche variables, no
  binaries), in the market-allocation LP, and in baseline revenue. `run_ilo_v3(price_impact=..., true_price_impact=...)`
  separates what the planner believes from how plans are scored. `estimate_price_flexibility()` re-estimates eta from
  Agmarknet CSVs. Default eta values are lower bounds from within-mandi regressions.
- **Break-even and discount stress** (`ilo_v3.py`). Per trip: break-even doorstep Rs/kg per crop, cushion %, break-even discount.
  Per plan: gain if the true farm-gate discount were 5/10/20/30/35% instead of the assumed one, with and without a
  live-quote dispatch rule.
- **Monte Carlo stress test** (`stress.py`, off by default: `run_ilo_v3(mc_draws=100)`). Replays the finished plan through the simulator under travel,
  readiness and price shocks. Reports mean, P5, P(loss), per-trip `p_beat`. `mc_min_prob` can withhold fragile trips, but
  in tests this lowered the mean and the P5, so it stays off.
- New files: `price_impact.py`, `stress.py`, `calibrate_circuity.py`, `experiments_v3_1/` (the scripts behind the numbers),
  tests `test_road_circuity.py`, `test_price_impact.py`, `test_breakeven.py`, `test_monte_carlo.py` and two fleet tests in
  `test_ilo_v3.py` (20 new tests, plus 6 for the spoilage and soft-capacity items below).
- **Spoilage sensitivity** (`logistics_lib_v2.spoilage_params()`, `SPOIL_UNREFRIG_MULT`, `SPOIL_CAP`, defaults unchanged;
  `experiments_v3_1/spoilage_sensitivity.py`; results section 23). ILO's ranking is stable across spoilage variants, but doubling
  the hourly rate cuts the gain by 25% and changes about half the hauled farmers. `monte_carlo_stress(spoilage_rate_sd=...)` adds
  a per-crop rate shock (default 0). 2 more tests (22 new in total).
- **Trip-structure measurement** (no planner change; `experiments_v3_1/trip_structure_*.py`, results section 24). Multi-mandi trips and the
  top-3 mandi cut: not worth building. Mixed-crop consolidation: about 0 to 5% end-to-end, noisy. Mandi capacity binds in 3 of 5
  presets and tripling it adds 15% to 39%; a soft capacity via price impact is the proposed next step.
- **Soft mandi capacity** (`PriceImpact(capacity_multiple=M)` / `PriceImpact.soft(M)`, off by default; results section 25). Also fixes a flaw: with price impact, each
  trip was offered at one mandi only; `run_ilo_v3(markets_per_trip=...)` now offers up to 3 (default 3 with price impact, else 1, so
  default behaviour is unchanged). Result: planning with soft capacity is not reliably better (6 of 10 cells up to +48%, 4 down to
  -9.7%) because the SP and the simulator disagree by 10% to 14%; use it for scoring, not planning. The capacity assumption alone moves reported gain by
  +7% to +26% in 8 of 10 cells. 4 more tests (26 new in total).
- Not done, by decision or because it needs data: OSRM road matrix (deferred to the end), mixed-crop and multi-mandi trips,
  calibrated spoilage rates, a price-history backtest, real farm-gate quotes.

## ILO v3, behavioural baselines and regional presets (Oct 2026)
- ILO v3 (`backend/ilo_v3.py`) is now the recommended plan. It hauls only what beats the farm-gate price, merges farmers heading to the same mandi into full trucks, picks trips with an exact 0/1 solver, and returns the best of its own plans and every baseline under identical accounting. ILO v2 is still computed as a legacy reference.
- The two comparison baselines are now behavioural farmer baselines (spot-hired truck to the nearest mandi if within 40 km and 10% above the trader's offer, otherwise sell at the farm gate). The old versions, the rational variants and a farm-gate-only reference are returned under `realistic_baselines` and are not shown in the UI.
- All approaches now share one accounting: the empty return leg is charged and spoilage counts from pickup.
- UI: the headline is farmer value (net return plus farm-gate sales); farm-gate sellers are slate on the map, never red; the Plan tab says when ILO recommends a simpler plan.
- Bihar preset rebuilt (Dec 2025 to Feb 2026, 8 mandis, placeholder capacities flagged). Four regional presets added: Karnataka (Bengaluru), Uttar Pradesh (Aligarh), Maharashtra (Junnar), Madhya Pradesh (Indore), built by `real_data/build_regional_presets.py`.
- Cold chain no longer shows a win: with spoilage counted from pickup, ILO and Proximity Pooling tie.
- Details and results: `ALGORITHM_AND_RESULTS_V2.md`, sections 19 to 21.

## Frontend redesign (Oct 2026)
- New UI: "painted mandi rate board" design system (see `DESIGN.md`, `PRODUCT.md`). Scenarios tab is the new first screen; one click loads a scenario, computes the plan and opens the map.
- Plan tab is now a ledger (revenue less transport = net return) with a harvest-sold bar and a pool table that stacks into cards on phones.
- Compare tab replaces the two Chart.js charts with one scoreboard that pairs net return with produce sold and shows a signed delta against ILO.
- Map tab is a workspace: toolbar, map, transport bar, stage rail, and a Story/Details side panel. Vehicles use a curated colour palette (the old hue-hash gave vehicles 1, 3 and 4 near-identical olives); farmers are coloured by their vehicle.
- Basemap: built in-process (limewash ground plus lat/lng grid, always renders offline) with raster tiles on top. Tiles are Esri gray canvas by default and configurable in `frontend/config.js`. CARTO's keyless tiles were tried and dropped: they are watermarked "API KEY REQUIRED" from Aug 2026.
- Fixed: the page scrolled itself on every story step on phones; map init no longer waits on tiles (it hung offline); "Only 100% of produce..." warning showed even at 100%; "Vehicles used" is no longer highlighted as a best value.
- Fonts (Barlow, Barlow Condensed, and Noto Sans for the rupee sign only) are self-hosted in `frontend/vendor/fonts/`.
- `frontend/vendor/chart.umd.js` is still shipped but no longer loaded.

## Earlier setup fixes (pre-redesign)

- `backend/requirements.txt` was missing `numpy` and `scipy`, which
  `algorithms_v2.py` needs. Without them, `/plan/compute` failed with a
  misleading *"algorithms_v2 module is not present"* error even though the
  file was right there — the module existed but couldn't import its own
  dependencies. Fixed, and re-verified with a clean venv holding only what's
  now in `requirements.txt`.
- `main.py` had no CORS middleware, so the browser blocked every request
  from `frontend/` to the API regardless of the above. Added.
- The frontend (`index.html` + `app.js`) was built against a different,
  simpler data shape than the backend actually serves (free-text crop/
  vehicle-type names, a `location` string, one crop per market row) instead
  of the real one (lat/lng, the 6 fixed crops and 7 fixed vehicle types from
  `logistics_lib_v2.py`, `ready_hr`/`deadline_hr`, and a market's `price`/
  `capacity_kg` as multi-crop dicts). Every form and table was rewritten to
  match the real API — this is why nothing you entered ever showed up
  before. The dashboard/comparison rendering code was already correct and
  is untouched.
- There were two copies of `algorithms_v2.py` and `logistics_lib_v2.py` (a
  top-level `algorithm/` folder and `backend/`) — identical, but confusing
  about which one the running server actually used (it's always the one
  in `backend/`, since that's what `main.py` imports from its own
  directory). Removed the duplicate; `benchmark_v2.py`, which isn't used by
  the API, now lives in `backend/` alongside the files it imports.
- The delivered zip had a stale `fpo.db`, `__pycache__/`, and a `.git/`
  folder in it. Removed, and added a `.gitignore` so they don't creep back in.

Everything above was tested by actually running it: a clean-venv
`pip install` + `verify_setup.py` pass for the backend, and every
`POST`/`GET` call the rewritten frontend makes was replayed against the
running server with `curl` to confirm the shapes match end to end
(including a real `/plan/compute` run).

## Map & simulation tab: how it was built

An interactive map and playback simulation of whichever plan was last
computed, built on top of the existing algorithm output — it adds no new
optimization logic and changes no existing behavior on the other three tabs.

- **Stack**: MapLibre GL JS for the base map/camera, deck.gl (core, non-React
  API) for every data layer, both vendored locally under `frontend/vendor/`
  as plain `<script>` tags — no React, no bundler, no build step, matching
  how `frontend/app.js` and `vendor/chart.umd.js` already work. Adding React
  here would have meant adding a bundler too just for one tab.
- **Backend**: a new `GET /plan/{id}/visualization` endpoint (see
  `backend/README.md`) reshapes the same stored plan into
  farmers/vehicles/markets/routes/simulation-events — it's a pure adapter
  over what `/plan/compute` already produces, in `backend/visualization_adapter.py`.
  Nothing about `/plan/compute` or the three algorithms changed, except that
  `run_ilo_v2` is now also called with `return_trace=True` to additionally
  capture (not recompute) the per-market allocation edges it already
  produces internally, for an exact per-market breakdown in the "why" panel.
- **What's honest about it, on purpose**: this project has no road network or
  vehicle depot locations, so routes are drawn as straight lines between real
  stop coordinates (never presented as real roads), and per-stop timestamps
  are a *deterministic reconstruction* using the algorithm's own timing
  constants — not a literal replay of its internal bookkeeping. Per-market
  received-kg is only ever shown when it's exactly derivable (always for
  Individual Transport, only for Our System/ILO, never for Proximity
  Pooling, which has no persisted per-market split) — never estimated or
  fabricated. See the module docstring in `visualization_adapter.py` for the
  full list of these boundaries.
- **Base map tiles**: the 2D basemap originally used MapLibre's keyless demo style (replaced, see the redesign entry above), which needs the
  *browser* to reach the internet. If it can't (offline, or that specific
  host is unreachable), the map still fully works — farmers, vehicles,
  markets, routes, the simulation, selection, and comparison mode all
  render and behave identically — just on a plain background instead of
  real geography. This was deliberately tested both ways (see below).
- **3D** is a pitched camera + simple extruded columns sized by pickup
  quantity, not detailed 3D truck models — kept intentionally cheap per the
  project brief this was built against.
- Tested with a real headless-browser run (Playwright + a cached Chromium)
  driving the actual page end to end against the actual backend: seeding a
  demo scenario through the UI, computing a plan, loading it into the map,
  clicking through all 7 presentation stages, playing/pausing/resetting/
  scrubbing the simulation, clicking a rendered marker to confirm
  MapLibre+deck.gl picking resolves to the right object in the details
  panel, switching algorithms, and toggling compare mode on and off — with
  zero unexpected console errors. The backend adapter itself has a
  dedicated test (`backend/verify_visualization.py`, described below) plus
  an additional stress run across 5 random seeds at 60 farmers each
  confirming no two of the same vehicle's reconstructed trips ever overlap
  in time, and a scale check at 800 farmers / 20 vehicles for response time.
