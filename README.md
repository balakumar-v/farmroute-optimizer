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

Not every scenario is a win. On the synthetic Cold chain scenario ILO and Proximity Pooling tie (₹59,099 against ₹58,473 behavioural and ₹59,099 rational). With spoilage counted from pickup, the refrigeration effect is small at those distances, and the scenario's blurb says so. Treat all of these as single runs on synthetic farmers.

## Live demo

https://farmroute-optimizer-frontend.onrender.com/

Farmer app (installable PWA): https://farmroute-web.onrender.com

The admin console and the farmer app are hosted on Render and the database is Neon Postgres. A free Render service sleeps when idle, so the first request after a pause can take a while to wake up.

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
| Admin console | Render static site, root directory `frontend/` | Build `npm ci && npm run build`; publish `dist`; set `VITE_API_BASE` to the backend's public URL |
| Farmer app | Render static site, root directory `farmer-app/` | No build; publish `.`; set `FARMER_API` in `farmer-app/config.js`; add `/sw.js` header `Cache-Control: no-cache` (see `farmer-app/README.md`) |

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
| `ROUTING_PROFILE` | Routing profile: OpenRouteService `driving-car` or `driving-hgv`; OSRM `driving` | provider default |
| `ROUTING_USER_AGENT` | User-Agent sent to the routing servers | `farmroute-optimizer/1.0 (student project)` |
| `ROAD_PLANNING` | `off` to plan on straight lines without a road matrix | `auto` |
| `ROAD_MATRIX_MAX_POINTS` | Largest scenario (farmers + mandis) that gets a road matrix | 200 |
| `FARMROUTE_ROAD_CIRCUITY` | Fixed road-km / straight-km factor when road lookups are off | 1.0 |
| `SMS_PROVIDER` | How SMS goes out: `dry` (log only), `twilio` or `msg91`. Needs that provider's credentials (see `backend/notify.py`). | `dry` |
| `WHATSAPP_PROVIDER` | How WhatsApp goes out: `dry`, `meta` (WhatsApp Cloud API) or `twilio`. | `dry` |
| `DEFAULT_COUNTRY_CODE` | Digits added to phone numbers typed without a country code | `91` |
| Provider credentials | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_SMS_FROM`, `TWILIO_WHATSAPP_FROM`; `MSG91_AUTH_KEY`, `MSG91_OTP_TEMPLATE_ID`, `MSG91_UPDATE_TEMPLATE_ID`, `MSG91_VAR`; `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`, `WHATSAPP_TEMPLATE`, `WHATSAPP_API_VERSION`. Which ones apply depends on the provider chosen; a missing one is shown in the admin console and fails sends, it does not stop the server. | none |
| `NOTIFY_DEMO_SHOW_OTP` | `on` returns the SMS code in the API response while `SMS_PROVIDER=dry`, so a demo can be completed without sending SMS (the farmer app then shows the code on the code screen). Never use with real farmers. | `off` |

Set `ALLOWED_ORIGINS` (include the farmer app's origin), `ADMIN_TOKEN` and `FARMROUTE_SECRET` in production: the defaults accept requests from any site and leave the admin routes open.

When the backend has `ADMIN_TOKEN` set, the admin console asks for it the first time a request is refused with 401, keeps it in that browser (`localStorage`, key `farmroute.adminToken`) and retries. Experimental `ILO_*` switches (for example `ILO_ENRICH`, `ILO_COLGEN`) exist for benchmarking and are off by default; they are not deployment settings.

### Farmer change requests

A farmer who has a published plan can ask the FPO for a different quantity, ready time or deadline from the farmer app (round chat button, bottom right). The farmer's plan never changes by itself:

1. The farmer types a message ("100 kg less, ready 2 hours later") or, if the language model is off or unreachable, fills a small form. A small model on OpenRouter turns the message into a JSON change request (field, `set`/`shift`/`scale`, number). It does not write SQL, does no arithmetic and never sees an id, phone number or location; it sees only that farmer's own three current values, fetched by a fixed query.
2. The backend validates the JSON (Pydantic), works out the new absolute values and checks them (quantity above 0 and under `CHANGE_MAX_QTY_KG`, ready before deadline, and so on). The farmer sees the result in plain numbers, built by code, and taps Confirm. Only then does it become a pending request.
3. In the console's **Requests** tab the operator sees the request next to what the farmer wrote, previews it (a re-plan with the change applied in memory, listing every farmer it would move and how many of them did not ask) and approves or rejects. Approving one or several requests recomputes once, saves the new values and publishes, so only farmers whose card changed are messaged. It is refused with 409 if the published plan changed since the preview, or if a farmer's details changed since they asked.
4. The farmer sees the answer under "Your requests" in the app, and the new card.

Rules: one live request per farmer (a newer one replaces the older), drafts expire after an hour and pending requests after `CHANGE_REQUEST_TTL_H`, the operator can close requests (`PUT /change-window`) when dispatch starts, and the farmer id always comes from the token. Settings are in `backend/.env.example`; without `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` the form is used. Code: `backend/change_requests.py`, `backend/chat_llm.py`, tests in `backend/tests/test_change_requests.py`, `frontend/src/views/RequestsView.tsx`, `farmer-app/app.js`.

## The app

| Tab | What it shows |
|---|---|
| Scenarios | Nine ready-made scenarios. One click loads the data, computes the plan and opens the map. |
| Data | The farmers, vehicles and markets the optimizer sees. Add rows by hand. |
| Plan | The ILO plan as a ledger: net return, produce not hauled and sold at the farm gate, farmer value, harvest sold, spoilage, and one row per pool. If ILO found nothing better than a simpler plan, the page says which plan it recommends instead. Under it, **Farmer access**: publish the plan to farmers, issue PINs, print cards for farmers without a phone, and manage farmers' phone numbers (see below). |
| Farmer access | PINs (issue, view who has one, re-issue), publish the plan to farmers, printed cards, phone numbers and recent messages. |
| Requests | Change requests from farmers (a new quantity or time): what they wrote, what it means, a preview of who a re-plan would move, then approve or reject. |
| Compare | ILO against two behavioural baselines, with farmer value and produce sold side by side, a delta against ILO, and a full breakdown table. |
| Map | The plan on a map: 7 presentation stages, a playable timeline, a step-by-step story, details for anything you select, compare mode, 3D, chase camera, and a full-screen walkthrough. Farmers who sell at the farm gate are slate; farmers who wanted a truck and got none are red. |

### Scenarios

Three synthetic scenarios, each built to isolate one mechanism, and six built on real mandi data.

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
| Tamil Nadu, around Vellore, Jan to Feb 2026 | 27 / 6 / 8 | Tomato, onion, potato. Small yards, so fewer farmers; most yards are farmers' markets (Uzhavar Sandhai) with retail-like prices |

In the real-data scenarios the mandi locations, prices and daily arrivals come from Agmarknet via the India Data Portal. The farmers and the fleet are synthetic, because no farmer-level data exists. Each scenario's "About the data" note lists what was cleaned and which counts are assumptions.

## Phone notifications (Web Push)

Farmers can get a notification on their phone when a published plan changes for them (approving a change request re-plans and publishes, so it triggers this too). One-time setup on the backend:

1. `cd backend && python tools/generate_vapid.py` prints `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` and `VAPID_SUBJECT`.
2. Set those three environment variables on the Render backend and redeploy (`pywebpush` is in `requirements.txt`).
3. Farmers tap **Notify me when my plan changes** in the farmer app. Sending is a background task after publish; each attempt is written to `notification_log` with channel `push`; a subscription the push service reports gone (404/410) is deleted. Without the keys nothing is sent and the button is hidden. Keep the private key: changing it makes every farmer turn notifications on again.

Routes: `GET /farmer/push/key` (public), `GET /farmer/push`, `POST /farmer/push/subscribe`, `POST /farmer/push/unsubscribe` (farmer login). The publish response has `push_updates`.

## Farmer app, phone numbers and messages

Farmers do not use the admin console. They use `farmer-app/`, a phone-first installable site (PWA) in English, Telugu, Hindi and Tamil with read-aloud:

- Log in with the farmer ID and PIN the FPO issued. The operator publishes one plan; each farmer sees only their own card (truck time, where the produce goes, an honest payout estimate).
- Farmers without a phone get a printed card: in **Farmer access** the operator picks a language and prints cards (browser "Save as PDF" gives a file).
- **SMS and WhatsApp updates.** After login a farmer with no stored number is offered to add one. A web page cannot read the SIM number, so the farmer types it, gets a 6-digit code by SMS, and types the code back; only then is it stored. When the operator publishes a plan, each farmer with a number whose card changed gets one SMS and one WhatsApp message (everyone with a number on the first publish), and a farmer who confirms a number later gets the current plan once. The farmer can delete their number from the card; the operator can clear one farmer's number or every number (type-to-confirm) in **Farmer access**, after which farmers are asked again.
- Sending is **off by default**: `SMS_PROVIDER` and `WHATSAPP_PROVIDER` are `dry`, which logs messages on the server instead of sending. Twilio, MSG91 (SMS) and the Meta WhatsApp Cloud API have adapters in `backend/notify.py`, written from the providers' API descriptions and not yet run against the live services. Messages are sent after the publish response, so a provider failure never blocks publishing; each attempt is listed under "Recent messages" (no numbers or text are stored in that log).
- Limits: codes expire in 10 minutes, allow 5 wrong guesses, and can be requested once a minute and 5 times an hour per farmer. The message language is fixed when the number is registered. India SMS to real farmers needs DLT-registered templates and WhatsApp needs approved templates; see `backend/notify.py`.

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

What these showed (synthetic scenarios, few seeds; `docs/ALGORITHM_AND_RESULTS_V2.md` section 22 has the tables and caveats):
- Planning with straight-line distances when roads are 1.4x longer cost about 17% of the gain and left 15 of 65 trips below the farm-gate price. Planning with the right factor cut that to 2 of 58. Underestimating the factor by 0.2 costs about 2%; overestimating by 0.2 costs about 14%.
- Fleet-aware planning adds 0 to 2.5% of final value; the gain is small because the synthetic fleet is small relative to the farmers. It also prices vehicles: one extra reefer was worth about Rs 4.7k in one scenario.
- Price impact: with elasticities estimated from your Agmarknet files (lower bounds), scoring with price response cuts reported gain by about 17%. Planning with it adds nothing measurable at those elasticities (-2%, inside model error) and about +7% when the true response is 3.5x stronger. Wrong beliefs hurt: assuming 2x the truth gave +0.1%.
- Farm-gate discount: assuming 20% to 30% and using the live-quote rule had a worst-case regret of 8% to 11% across true discounts of 5% to 35%. Without the rule, assuming 30% lost money when the true discount was 5%.
- Trip structure: multi-mandi trips and the top-3 mandi cut are not worth building; mixed-crop trips add about 0 to 5% and are noisy. Mandi capacity is the lever: it binds in 3 of 5 presets, and tripling it adds 15% to 39% (section 24). Capacity is a weak input, so report capacity sensitivity with any gain.
- Soft capacity (section 25): scoring with a soft mandi capacity (volume up to 3x a normal day at falling prices) instead of a hard cap raises reported gain by 7% to 26% in 8 of 10 cases. Planning with it is not reliably better than ignoring price impact (6 of 10 cases better, 4 worse by up to 10%), so use it for scoring and sensitivity, not planning.
- Spoilage (earlier, with the old assumed rates): ILO beat every baseline under every spoilage variant tried (lead 4% to 9%), but doubling the hourly spoilage rate cut the gain by 25% and changed about half of the hauled farmers; the refrigeration multiplier mattered less (3 -> 6: -12%). The per-crop hourly rates are the parameter worth measuring. **Update, Nov 2026:** tomato, spinach, cauliflower and mango now use rates from a literature review of weight loss (below), with a per-crop uncooled multiplier. With them, on 100 synthetic farmers (18 scenarios per rate set) ILO's lead over the best baseline rose from +2.5% to +5.6% on average (range +2.6% to +13.1%), because lower spoilage makes longer hauls and pooling pay. The Bihar example above is unchanged (it grows onion and potato only).
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
  phones.py                  farmer phone numbers: code check, storage, who gets a message on publish
  notify.py                  phone-number parsing, codes, message text (en/te/hi/ta), SMS and
                             WhatsApp providers (dry-run by default); no database, easy to test
  roads.py                   road distances (OSRM / OpenRouteService), matrix and route-geometry cache
  price_impact.py            volume-dependent mandi price model and eta estimator (off by default)
  stress.py                  Monte Carlo replay of a finished plan; withhold_fragile()
  calibrate_circuity.py      fit the road-circuity factor from real road distances
  logistics_lib_v2.py        data model: 6 crops, 7 vehicle types, costs, spoilage
  visualization_adapter.py   reshapes a stored plan for the map (no recomputation)
  integrated_milp.py, milp_benchmark.py   exact MILP ground truth for small instances
  database.py, schemas.py    Postgres storage (psycopg) and request/response models
  tools/                     run by hand: verify_*.py (endpoint / map / notification checks), benchmark_*.py
                             (ILO v3 vs baselines, scale), calibrate_circuity.py, generate_vapid.py
  experiments/v3_1, v4       scripts and raw results behind the reported numbers (each has its own README)
  tests/                     dispatch, baselines, ILO v3, roads, advisors, upload, auth, phones, visualization
  real_data/                 Agmarknet pipeline, regional preset builder, data (own README)
farmer-app/                  the farmers' installable PWA (own README); no build step
frontend/                    React + TypeScript + Vite admin console (own README)
  src/                       views, state, API client, scenario data (lib/scenarios.ts), map engine (vis/),
                             Farmer access panel (components/FarmerAccess.tsx), printed cards (lib/printCards.ts)
  index.html, package.json, vite.config.ts
  legacy/                    the pre-React frontend (not built or loaded). legacy/app.js is still the preset source
                             that backend/real_data reads (SCENARIOS), so keep it until presets move to a data file
.github/workflows/ci.yml     CI: backend tests, and frontend build and tests, on every push
docs/                        EXTENDING.md (where to plug in new views, prices, objectives, constraints, presets),
                             ALGORITHM_AND_RESULTS_V2.md (design history, benchmarks, assumptions), MILP_GROUND_TRUTH.md,
                             PRODUCT.md and DESIGN.md (admin UI), whatsapp/ (setup guides); docs/README.md is the index
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
| `GET /plan/{id}/payout`, `/payout/{farmer_id}` | Per-farmer payout statements: planned take-home, downside range, operator fee line (totals plus fee reconcile to the plan value) |
| `GET /plan/{id}/fairness` | Who gains and how evenly: share gaining, gain spread, Gini, bottom-fifth share |
| `GET /plan/{id}/diff/{old_plan_id}` | Which farmers a re-plan changed, and why |
| `GET /plan/{id}/driver-sheet/{vehicle_id}` | One vehicle's trips in order, with planned times, kg and map links |
| `POST /sensors/reading`, `GET /sensors/readings` | Store ESP32 temperature and humidity readings |
| `POST /reset` | Clear all data (including phone numbers and the message log) |
| `POST /farmers/pins`, `POST /farmers/{id}/pin` | Issue farmer PINs (shown once, stored hashed). `pins` issues for everyone without one; `?only_missing=false` re-issues for all |
| `GET /farmers/pins` | Admin: per farmer, whether a PIN exists, when it was issued and whether they are locked out. Never returns a PIN or hash |
| `POST /plan/{id}/publish`, `GET /published`, `GET /published/cards`, `DELETE /published` | Choose the one plan farmers can see (or hide it), and read the published cards. Publishing also reports `phone_updates` and sends the SMS / WhatsApp messages afterwards |
| `POST /farmer/login` | Farmer ID + 6-digit PIN, returns a 12-hour token |
| `GET /farmer/me` | The logged-in farmer's own card from the published plan, with `phone: {registered, masked}` (farmer token only) |
| `GET /farmer/phone`, `POST /farmer/phone/start`, `POST /farmer/phone/verify`, `DELETE /farmer/phone` | The farmer's own number: status, text a code, confirm it, delete it (farmer token only) |
| `GET /farmers/phones` | Admin: counts, masked numbers, SMS / WhatsApp provider status, recent sends. Full numbers are never returned |
| `DELETE /farmers/phones?confirm=true`, `DELETE /farmers/{id}/phone` | Admin: clear every stored number (needs `confirm=true`), or one farmer's |
| `POST /farmer/chat`, `POST /farmer/requests/{id}/confirm`, `.../withdraw`, `GET /farmer/requests` | Farmer asks for a change: what the server understood (nothing changes yet), confirm or withdraw, and that farmer's own requests (farmer token only) |
| `GET /change-requests`, `POST /change-requests/preview`, `.../approve`, `.../{id}/reject`, `GET/PUT /change-window` | Operator: review, preview, approve (one recompute and publish) or reject farmer change requests; open or close requests |

`POST /plan/compute` options:
- `road_distances` (default `true`): plan on measured road distances between every farmer and mandi (OpenStreetMap via OSRM, cached in the database). If road data is unavailable it falls back to straight lines. The distance model used is stored with the plan as `distance_model`.
- `road_circuity=1.3`: plan and score with road distance = 1.3 x straight line instead (400 outside 1 to 3).
- `mode` = `returns` (default, maximise farmer value) or `spoilage` (least spoiled produce within `max_value_sacrifice`, default 0.10, of the best returns plan; slower).

`/plan/compute` returns `integrated_logistics_optimization`, `individual_transport` and `proximity_pooling`, each with `pools` and a `summary` that includes `net_return_incl_farmgate`, plus `distance_model` and `realistic_baselines` as above. Crops: `tomato`, `onion`, `potato`, `cauliflower`, `mango`, `spinach`. Vehicle types: `mini_pickup`, `van`, `reefer_van`, `truck_2t`, `reefer_2t`, `truck_5t`, `reefer_5t`.

### Roles and access

| Who | Gets in with | Can use |
|---|---|---|
| Admin (operator) | `ADMIN_TOKEN` as a bearer token | every route except the `/farmer/` ones |
| Farmer | farmer ID + PIN, then a signed token | `/farmer/` routes only: their own card, phone number and change requests, nothing of any other farmer's |
| Anyone | nothing | `/docs`, `/openapi.json`, `POST /farmer/login` |

Admin access is default-deny: any route outside `/farmer/` requires the token, including ones added later. If `ADMIN_TOKEN` is not set the admin routes stay open (local development) and the farmer routes return 503, so farmers cannot be reached on an open backend by accident. Setting `ADMIN_AUTH=off` makes that choice on purpose; see the warning in the env table. A farmer's token cannot call any admin route, and the admin token is not accepted as a farmer token.

Farmers only see a plan an operator has published. Publishing builds one card per farmer holding only that farmer's own crop, quantity, status, payout lines and trip details (no other farmer's id, and no trip revenue or cost). Re-publishing marks which farmers' cards changed and why. Phone numbers are stored as typed-and-confirmed E.164 strings, and only masked forms (`+91******3210`) are returned to the admin console or the farmer app. PINs are stored as salted scrypt hashes, five wrong PINs lock that farmer for 15 minutes, and issuing a new PIN logs out the old sessions.

Limits: someone who knows a farmer ID can lock that farmer out for 15 minutes (an admin issuing a new PIN clears it); there is no per-IP rate limit because behind Render's proxy all callers share one address; there is one shared admin token, not per-operator accounts. Do not put real farmer details on a deployment before `ADMIN_TOKEN` is set.

## What is real and what is not

- Real: mandi coordinates (the portal's own, never geocoded or invented), prices and reported daily arrivals.
- Synthetic: every farmer, lot size, ready time and the fleet. Farmer counts (about 60 pickups per regional preset, a typical collection round for one FPO) and vehicle sizes are modelling choices.
- Assumed: the farm-gate price (20% under the median mandi price), the baseline behaviour parameters, and mandi capacity. Capacity is the median reported daily arrival, and where one value repeats on over 70% of days it is a reporting default, so it is raised to the lower quartile of that state's other mandis for the crop (never lowered).
- Dropped, not guessed: mandis with no coordinates (Maharashtra 5, Madhya Pradesh 27), implausible price or arrival units, and mandi-crop series absorbing under 1 t per day.
- Plans use measured road distances when OSRM is reachable, and straight lines otherwise (`distance_model` says which). The map draws real-road geometry once it has been fetched and straight lines until then. There is no depot data.
- Per-stop times are reconstructed with the algorithm's own timing constants, not replayed from its internals.
- Phone numbers, when farmers add them, are the farmers' own; SMS and WhatsApp are not sent until you configure a provider (default `dry`).
- Sensor readings are stored only. The planner cannot yet recompute spoilage from live readings, and the UI never simulates sensor data.

## Map tiles

The map always renders a limewash background with a lat/lng grid, so it works offline. Street tiles load on top when the internet is available (Esri gray canvas by default, no key). To use another provider, such as CARTO with a free key, edit `frontend/src/config.ts`.

## Tests and benchmarks

```bash
cd backend
pip install -r requirements-dev.txt
export DATABASE_URL=postgresql://...   # the endpoint tests need a Postgres; without it they are skipped
python3 -m pytest tests                # the full run takes several minutes; CI runs it on every push

