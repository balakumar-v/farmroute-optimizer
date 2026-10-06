# Changelog

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
