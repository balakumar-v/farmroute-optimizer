# Extending Farmroute

Where to plug new behaviour in. Every seam below exists in the code today; each recipe says which file to touch and
which test pattern to copy. Rule of thumb: **add read-only views first** (they cannot change a plan's numbers), and
touch the solver only when a brief truly needs a different objective or constraint.

## 1. A new read-only view of a plan (cheapest, safest)

Examples already built this way: fleet advice, quote check, impact, payout, plan diff, driver sheet.

1. Write a pure function in `backend/advisor.py`. Input is the dict `GET /plan/{id}` returns (`input_snapshot`,
   `integrated_logistics_optimization`, `realistic_baselines`). No database calls inside it.
2. Add a three-line endpoint in `backend/main.py` under "plan advisors": `plan = get_plan(plan_id)`, call the
   function, map `KeyError` to a 404. If it needs stop order or arrival times, take them from
   `_straight_viz_payload(...)["solutions"]["integrated_logistics_optimization"]` (see `plan_driver_sheet`).
3. Test it in `backend/tests/test_advisor.py`: build a plan with `_plan()` (no database needed), assert an
   invariant (totals reconcile, nobody is paid below their doorstep value), and add one call to
   `test_endpoints_end_to_end` (runs when `DATABASE_URL` is set).

## 2. A different price assumption (farm-gate, observed quotes)

`baselines_v3.FarmgatePrices(markets, discount=..., per_kg={crop: rs_per_kg}, price_fn=farmer -> rs_per_kg)`.
`run_ilo_v3(..., prices=FarmgatePrices(...))` plans with it. **Not yet wired into the API**: `_run_plan` in
`main.py` calls `run_ilo_v3` without `prices`, so the API always uses the median-mandi x (1 - 20%) assumption.
To use real quotes, pass `prices=` there and store the per-crop prices in `realistic_baselines["assumptions"]`
(`advisor._prices` already reads `farmgate_discount` from that block; extend it to read `per_kg`).

## 3. A different objective (what the plan optimises)

- `mode=returns | spoilage` on `POST /plan/compute` (`run_ilo_v3` vs `run_ilo_v3_spoilage_first`).
- `spoil_weight` in `run_ilo_v3`: charges spoiled produce extra in trip scoring.
- `dispatch_margin`: a trip must beat the farm gate by this fraction (risk buffer).
To add a new mode: add a branch next to `mode == "spoilage"` in `_run_plan`, and validate it in `compute_plan`.

## 4. A new constraint

Trip selection is one exact program, `ilo_v3.solve_fleet_set_partition`: rows are farmers (each at most once),
mandi capacity per crop, and vehicles busy per time cell. A new limit is a new row group in that matrix
(see how `mk_rows` and `fl_rows` are built). Afterwards run `tests/test_ilo_v3.py` and
`milp_benchmark.py`: the "never worse than a baseline" safeguard must still hold.

## 5. A new data source or regional preset

Presets are frontend data in `frontend/src/lib/scenarios.ts` (farmers, vehicles, markets that the app POSTs to
the API). Generate the block with `backend/real_data/make_preset_block.py` from Agmarknet data
(`scrape_agmarknet.py`, `build_regional_presets.py`). A new region = a new entry with a `category`, a `blurb`
that says exactly which parts are real and which are assumed.

## 6. Bulk-loading farmers

`POST /farmers/upload` (csv/xlsx, all-or-nothing validation, `dry_run=true`). Add a column by extending
`farmer_upload.REQUIRED/OPTIONAL` and `schemas.FarmerIn`.