python3 tools/verify_setup.py                # endpoint sanity check against your DATABASE_URL (it ends by resetting the data)

python3 tools/benchmark_ilo_v3.py grid      # win/tie/loss map across scenarios
python3 tools/benchmark_ilo_v3.py robust    # planner assumes 20% discount, truth differs
python3 tools/benchmark_ilo_v3.py margin    # planner margin sweep
python3 tools/benchmark_ilo_v3.py bihar     # the Bihar preset
```

The phone-number tests in `tests/test_phones.py` that need no database (number parsing, codes, message text, provider requests, who is messaged) run anywhere; its API tests need `DATABASE_URL`. Use a throwaway database for tests: the endpoint tests call `POST /reset`, which empties every table. Road lookups need internet access; without it plans fall back to straight lines and the tests still pass.

`python3 -m pytest real_data/tests` additionally needs `pip install -r real_data/requirements-realdata.txt`; without it those tests fail on a missing `agmarknet` module. The API does not need it.

Frontend: `cd frontend && npm test` (simulation engine) and `npm run build` (typecheck plus production build). `.github/workflows/ci.yml` runs both halves on every push.

## Real-data pipeline

The India Data Portal's Agmarknet export is a bulk CSV you download by hand (the Agmarknet site itself is captcha-protected). The repo includes the CSVs for Bihar and four other states (Karnataka, Uttar Pradesh, Maharashtra, Madhya Pradesh) under `backend/real_data/data/raw/`, about 15 MB of data in all. The Tamil Nadu preset's source CSVs are not included, so that preset can be used but not rebuilt from this repository.

```bash
# regional preset (any of the five non-Bihar presets; Tamil Nadu needs its own CSV)
python3 real_data/build_regional_presets.py --list
python3 real_data/build_regional_presets.py --preset karnataka_bengaluru --csv <state csv>
```

This writes a `.js` block of preset data to adapt into `SCENARIOS` in `frontend/src/lib/scenarios.ts` and a `.json` record of every count, cleaning step and assumption under `real_data/data/regional/`. Bihar uses the older `import_idp_csv.py`, `build_real_markets.py` and `make_preset_block.py` path. Steps and safeguards are in `backend/real_data/README.md`.

## Known issues and limitations

- `verify_visualization.py` currently fails. Its check that served plus unserved farmers cover everyone predates farm-gate farmers, who are now a third group (`farmgateFarmerIds`). It also needs an empty database. The pytest suite, including `test_visualization_baselines.py`, passes.
- All farmers and the fleet are synthetic, and ILO's lead depends on the assumed farm-gate discount and on a few high-priced mandis (Sheohar in Bihar). Price response to extra volume is modelled only if `price_impact` is switched on (default off); its elasticities are lower bounds, and fixed-price numbers overstate gains by roughly 17% at those values.
- Distances are measured road km (OSRM, cached) when reachable, else straight-line km times a circuity factor, at a constant 32 km/h for time. The public OSRM demo server is rate-limited and has no uptime guarantee, so a deployment that must not fall back should host its own (`OSRM_BASE_URL`). Road km do not capture road quality, so travel time is still approximate.
- In the fleet model a vehicle is busy for the pickup leg plus turnaround; the delivery leg does not occupy it (inherited from the simulator).
- Spoilage is a linear model with a per-crop uncooled/cooled switch. Tomato, spinach, cauliflower and mango use working rates from a literature review of hourly postharvest WEIGHT loss (uncooled / cooled per hour: tomato 0.05% / 0.013%, spinach 0.75% / 0.03%, cauliflower 0.15% / 0.03%, mango 0.07% / 0.015%). Onion and potato (0.8% and 0.5% per hour) have no source and are probably far too high. Weight loss is not rejection or quality loss, which are not modelled. A reefer is treated as pre-cooled load; one that holds temperature without removing field heat sits between the two rates. Spoilage is counted only from pickup, not while produce waits at the farm. Trips are single-mandi and single-crop for consolidation. The plan covers one day with no carry-over.
- Mandi capacity is a hard cap by default, built from median daily arrivals (some Bihar values are reporting defaults); it binds in 3 of 5 presets and the cap assumption moves reported gain by 7% to 26% (sections 24 and 25). A soft cap exists (`PriceImpact.soft`), but planning with it is not yet reliable.
- The Monte Carlo shock sizes and the farm-gate discount scenarios are judgement calls, not calibrated.
- v3.1 results come from 2 to 6 synthetic seeds per setting. Treat the percentages as indications.
- In the regional presets the farmer cluster is centred on a mandi hub, so hauling pays far more often than in Bihar. Do not read the lead sizes across presets as a statement about the regions.
- Six Bihar mandi-crop capacities are reporting defaults, not measurements. Madhya Pradesh lost 27 mandis to missing coordinates, which thins its mandi set.
- MILP ground truth only scales to about 5 to 7 farmers.
- Farmer change requests: the OpenRouter path was tested against a mocked client and then on a real phone. Reasoning models can use up the token limit while thinking (OpenRouter logs `finish_reason: length`): prefer a non-reasoning model or raise `OPENROUTER_MAX_TOKENS`, and mind `OPENROUTER_TIMEOUT_S` for slow ones. Test your model on your farmers' languages before relying on it. Times are plan hours (hour 0 is 00:00), there is no 'tomorrow'. Cancelling participation is not supported yet. The chat rate limit is per process and in memory. Every preview adds an unpublished row to `plan_runs`. The Telugu, Hindi and Tamil strings are machine-written and need a native review.
- No Docker image yet. CI (GitHub Actions) runs the tests and the frontend build; deployment is by hand on Render and Neon (see Deployment). The admin routes are open unless `ADMIN_TOKEN` is set.
- SMS and WhatsApp: the Twilio, MSG91 and Meta adapters have not been run against the live services, and the database-backed phone tests in `tests/test_phones.py` were written without a Postgres available, so run them once against a throwaway database. The Telugu, Hindi and Tamil strings (app and messages) are machine-written and need a native-speaker review.
- The farmer app shows a demo code on screen when `NOTIFY_DEMO_SHOW_OTP=on` with `SMS_PROVIDER=dry`; never leave that on with real farmers.
