# Changelog

## Unreleased
- Plan compute now uses the latest fresh ESP32 `room` reading as the plan temperature (simulated fallback); added `hardware/` firmware.

## Faster planning (Nov 2026)
Measured on the same scenarios, original vs now (this machine; Render's free CPU is far slower, so the ratios matter more than the seconds):

| scenario | ILO v3 before | now |
|---|---|---|
| 40 farmers | 4.8 s | 0.8 s |
| 60 farmers | 12.9 s | 2.8 s |
| 100 farmers | 11.3 s | 3.3 s |
| 100 farmers (hard case) | 42.3 s | ~10 s |
| 200 farmers | 33 s | ~8 s |

- **Allocation cache** (`algorithms_v2.allocate_markets_lp`). The trip search asked for the same market allocation again and again (78% of 5,443 calls on a 100-farmer plan were exact repeats), each a separate HiGHS solve. The answer depends only on the pools' kg, positions, timing, vehicle cost and the markets' prices and room, so it is now remembered (bounded LRU, 4,000 entries, a few MB; `ALLOC_CACHE_MAX=0` turns it off) and handed back as a fresh copy.
- **Single-pool shortcut.** A one-pool allocation is a fractional knapsack, so it is filled greedily instead of calling the LP solver (exactly the LP optimum; tested against the LP on random cases). The multi-pool LP is unchanged, but its matrix is now built directly in COO form instead of cell by cell.
- **Set-partition time cap 30 s -> 5 s** (`ILO_SP_TIME_LIMIT`; `ILO_SP_GAP` sets the gap, default unchanged). On the hard cases the exact solver ran into its 30 s cap and returned its best-so-far anyway. With 5 s the plan value moved by 0.0% to -0.4% in our runs (and was sometimes higher, because a capped solver's best-found is noisy). Set `ILO_SP_TIME_LIMIT=30` to restore the old behaviour.
- The plans are unchanged otherwise: on four scenarios every pool, vehicle, kg and rupee matched the original to 1e-6 with the cache and shortcut in place. Tests: `test_speed_paths.py`.

## "My trader pays less": join the pooling from the chat (Nov 2026)
- **New request type.** A farmer shown as "sell at your door" can say, in the chat, on the form, or with one tap from "Check a trader's offer", that their own trader pays less than expected and they want to join the pooling. The model returns only `pool_join: {quote_per_kg}` (a price for one kg, copied from the message; a total for the lot makes it ask). Code checks it against the farmer's own published card: refused if they already have a truck (`already_hauled`), are waiting for one (`waiting_truck`), or the offer is not below the expected door price (`not_lower`).
- **Admin approves like any change.** Nothing is saved by drafting, confirming or previewing. Approving writes `farmers.trader_quote_per_kg` (new nullable column, added at startup) and the re-plan prices **only that farmer's** doorstep sale at the quote, through `FarmgatePrices(price_fn=...)`. Every other farmer keeps the assumed price (median mandi less the 20% farm-gate discount); with no quotes the optimizer runs exactly as before. The plan snapshot records `trader_quotes` so the cards, quote check and payout statements agree with the plan.
- Whether the farmer gets a truck is up to the planner: a quote only helps if hauling now beats that farmer's own door price. The farmer sees the result on their new card and can still cancel in the chat.
- `CHANGE_MAX_QUOTE_PER_KG` (default 500) rejects a typo'd price. Farmer app strings added in English, Telugu, Hindi and Tamil. Tests: `test_pool_join.py`, `test_change_requests.py` (DB), `changeRequests.test.ts`, `chat.test.mjs`.
- Fixed: confirming a request that was refused for "too many waiting" or "already asked" showed the generic "your details changed" message; the farmer app now shows the right message (all four languages), keyed on the server's `code`.
- Not done: a quote never expires on its own (clear `trader_quote_per_kg` when a new harvest cycle starts); no instant take-home figure for a doorstep farmer before the re-plan, because no trip exists to price until it runs.

## Change-request chat: follow-ups, several requests, "tomorrow 6 AM", cancel (Nov 2026)
- **The bot remembers the chat.** The last few turns (the farmer's messages and what the app asked or refused) are kept per farmer for ten minutes and sent to the model, so an answer to "before what?" or "make it 200 then" is understood. The memory is cleared when a request is confirmed. New table `chat_context`.
- **Several requests at once.** A farmer can have up to `CHANGE_MAX_PENDING` (5) requests waiting; a new one no longer replaces the old one. Asking for exactly the same thing twice is refused. The console flags requests of one farmer that clash (same thing, or one leaves the plan), refuses to preview or approve a clashing pair together, checks at approval that a farmer's numbers still hold together (ready before deadline), and marks the other request superseded when one is approved. A request is stale only if what it changes moved, so approving a quantity request does not spoil a waiting time request. Drafts are now deleted rather than kept when replaced or withdrawn. The unique one-pending index is dropped at startup.
- **Dates.** The model passes a day word (today, tomorrow, day after tomorrow, a weekday, or a date) and a 24-hour time; code turns it into plan hours from today's date (`FARMROUTE_TZ`, default Asia/Kolkata) and the plan day (the calendar date of hour 0, set in the Requests tab, default the day the plan was published). Times past 24:00 show as "next day" on the confirm card, the farmer's card and in SMS/WhatsApp. The farmer form has a Day box.
- **Cancel and rejoin.** "I will not sell this time" becomes a request; approving it sets `farmers.active = false` (new column, added at startup), the row stays and the next plan leaves the farmer out. The farmer sees a "you are not selling this time" screen with a button to ask to join again. The console's Data tab marks farmers who left, and the preview lists farmers who leave or join. An all-farmers-out plan is refused.
- Tests: backend (`test_change_requests.py`), console (`changeRequests.test.ts`), farmer app (`chat.test.mjs`).
- Not done: the optimizer stability term (penalise moving farmers who did not ask), voice replies, dates with a month name beyond what the model turns into YYYY-MM-DD.

## Rescue for pools that got no truck + honest fleet metrics (Nov 2026)
- `run_ilo_v3` now runs two extra passes on pools that ended with no vehicle: (1) re-plan them on own vehicles the first pass left idle (splits a pool that only a big truck could take), (2) hire non-refrigerated spot trucks (`SPOT_MARKUP` 1.15x rate, max 6 per type). Each pass is kept only if it adds value; every farmer still appears exactly once. Switch off with `rescue_unserved=False` / `spot_fallback=False`. Details in `meta["rescue"]`.
- Pools that still get no truck carry `no_truck_reason` (needs reefer / bigger than the biggest vehicle / all vehicles dispatched / deadline).
- Trips from a pass that fell back to its direct baseline now get a synthesized trace entry, so the map shows their market receipts.
- `GET /plan/{id}/fleet-usage` + Fleet usage panel: vehicles dispatched vs idle, average load as % of capacity, hired trips, per-type rows, unserved pools with reasons. The summary line now reads "% of fleet dispatched" (it was labelled "utilised", but never measured load).
- Plan tab: "Infeasible" tag replaced by "No truck: <reason>".
- Tests: `backend/tests/test_rescue.py` (6).

## Fairer payouts: range, operator fee, split rule, fairness report (Nov 2026)
- Payout statements and farmer cards show a downside range (`range_inr`: mandi prices -10%, running cost +10%); the farmer app slip shows "as little as Rs X" when it is meaningfully lower (en/te/hi/ta). Service worker cache v11.
- `OPERATOR_FEE_PCT` (default 0): an explicit fee line taken only from a farmer's gain over their doorstep value; totals plus fee reconcile to the plan value.
- `split_rule=kg|cost_aware` on `POST /plan/compute` and a "Share gains" selector on the Plan tab. `kg` stays the default; `cost_aware` (new `backend/payout_rules.py`) splits by crop value and pickup detour. `tools/compare_split_rules.py` shows it tracks detour cost but widens inequality (docs section 26).
- `GET /plan/{id}/fairness` and a Fairness panel on the Plan tab (share gaining, gain spread, Gini, bottom fifth, who gets nothing).
- Tests: `backend/tests/test_payout_rules.py` (15).

## Repo restructure (Nov 2026)
No code behaviour changed; top-level deploy folders (`backend/`, `frontend/`, `farmer-app/`) and every backend module the API imports stay where they were.
- Root: the long docs moved to `docs/` (with an index); the two WhatsApp guides to `docs/whatsapp/`. Root keeps README, CHANGELOG, `.github`.
- `backend/tools/`: run-by-hand scripts (`verify_*`, `benchmark_*`, `calibrate_circuity`, `generate_vapid`). Run them as `python tools/<name>.py` from `backend/`.
- `backend/experiments/{v3_1,v4}`: the study scripts and raw results; v4 logs in `v4/logs/`, launchers no longer hardcode a machine path.
- `frontend/legacy/`: the old pre-React files (app.js, style.css, vis/, vendor/, config.js). `legacy/app.js` is still read by `backend/real_data` for the presets.
- Removed `farmer-app/manifest.webmanifest` (unused duplicate; the app loads `manifest.json`). `.gitignore` now covers node_modules, dist and env files.
- Tests: same results before and after (86 pass; the same 4 `agmarknet` import failures).

## Farmer login on PC, show/hide PIN (Nov 2026)
- Farmer app login: the ID and PIN boxes no longer ask the browser's password manager to fill them (`autocomplete="off"` / `"new-password"`). A desktop browser could autofill an old saved PIN (PINs change when re-issued) into the 6-character box, so the correct PIN could not be typed and the login said "wrong". Spaces typed or pasted inside the PIN are ignored.
- Eye button at the right of the PIN box shows or hides the PIN (labels in en, te, hi, ta).
- Service worker cache bumped to v10 so desktop browsers drop the old cached `app.js`.

## Farmer access on its own tab, current-PIN list (Nov 2026)
- The whole Farmer access area (PINs, publish, printed cards, phone numbers, recent messages) moved out of the Plan tab into a new **Farmer access** tab (`views/AccessView.tsx`); the Plan tab is now only the plan, its numbers and the pools.
- Next to **Issue PINs** there is now **View current PINs**: every farmer with whether they have a PIN, when it was issued and whether they are locked out, plus a per-farmer **Re-issue / Issue**. PINs are stored only as salted hashes, so the digits of an existing PIN cannot be shown; re-issuing shows the new one once. New route `GET /farmers/pins` (admin token; never returns a PIN or hash).

## Merge of main4 + v3 + merged2 (Nov 2026)
Base: main4 (superset: change requests, Web Push, /health, tests, onion/potato spoilage rates, map clock). Added from merged2: the farmer-app microphone (speech recognition) button, its strings (en/te/hi/ta), CSS, README text and jsdom tests, merged by hand into main4's `app.js` next to the Web Push code. Added from v3: `backend/whatsapp_service.py` (Meta Cloud API payload builders, webhook verify + delivery-status events, no WABA ID needed), the `/api/whatsapp/*` and `/webhook/whatsapp` routes (public prefixes in `auth.py`), table `whatsapp_delivery_statuses`, `WHATSAPP_PHONE_NUMBER_ID` / `WHATSAPP_GRAPH_API_VERSION` / `WHATSAPP_WEBHOOK_VERIFY_TOKEN` env names (old `WHATSAPP_PHONE_ID` still works), `tests/test_whatsapp_service.py`, `WHATSAPP_SETUP_GUIDE.md`.  v3's `backend/.env` (live-looking secrets) was NOT carried over.

## Farmer change requests: chat in the farmer app, approval in the console (Nov 2026)
A farmer can ask the FPO for a different quantity, ready time or deadline from a round chat button on the card screen. Nothing changes until an operator approves.
- Farmer app: type a message ("100 kg less, ready 2 hours later") or, when the language model is off or unreachable, fill a small form. The app shows what it understood in plain numbers (built by code, not by the model) and the farmer taps Confirm. "Your requests" shows waiting, approved or rejected (with a reason), and a waiting request can be cancelled. The button is hidden offline. New strings in en, te, hi, ta (machine-written; need a native review).
- Backend: `backend/chat_llm.py` (OpenRouter, JSON out only, no SQL, no ids, no arithmetic; sees only that farmer's own three values) and `backend/change_requests.py` (Pydantic models, set/shift/scale resolved against the farmer's row and bounds-checked, drafts, confirm, one live request per farmer, approve and reject). Routes: `POST /farmer/chat`, `POST /farmer/requests/{id}/confirm|withdraw`, `GET /farmer/requests`; operator `GET /change-requests`, `POST /change-requests/preview|approve`, `POST /change-requests/{id}/reject`, `GET/PUT /change-window`. Tables `change_requests`, `change_window` (cleared by `POST /reset`).
- Preview and approve: `_compute_plan_impl(farmer_overrides=...)` plans as if the new values were saved without writing them. Approving one or several requests recomputes once, saves, then publishes through the existing publish (so only farmers whose card changed are messaged). Refused with 409 if the published plan moved since the preview or the farmer's details changed since they asked.
- Console: new Requests tab (what they wrote, what it means, preview showing how many farmers did not ask but would move, approve, reject with a reason, open or close requests). Approve stays disabled until that exact selection has been previewed.
- A model that returns no text or is cut off by the token limit (a reasoning model, `finish_reason: length`) now gets one retry with a bigger budget and then falls back to the form; it can no longer crash the chat endpoint.
- Not done: cancelling participation, dates such as "tomorrow", voice input, the optimizer stability term (penalise moving farmers who did not ask). The OpenRouter call has only been run against a mocked client.
- Tests: `backend/tests/test_change_requests.py` (pure tests need no database; the API tests need `DATABASE_URL`), `frontend/src/lib/changeRequests.test.ts`, `farmer-app/tests/chat.test.mjs` (jsdom; `cd farmer-app/tests && npm i && npm test`).
- Microphone button in the farmer app's message box (phone's built-in speech recognition, in the app's language; fills the box, never sends by itself; hidden where the browser has none). Tests use a fake recogniser in jsdom.

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
