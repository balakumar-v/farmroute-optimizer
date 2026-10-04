# Farmroute Optimizer

Farmer produce-pooling / market-allocation decision layer: FastAPI + SQLite
backend, plain HTML/JS frontend.

## Run it

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Then open `frontend/index.html` in a browser (double-click it, or serve the
`frontend/` folder with any static server). The API base field at the top
defaults to `http://localhost:8000` — leave it as-is if you used the command
above.

Order of use: add a few farmers, vehicles and markets on the **Data entry**
tab first (all three need at least one entry), then use **Recommended plan**
or **Comparison** to call `/plan/compute`. The **Map & simulation** tab reads
whatever plan you last computed on those two tabs — compute one first, then
switch over and click "Load latest plan".

## Map & simulation tab (new)

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
- **Base map tiles**: the 2D basemap uses MapLibre's free, keyless public
  demo style (`https://demotiles.maplibre.org/style.json`), which needs the
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


## What was actually wrong

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

See `backend/README.md` for the full endpoint reference.
