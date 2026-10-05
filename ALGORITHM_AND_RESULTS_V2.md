# Algorithm v2: Redesign for Scale

This is a redesign of the original prototype, built directly from the audit
findings on v1 (see `ALGORITHM_AND_RESULTS.md`) and stress-tested up to
10,000 farmers. It is still a prototype on synthetic data — the goal here
is a proof of concept that the *approach* holds up computationally and
economically at scale, not a production system.

Code: `logistics_lib_v2.py` (data model), `algorithms_v2.py` (pipeline),
`benchmark_v2.py` (scalability + comparison harness). Results:
`results_v2_raw.csv` (450 runs), `results_v2_summary.csv` (aggregated).
Interface: `CONTRACT.md`.

**This revision (Round 3) adds:** a live sensor-override hook connecting
the IoT hardware layer to the algorithm (§2), and k-means depot placement
replacing the earlier grid partition (§3, includes a full benchmark re-run
and an honest before/after — it helped net return meaningfully and did
**not** resolve the coverage plateau, which was the specific thing it was
trying to fix). Sections 1 and 4–6 carry over from the Round 2 write-up
with numbers refreshed after the depot-placement change.

**Round 4 adds:** an exact MILP ground-truth benchmark for small
instances (see `MILP_GROUND_TRUTH.md`) — and, unlike Round 3's
depot-placement finding, this one led to an actual ILO fix, not just a
diagnosis. Tracing ILO's worst small-instance gap against the MILP
(74.4% of the true optimum) found a real, mechanical cause — DBSCAN's
fixed clustering radius blocking an economically-obvious pooling
decision under refrigerated-fleet scarcity. Fixed with a
scarcity-aware widened radius applied only to refrigeration-needing
farmers (§10), reverified against both the MILP (mean ratio 85.3%→96.0%)
and the full 450-run benchmark (net return +1.5% to +12.9% and service%
+0.8 to +3.4 points at **every** tested scale, zero regressions). All
tables in §4–§5 below reflect the numbers after this fix.

## 1. What changed from v1 (Round 2, unchanged this round)

**Wider sample space.** 6 crops instead of 2 (tomato, onion, potato,
cauliflower, mango, spinach) and 7 vehicle types instead of 4 (500kg
mini-pickup up to a 5,000kg refrigerated truck).

**A real, finite fleet.** Vehicles are individual instances with an
`available_at_hr` that updates as they're used, and can be reused later
the same day (multi-trip modeling). A pool that can't get a vehicle in
time is genuinely unserved.

**Market allocation is a linear program, not a greedy pass.** One LP per
crop (`scipy.optimize.linprog`, HiGHS) solved jointly across every pool
competing for that crop's markets — provably optimal for "maximize net
value subject to capacity," and it naturally leaves produce unsold rather
than force a trade at a loss.

**Mixed-crop pooling.** A truck can carry tomatoes from one farmer and
onions from another in the same load.

**Fast geo-clustering.** DBSCAN with `metric='haversine',
algorithm='ball_tree'` instead of an O(n²) pairwise distance matrix.

**Optional elastic market pricing.** Off by default.

Five real bugs were found and fixed by actually running this at
increasing scale (broken vehicle-reuse timing, a ready-time-instead-of-
deadline gate that silently disabled multi-trip reuse, bin-packing to
the single largest vehicle starving every other size class, weight-sorted
bin-packing ignoring geography, and a one-shot capacity queue that ran
dry) — full detail in the Round 2 section preserved below (§7).

## 2. Live sensor-override hook (Round 3, new)

**The problem this closes:** the hardware track posts live
temperature/humidity readings to `POST /sensors/reading`, but nothing
consumed them — a real reading had zero effect on any plan's numbers.
This is the gap between "we built a sensor" and the pitch deck's actual
hardware claim (live reading → adjusted spoilage → net return
recalculates).

**The design wrinkle, and the decision made.** `run_our_system_v2()`'s
per-crop `allocs` (each with its own market split, price, kg) get summed
into the flat `pool_result` by `_finalize()` and are otherwise discarded.
Since v2 pools are mixed-crop, correctly overriding one pool's spoilage
needs each crop's own allocation, not just the pool total — a single
truck carries several crops at different spoilage rates. Two options were
open: (a) have `run_our_system_v2()` optionally return/cache the per-crop
breakdown, or (b) reverse-engineer a pool's crop composition from the
flat result after the fact. **Chose (a).** Option (b) would need farmer
crop lookups threaded back in from elsewhere anyway and gains nothing
over keeping the breakdown that already exists mid-call — it would be
solving the same problem a second time, worse.

**What was built:**
- `run_our_system_v2(..., return_trace=False)` — new optional argument.
  When `True`, returns `(results, trace)` instead of just `results`.
  `trace` is `dict[int, PoolTrace]`, one entry per pool that actually got
  a vehicle (infeasible pools have no trace entry — there's nothing to
  override). Default behavior (`return_trace=False`) is **unchanged** —
  verified against the exact worked example in `CONTRACT.md`
  (`net_return_per_farmer=3027.1`, reproduced exactly).
- `PoolTrace` — one dispatched pool's farmers, assigned vehicle,
  `transport_cost` (fixed once dispatched), `unsold_kg` (LP-driven, also
  fixed), and `crop_allocations: dict[crop -> list of {market_id, price,
  kg, dist_km}]` — literally the LP's own edge output, cached instead of
  thrown away.
- `apply_sensor_reading(trace, pool_id, observed_temp_c, elapsed_hours)`
  — recomputes `spoilage_loss_kg`, `revenue`, `net_return`, and
  `per_farmer_net` from the observed reading, per crop, using a new
  `spoilage_fraction_from_temp()` in `logistics_lib_v2.py`. Everything
  else (`markets_used`, `unsold_kg`, `unserved_no_vehicle_kg`,
  `transport_cost`) is carried over unchanged — market allocation is not
  re-run, exactly as specified. Raises `KeyError` with a clear message
  for an unknown `pool_id` or a pool that never dispatched.
- `spoilage_fraction_from_temp(crop, observed_temp_c, transit_hours)` —
  the base pipeline only ever knows a vehicle's refrigerated/not
  *design fact* (a binary); a real sensor gives a continuous temperature.
  Modeled as spoilage rate increasing linearly with how far the observed
  temperature sits above a per-crop safe transit threshold (4°C for
  crops needing refrigeration, 20°C otherwise; +8%/°C above that,
  capped at the same 0.6 loss ceiling as the rest of the model). This is
  an explicitly-not-fit assumption, flagged the same way the rest of
  this prototype's spoilage modeling is — replacing it with something
  calibrated to real produce is future work, not claimed here.

**Verified, not just written:** tested on a real dispatched mixed-crop
pool (4 crops, 8 farmers) at three conditions —

| Condition | revenue | spoilage_loss_kg | net_return |
|---|---:|---:|---:|
| Modeled estimate (original) | 32,370.6 | 803.4 | 26,057.5 |
| Sensor: 4°C, 3hr (cold chain held) | 43,189.6 | 169.6 | 36,876.5 |
| Sensor: 28°C, 6hr (cold chain broken) | 30,397.5 | 943.0 | 24,084.4 |

`transport_cost` (6,313.1) and `unsold_kg` (0.0) identical across all
three, as required. Also checked: unknown `pool_id` and infeasible-pool
`pool_id` both raise `KeyError` correctly.

**Usage example** (also added to `CONTRACT.md`):
```python
results, trace = run_our_system_v2(farmers, copy.deepcopy(fleet), markets, return_trace=True)
# ... truck for pool 3 posts a live reading mid-transit ...
updated = apply_sensor_reading(trace, pool_id=3, observed_temp_c=26.5, elapsed_hours=4.2)
# updated["net_return"], updated["spoilage_loss_kg"] etc. reflect the live reading;
# updated["markets_used"] / ["unsold_kg"] / ["transport_cost"] are unchanged from results[3].
```

## 3. Depot placement (Round 3, new — replaces the grid partition)

**What changed.** `_grid_partition()` (fixed ~26km grid cells) is
replaced as the default by `_depot_partition()`: k-means on farmer
coordinates places `round(n_farmers / 40)` depots (the same ~1-vehicle-
per-40-farmers ratio `default_fleet_composition()` uses), then each
farmer is assigned to their nearest depot (exactly what a k-means label
is) before DBSCAN + bin-packing run within each depot's catchment. The
grid partition is kept only as the fallback when scikit-learn isn't
available.

**Why this was expected to help:** a fixed grid cell doesn't adapt to
where farmers actually are — a sparse cell forms a small, inefficient
pool right next to a dense cell forming an oversized one. Density-adaptive
depots should produce more evenly-sized, tighter pools, and shorter
average routes should mean faster vehicle turnaround (more trips/vehicle/
day for the same fleet).

**What the full benchmark re-run actually showed** (5 trials/n, same
seeds as Round 2, so this is a genuine paired before/after — grid vs.
depot, everything else identical):

| Farmers | Net return: grid → depot | Service%: grid → depot |
|---:|---:|---:|
| 50 | 152,264 → 141,273 | 69.4% → **64.6%** (worse) |
| 100 | 165,185 → 154,791 | 42.1% → **37.9%** (worse) |
| 300 | 248,932 → 279,928 (+12%) | 29.5% → 29.9% (flat) |
| 1,000 | 334,809 → 416,124 (+24%) | 15.8% → 16.3% (flat) |
| 4,000 | 1,129,003 → 1,300,343 (+15%) | 13.9% → 14.2% (flat) |
| 10,000 | 2,850,915 → 3,127,659 (+10%) | 13.1% → 13.2% (flat) |

**Honest reading — don't oversell this:**

1. **Net return improved meaningfully and consistently from n=300 up
   (+8% to +24%).** Depot-based pools are genuinely more efficient
   trips — this part worked as expected.
2. **The coverage plateau — the specific thing this change was meant to
   fix — did not move.** Service% at scale is flat within noise (13.1%
   → 13.2% at n=10,000; the largest movement anywhere from n=300 up is
   +0.6 points). More efficient individual trips didn't translate into
   materially more farmers served, because total fleet capacity didn't
   change — the same number of vehicle-hours were just spent slightly
   better. **This confirms rather than contradicts the Round 2
   diagnosis**: the plateau is a fleet-*sizing* problem (a flat ratio
   that ignores local density), not a pooling-*quality* problem, and
   better pooling alone — however done — was never going to fix it.
3. **Small-n (50, 100) actually got worse**, and this was traced to a
   real mechanism, not noise: at n=50, `round(50/40)=1`, so k-means
   places a single depot containing *all* 50 farmers regardless of how
   spread out they are — re-verified directly (`_depot_partition`
   returns one 50-farmer group at n=50, vs. the old grid's 10
   appropriately-sized cells for the same scenario). This reintroduces
   some of the exact sprawl problem the grid partition was originally
   built to fix (§7, bug 4), specifically in the regime where farmer
   *count* is low but the *service area* isn't small. The fix would be
   bounding depot count by geographic spread as well as farmer count,
   not swapping one count-only heuristic for another — not done here;
   flagged for the next round.

Updated charts: `chart_net_return_v2.png`, `chart_service_pct_v2.png`,
`chart_runtime_scaling_v2.png` (runtime shape unchanged — k-means adds
negligible overhead, e.g. 3.9s vs 4.7s at n=10,000 for the whole run,
both dominated by the LP stage, not clustering).

## 4. Runtime (Our System, mean of 5 trials, refreshed after the Round 4 fix in §10)

| Farmers | Vehicles | Markets | Runtime |
|---:|---:|---:|---:|
| 50 | 4 | 3 | 0.04s |
| 1,000 | 24 | 4 | 0.43s |
| 4,000 | 100 | 13 | 1.36s |
| 10,000 | 250 | 33 | 4.21s |

Still near-linear; negligibly higher than before the fix (the extra
DBSCAN pass for refrigeration-needing farmers is cheap). Full table:
`results_v2_summary.csv`.

## 5. What this does not show (updated)

Everything in the Round 2 write-up's honesty section still applies — net
return and service coverage are separate axes, Proximity Pooling's
collapse is by construction (naive baseline), and the disclosed
simplifications (haversine distance, constant vehicle speed, a flat
1-hour turnaround buffer, no VRP solver) are unchanged.

**Added this round:** depot placement was tested against the specific
claim it was meant to validate ("does this fix the coverage plateau?")
and the honest answer is no — see §3. It's a real, separately-useful
improvement (better trip economics), not a fix for the thing it was
asked to fix. Reporting a net-return win here without the service%
number next to it would repeat exactly the mistake `CONTRACT.md` already
warns against.

## 6. Suggested next step (revised)

Round 2 suggested depot placement as the top lever for the coverage
plateau. Having built and tested it, that diagnosis needs sharpening:
**depot placement improves trip efficiency but does not add capacity
where the density is** — it reshapes existing vehicle-hours rather than
allocating more of them to where farmers actually are. The next step
that actually targets the plateau is **density-aware fleet allocation**:
size or place vehicles proportional to *local* depot demand (e.g.
`default_fleet_composition()` currently takes only a global farmer
count; it should take the depot sizes from `_depot_partition()` and
distribute vehicles across them, not just fix a global ratio). A smaller
follow-up worth doing alongside it: bound depot count by geographic
spread, not just farmer count, to fix the small-n regression in §3.

## 7. Bugs found by actually running it (Round 2, unchanged — kept for reference)

Four of five were caught by testing at increasing scale, not by
inspection.

1. **Individual Transport's vehicle-reuse timing ignored `ready_hr`.**
   Hardcoded pickup-completion time as a flat 0.65hr for every farmer,
   letting 4 trucks appear to serve 30 farmers individually at n=30.
2. **A vehicle had to be free *before* a pool's `ready_hr`.** Since every
   pool becomes ready in the first ~4 hours while a single trip often
   takes longer, no vehicle could ever qualify for a second trip — fixed
   by checking against the pool's *deadline* instead.
3. **Bin-packing to the single largest vehicle's capacity starved every
   other vehicle type.** At n=1,000, 75 of 83 pools needed one of only 5
   largest trucks; 19 smaller/mid vehicles sat idle. Fixed by drawing
   each pool's capacity ceiling from the fleet's actual capacity mix.
4. **Bin-packing by weight ignored geography.** Produced pools with a
   mean pickup route of 291km at n=10,000 (worst case: 44 simulated
   hours). Fixed with a sweep-order pack (sort by angle around the
   group's centroid).
5. **The fleet-capacity menu was a one-shot queue.** Once it emptied,
   every remaining pool collapsed to ~1 farmer. Fixed by making it an
   infinite round-robin over the fleet's capacity mix.

## 8. Benchmark methodology (unchanged)

Paired-trial design: for each farmer count, the same generated scenario
(same seed) runs through all three algorithms. 5 trials per farmer count,
n ∈ {50, 100, 300, 600, 1000, 2000, 4000, 6000, 8000, 10000} — 450 runs
total. Fleet and market count scale with farmer count (~1 vehicle per 40
farmers, ~1 market per 300 farmers). Both baselines get the same real
fleet, multi-trip-reuse, and depot-placement pooling as Our System — the
only remaining difference is decision logic (LP allocation vs. no pooling
vs. naive single-market selection).

## 9. Not done this round

**Unit tests (stretch #3) and the package refactor / Shapley-value option
(stretch #4) were not attempted.** Per the prompt's own priority order,
#1 and #2 took the full available effort once done properly (each
surfaced real, non-obvious findings worth verifying rather than
asserting) — starting #3–#4 on top of that would have meant less
rigor on the two things actually asked for first. The three invariants
named in #3 (no double vehicle-booking, LP never exceeds market capacity,
`unsold_kg + unserved_no_vehicle_kg` + sold reconciles to `total_qty_kg`)
remain a good next-session task and would likely have caught bugs 2, 3,
and 5 above faster than manual scale-testing did.

## 10. Refrigeration-scarcity-aware clustering (Round 4, new — found via the exact MILP, then fixed)

Building the exact MILP ground truth (`MILP_GROUND_TRUTH.md`) wasn't
just a benchmarking exercise — tracing ILO's worst small-instance gap
against it (74.4% of the proven optimum) led to a real fix, not just a
diagnosis, per the same "verify by running, don't just assert" standard
the rest of this project has held to.

**What the MILP found.** On the traced instance, the MILP's optimal
solution pools 4 farmers — 0, 2, 3, 4 — onto a single refrigerated
truck; ILO split them into 4 separate trips instead. Farmers 2 and 3
are 33.2km apart, and no pair among {0,2,3,4} is within ILO's
`EPS_KM=12` DBSCAN radius even via a chain, so ILO's clustering stage
never even considers this pooling. The MILP takes it anyway because 4
of these 6 farmers need refrigeration and the fleet has exactly 1
refrigerated vehicle — paying that reefer's fixed cost twice (or more)
is far worse than a longer combined trip. **DBSCAN's geographic-
compactness proxy and the problem's real economic driver
(refrigerated-fleet scarcity) disagreed, and ILO's pooling stage had no
way to see that**, since it commits to clusters before vehicle
assignment ever runs.

**The fix**: `_refrig_eps_km()` in `algorithms_v2.py` widens the DBSCAN
radius used for refrigeration-needing farmers specifically (never for
the general population — the tight radius that fixed the §7-bug-4
sprawl regression at scale stays untouched), scaled by two distinct
scarcity signals taken together — how much refrigeration-needing demand
exists relative to total refrigerated capacity, *and* how few
refrigerated vehicles exist at all (the latter matters independently:
each extra trip pays a full fixed cost again no matter how full it is).
An earlier version using only the capacity signal closed the traced
instance to just 82.1% — under-weighting how badly a second avoidable
trip hurts when only one refrigerated vehicle exists at all. Taking the
max of both signals closed it to 95.3%, matching the MILP's pooling
structure exactly. Capped at 3× the base radius so it can't grow
unbounded.

**Reverified two ways, not asserted:**

- **Against the MILP** (`milp_benchmark.py`, same 9 small instances):
  mean ILO/MILP ratio on proven-optimal cases rose from **85.3% to
  96.0%** (min 74.4%→91.0%, max 100.0%→102.1%). Full before/after table
  in `MILP_GROUND_TRUTH.md` §6b.
- **Against the full-scale benchmark** (`benchmark_v2.py`, 450 runs,
  n=50–10,000) — the check that mattered most, since a naive "just widen
  the radius" fix risked reopening the exact sprawling-route regression
  §7 bug 4 fixed. Sample-checked route distances directly before
  trusting the result: mean pickup-route distance grew modestly
  (≈14–18km → ≈20–22km) but stayed bounded (max ≈130km, nowhere near the
  original 291km/44-simulated-hour blowup). Net return improved and
  service% improved at **every single tested scale**, zero regressions:

| Farmers | Net return (mean) | Service% (mean) |
|---:|---:|---:|
| 50 | 154,051 (+9.0%) | 68.0% (+3.4pp) |
| 100 | 161,191 (+4.1%) | 40.8% (+3.0pp) |
| 300 | 284,090 (+1.5%) | 31.9% (+1.9pp) |
| 1,000 | 426,355 (+2.5%) | 17.2% (+0.9pp) |
| 2,000 | 772,294 (+12.9%) | 16.8% (+1.6pp) |
| 4,000 | 1,365,419 (+5.0%) | 15.6% (+1.4pp) |
| 6,000 | 2,219,484 (+7.9%) | 15.8% (+0.8pp) |
| 8,000 | 2,286,849 (+12.2%) | 13.2% (+0.9pp) |
| 10,000 | 3,388,166 (+8.3%) | 14.1% (+0.8pp) |

(% changes are vs. the depot-placement-only numbers in §3/§4 before this
fix.) Full table: `results_v2_summary.csv`.

**Applied only to ILO, not Proximity Pooling** — this is genuine
problem-aware intelligence (recognizing refrigerated capacity as the
binding constraint, not just geography), not a bookkeeping correction,
and the naive baseline is deliberately kept geography-only for
comparability with its original definition.

**Honest residual limits, unchanged from before this fix:** the
coverage plateau (§5/§6) is still open — this fix improves trip quality
within the existing fleet, it doesn't add fleet capacity where density
needs it, which remains the identified next lever. The small-n
regression from depot placement (§3, n≤100) is partially offset (n=50
service% recovered from 64.6% to 68.0%, still short of the original
grid-based 69.4%) but not the primary target of this fix and not fully
closed.

## 11. Density-aware fleet allocation (Round 5, new — targets §6's plateau directly)

§6 named this as the next lever after depot placement was shown (§3) to
improve trip efficiency without moving the coverage plateau. This round
implements it.

**The change**: `default_fleet_composition(n_farmers)` sized the whole
fleet off a single global farmer count. `depot_aware_fleet_composition(farmers)`
(new, in `logistics_lib_v2.py`, now `generate_scenario_v2`'s default)
partitions farmers with the exact same `_depot_partition()` the
clustering stage uses (moved into `logistics_lib_v2.py` so both modules
share one implementation instead of risking two copies drifting apart),
then sums each depot's own vehicle-equivalent demand
(`max(1, len(depot)/FARMERS_PER_DEPOT)`, floored per depot) into the
fleet total, instead of dividing total farmer count by the ratio once.
The type-mix weights are still applied once, globally, to that total —
**not** re-derived per depot.

That last point was a real bug caught before this ever got benchmarked,
not a design choice: an earlier version reapplied the ~1-per-40 ratio
*inside* each depot too. Since depots are already sized to be ~40
farmers by construction (`FARMERS_PER_DEPOT` is the same constant), a
depot's own count divided by 40 rounds to ~1 almost every time — which
collapsed every depot's local type-mix computation to a single
fallback vehicle. Caught by testing at n=1,000–10,000: the fleet came
back 100% `van`, zero refrigerated capacity generated at any scale.
Fixed by keeping the type-mix step global and letting only the total
vary with how demand is distributed across depots — see the function's
docstring for the specific numbers this produced.

**What it actually does**: a single dense depot (or several
evenly-sized depots near `FARMERS_PER_DEPOT`) reduces to the same total
the flat version computed — confirmed identical fleet size and identical
downstream results at n=50/100/300 below, since those scenarios'
depots happen to land close to that size. Where depot sizes are
uneven — several genuinely small, separate pockets that the flat ratio
would silently pool in with a much larger one — the total grows
(each small pocket contributes its own floored vehicle-equivalent).
Isolated unit check (bypassing depot *placement* itself, which is a
separate, still-open issue — §6, next bullet): a synthetic 350-farmer
depot plus four separate 5-farmer pockets (n=370 total) got 13 vehicles
under the new function vs. 9 under the flat one.

**Reverified against the full-scale benchmark** (mean of 5 seeds per n,
same farmers/markets fed to both fleets so only the fleet-sizing method
differs):

| Farmers | Net return: old → new | Service%: old → new | Fleet size: old → new |
|---:|---:|---:|---:|
| 50 | 163,331 → 163,331 (+0.0%) | 70.85% → 70.85% (+0.00pp) | 4 → 4 |
| 100 | 168,684 → 168,684 (+0.0%) | 42.54% → 42.54% (+0.00pp) | 4 → 4 |
| 300 | 347,187 → 347,187 (+0.0%) | 31.46% → 31.46% (+0.00pp) | 9 → 9 |
| 1,000 | 578,672 → 582,914 (+0.7%) | 18.34% → 18.99% (+0.66pp) | 24 → 28 |
| 2,000 | 853,329 → 839,638 (-1.6%) | 18.19% → 18.36% (+0.17pp) | 50 → 54 |
| 4,000 | 1,853,212 → 1,865,444 (+0.7%) | 17.36% → 17.43% (+0.07pp) | 100 → 107 |
| 6,000 | 2,597,517 → 2,678,253 (+3.1%) | 16.44% → 16.60% (+0.16pp) | 151 → 160 |
| 8,000 | 3,111,357 → 3,118,665 (+0.2%) | 14.74% → 15.03% (+0.29pp) | 200 → 216 |
| 10,000 | 3,745,573 → 3,652,818 (-2.5%) | 14.35% → 14.40% (+0.05pp) | 250 → 269 |

**Honest read of this table, not just the headline direction**: service%
moves in the right direction at every n≥1,000 (small — +0.05pp to
+0.66pp — not the plateau-breaking jump §6 was hoping to test for), at
the cost of a modestly larger fleet (+4% to +9% more vehicles) that this
function now judges necessary given how demand is actually distributed
across depots. Net return is mixed (two of nine scales dipped slightly,
within run-to-run noise territory given only 5 seeds) — more vehicles
slightly dilutes average per-trip efficiency even as it raises total
volume served, exactly the tradeoff a real fleet-sizing decision would
face. n=50/100/300 are provably unchanged (identical fleet, identical
result) because those particular scenarios' depots already land close
to `FARMERS_PER_DEPOT` in size — this fix only bites when depot sizes
are uneven, which random depot placement doesn't reliably produce at
every scale/seed.

**This is a real, verified step in the right direction, not the fix for
the plateau.** §6's other named lever — bounding depot *count* by
geographic spread, not just farmer count (the n≤100 regression cause) —
is still open and would need to land before fleet allocation can be
sized off genuinely spread-aware depots rather than count-only ones.
Vehicles also remain a single shared, location-agnostic pool at
assignment time (`assign_fleet()` isn't depot-bound) — this fix changes
fleet SIZE, not routing or vehicle-to-depot binding.

## 12. Depot count bounded by geographic spread (Round 5, new — targets §3's small-n regression)

§6 named this as a smaller follow-up alongside density-aware fleet
allocation: bound depot count by geographic spread, not just farmer
count, to fix the n≤100 regression §3 traced (a single depot spanning
the whole area when `round(n/40)` floors to 1).

**The change**: `_spread_based_depot_floor()` (new, `logistics_lib_v2.py`)
computes each population's actual lat/lng bounding-box area and compares
it to a reference per-depot area (~2,880 km², calibrated from what
`FARMERS_PER_DEPOT=40` already implies spatially at n=300-10,000 in this
project's own benchmark scenarios — see the function's docstring).
`_depot_partition()` now takes `max(count_based, spread_based)` instead
of count alone, so a population whose actual area is large relative to
what its own farmer count would normally imply gets more depots; a
normally-proportioned one is untouched.

**A wrong first version, caught before benchmarking**: tiling the whole
bounding box with fixed `DEPOT_CELL_KM`-sized cells (26.4km, the
grid-partition fallback's cell size, derived from the unrelated DBSCAN
radius) gave 1,054 depots of ~3-9 farmers each at n=10,000, vs. the
validated 250 — a ~4x inflation at **every** scale, not just small n,
because `DEPOT_CELL_KM` and `FARMERS_PER_DEPOT` were never calibrated to
imply the same area per depot. Would also have wrecked
`depot_aware_fleet_composition()`'s per-depot vehicle floor (§11) —
each of those 1,054 slivers would have claimed its own vehicle. Replaced
with the calibrated-reference-area version above once this was caught.

**Honest result — this is a no-op on this project's own benchmark
data, not a fix for the documented regression:**

- Re-ran `_spread_based_depot_floor()` against `generate_scenario_v2`
  at n=10/20/50/100/300/1,000/4,000/10,000 (seed=1): it never exceeds
  the count-based figure at any scale — confirms the calibration
  doesn't inflate depot count anywhere it wasn't already needed.
- Ran n=50 across 10 different seeds specifically: the floor stayed at
  1 (matching count-based) every single time. Full-pipeline service%
  at n=50/300/1,000 came back bit-identical to §11's pre-this-fix
  numbers (70.85% / 31.46% / 18.99%).
- **Why**: `generate_scenario_v2` draws farmer positions i.i.d.
  uniformly inside a bounding box, so density stays close to its
  expected value almost every draw — there's no genuine area-vs-count
  anomaly for this floor to catch at any of the scales this project
  benchmarks at. §3's original n=50/100 regression must have had a
  different root cause than a literal area/density mismatch (a
  single-vs-multiple DBSCAN catchment boundary effect is the likely
  candidate, not yet isolated) — this fix does not resolve it, and that
  regression **remains open**.
- **Verified the mechanism itself is real**, on data this benchmark
  generator can't produce: two 25-farmer pockets ~440km apart (n=50
  total, bimodal rather than uniform) got `count_based=1` but
  `spread_floor=2`, correctly forcing 2 depots instead of 1 spanning
  both pockets. This is exactly the failure mode a real deployment
  (genuinely separated villages/regions) could hit even at low farmer
  counts — the fix is a real, working safety net for that case, it
  simply isn't exercised by this project's own synthetic test data.

**Net assessment**: implemented as specified, verified working on the
scenario it's designed for, verified inert (correctly, not by
accident) on this project's own benchmark suite. §3's n≤100 regression
needs a different, still-unidentified fix.

## 13. Generalizing scarcity-aware clustering beyond refrigeration (Round 5, new — and reverted)

§6 named this as a follow-up: `_refrig_eps_km`'s pattern (widen the
DBSCAN radius for farmers needing a scarce vehicle subtype, scaled by
how scarce it actually is) seemed like it should generalize to other
scarce vehicle types, not just refrigeration.

**What shipped**: `_refrig_eps_km`'s math was pulled out into a
reusable `_scarcity_eps_km(farmers, fleet, needs_predicate,
capable_predicate, ...)` helper, and `_geo_clusters()` was generalized
from a hardcoded two-way (refrig / not) split to an arbitrary dict of
named scarcity dimensions — a farmer matching several at once gets
clustered at the max of their applicable epsilons. Both are real,
useful refactors on their own and are still in place.

**What was tried and reverted**: a second dimension, `_capacity_eps_km`,
treating "farmers whose own qty_kg exceeds the fleet's smallest vehicle
tier" as the analog of "needs refrigeration." Refrigeration is the
*only* farmer-level attribute in this data model that maps cleanly to
"requires a specific vehicle subset" — capacity need is otherwise an
aggregate, pool-level property (no single farmer's qty_kg, 150-600kg
here, ever needs a whole 5-tonne truck alone), so this was the one
analog available without inventing a new farmer attribute.

**Benchmarked before deciding to keep it — and it was a real
regression, not a no-op:** mean of 5 seeds, n=50-10,000, isolating just
this one change:

| Farmers | Net return: without → with | Service%: without → with |
|---:|---:|---:|
| 300 | 342,028 → 325,702 (**-4.8%**) | 30.70% → 30.09% (-0.61pp) |
| 1,000 | 580,211 → 575,492 (-0.8%) | 18.85% → 18.63% (-0.22pp) |
| 2,000 | 871,804 → 770,899 (**-11.6%**) | 18.39% → 17.80% (-0.59pp) |
| 4,000 | 1,832,777 → 1,749,352 (-4.6%) | 17.24% → 16.95% (-0.28pp) |
| 8,000 | 3,095,545 → 2,864,206 (-7.5%) | 15.06% → 14.81% (-0.24pp) |
| 10,000 | 3,712,586 → 3,389,297 (**-8.7%**) | 14.42% → 14.21% (-0.21pp) |

**Root cause, traced before reverting (not just "it got worse")**:
`_scarcity_eps_km`'s formula treats a resource as scarce when the
"capable" fleet subset is small — that's true for reefers (~32% of the
fleet by design). But "capacity above the smallest tier" selects
everything except `mini_pickup`, which is only ~10-11% of this fleet —
i.e. the "capable" set here is ~89% of all vehicles, the *opposite* of
scarce. Confirmed directly: `capacity_scarcity` (needing-demand ÷
capable-capacity) came back at 2.15 at n=1,000 — not because capable
vehicles were scarce, but because comparing a full day's aggregate
demand against a one-shot (non-multi-trip) capacity sum overstates
scarcity for any subset at scale, refrigeration included (its own
ratio comes back 6-12x at every scale tested, also always pinned to
the max multiplier) — refrigeration's fix still works despite this
because reefers really are a minority resource; capacity's didn't
because non-mini_pickup vehicles aren't. Widening eps for ~20-24% of
farmers who didn't actually face a real vehicle-availability
bottleneck just sprawled their pools' geography for no offsetting
benefit.

**Also caught before shipping, a second and separate bug**: an early
version of the generalized `_geo_clusters()` iterated its scarcity
groups in whatever order a `defaultdict` happened to populate them in
(dependent on incidental farmer ordering within each depot cell), not
a fixed order. Since `fleet_capacity_cycle()` is a single shared,
stateful iterator consumed in cluster-processing order, this silently
changed which capacity ceilings downstream pools drew — caught by
diffing against the pre-refactor baseline (n=300/1,000 service% came
back 0.15-0.75pp off with no intended functional change). Fixed by
always processing scarcity groups in descending-eps order, reproducing
the original hardcoded ordering (refrig group, always the wider one,
was always processed first) exactly — reverified bit-identical to the
§11/§12 baseline after the fix.

**Net assessment**: the generalized `_scarcity_eps_km`/`_geo_clusters`
machinery is real, working, and kept (useful if a genuine second
scarcity dimension is ever added to the data model). The one capacity
analog available in the *current* model isn't a genuine instance of
the pattern it was modeled on, measurably hurts results, and was not
shipped. `run_our_system_v2` uses only the refrigeration dimension,
identical to §10's behavior.

## 14. Joint (Hungarian-matching) vehicle assignment (Round 5, tried and reverted)

§6 named this too: `assign_fleet()`'s one-pool-at-a-time greedy pass
processes pools in `ready_hr` order and best-fits whichever vehicle is
free — which pool "claims" a scarce vehicle when several compete is
whichever gets processed first, an arbitrary order artifact, not a
jointly optimal decision.

**What was built**: a round-based replacement. Each round solves one
exact bipartite min-cost matching
(`scipy.optimize.linear_sum_assignment`, the Hungarian algorithm)
across every still-unassigned pool and the whole fleet at once —
cost = the assigned vehicle's `capacity_kg` (preserving the original's
best-fit preference), `+1e5` for a feasible-but-non-reefer match on a
refrigeration-needing pool (preserving the original's *soft*
refrigeration preference — never a hard constraint, since spoilage
already penalizes the wrong vehicle downstream), infeasible pairs
priced at `1e9` and discarded from the result regardless of what a
rectangular matching forces. After each round, matched vehicles'
`available_at_hr` advances exactly as before, freeing them for a
*later* round — this is what was meant to preserve multi-trip reuse.

**Benchmarked before trusting it, and it was a severe regression, not
a subtle tradeoff:** mean of 5 seeds, controlled A/B (same
farmers/fleet/markets, only `assign_fleet` swapped):

| Farmers | Net return: greedy → joint | Service%: greedy → joint |
|---:|---:|---:|
| 50 | 163,331 → 103,231 (**-36.8%**) | 70.85% → 43.33% (**-27.53pp**) |
| 100 | 168,684 → 97,725 (**-42.1%**) | 42.54% → 26.57% (-15.97pp) |
| 300 | 347,187 → 260,747 (-24.9%) | 31.46% → 23.90% (-7.56pp) |
| 1,000 | 582,914 → 492,227 (-15.6%) | 18.99% → 15.13% (-3.86pp) |
| 4,000 | 1,865,444 → 1,644,228 (-11.9%) | 17.43% → 14.76% (-2.67pp) |
| 10,000 | 3,652,818 → 3,285,116 (-10.1%) | 14.40% → 12.76% (-1.64pp) |

Runtime was fine (comparable to the greedy version, ~5s at n=10,000)
— the problem was never speed.

**Root cause, traced by instrumenting round-by-round (not just
"it got worse"):** at n=1,000 (26 vehicles, 307 pools needing
assignment), per-round assignment counts came back **26, 26, 25, 16,
3, 1, then stuck** — 210 of 307 pools (68%) left unassigned, versus
most of them being served by the greedy version. The mechanism: a
Hungarian matching is one-to-one, so a single round can assign **at
most one pool per vehicle** — with far more pools than vehicles
(routine here), that caps each round at `n_vehicles` assignments no
matter how the cost matrix is shaped. Worse, rounds synchronize every
vehicle's clock together (all matched vehicles advance to
`completion + TURNAROUND_HR` at the same logical step), discarding the
fact that different vehicles actually become free at different real
times — which is exactly the granularity multi-trip reuse depends on
when individual trips and the workday (`WORKDAY_END_HR=14`) are both
short relative to fleet size. The greedy version's fine-grained,
one-decision-at-a-time processing captures that granularity for free;
batching by round throws it away in exchange for removing the order
artifact — a bad trade, confirmed directly, not assumed.

**What a real fix would need, and why it wasn't attempted this
round:** genuine time-expanded modeling — each vehicle offering
several discrete availability slots through the day (a min-cost-flow
formulation over a time-expanded network is the standard approach for
this class of vehicle-scheduling problem) — not a per-round batch
match. That's a materially bigger undertaking than "a small assignment
LP per time-slice" implied, and wasn't attempted this round.

**Net assessment**: reverted. `assign_fleet()` is unchanged from
before this fix; the attempt is kept as `_assign_fleet_joint_attempt()`
(not called anywhere) with the full trace in its docstring, the same
way §13's reverted capacity dimension was kept documented rather than
silently deleted. Order-artifact-free vehicle assignment remains open;
it needs a bigger structural change than this round attempted.

## 15. Merged into the map/simulation frontend (Round 6)

A separate agent built a `Map & simulation` tab on top of this project
(MapLibre GL + deck.gl, `frontend/vis/*.js`) and a backend adapter layer
(`backend/visualization_adapter.py`, `GET /plan/{id}/visualization`) that
reshapes `/plan/compute`'s stored output into farmers/vehicles/markets/
routes/simulation-events, working from an earlier snapshot of this file's
Round 4 algorithm (pre-§11-14: flat `default_fleet_composition`, no
spread-based depot floor, hardcoded refrig-only `_geo_clusters`).

This round merges the two: `backend/algorithms_v2.py` and
`backend/logistics_lib_v2.py` here are the §11-14 versions (depot-aware
fleet sizing, spread-based depot floor, generalized scarcity-eps
clustering; joint vehicle assignment tried and reverted per §14 — same
status as before this merge), dropped in under the visualization layer
unchanged. `backend/main.py`, `backend/database.py`,
`backend/visualization_adapter.py`, and every `frontend/` file are the
other agent's work, untouched by this merge.

**Why the merge required no adapter changes**: `visualization_adapter.py`
consumes `run_ilo_v2(..., return_trace=True)`'s `PoolTrace` output
(`crop_allocations` per pool) and each algorithm's flat
`{farmer_ids, vehicle_id, markets_used, total_qty_kg, revenue,
transport_cost, spoilage_loss_kg, unsold_kg, net_return, infeasible}`
pool dicts — none of that shape changed across §11-14; those rounds
changed fleet sizing and clustering internals, not `_finalize()`'s
output contract or `PoolTrace`'s fields. `run_ilo_v2`,
`run_individual_transport_v2`, `run_proximity_pooling_v2`, and
`summarize()` all kept identical signatures throughout. Verified directly
(not just argued): ran `generate_scenario_v2` -> all three algorithms ->
`build_plan_visualization()` end to end post-merge and confirmed routes,
`distanceKm`, `simulationEvents`, and `marketBreakdownAvailable` all come
back populated and shaped as `visualization_adapter.py`'s docstring
describes.

**What did NOT get merged, on purpose**: the other agent's own
documentation (this project's `README.md` map/simulation section,
`backend/README.md`'s endpoint docs, `backend/verify_visualization.py`)
still describes the visualization layer's own design and honesty rules
— those weren't touched, since this round only changed which algorithm
sits underneath them. The still-open items from §14 (joint vehicle
assignment) and the "P2 #5" backlog note further up (real road distance
via OSRM) are unaffected by this merge either way; see the assessment of
the visualization layer itself for a separate list of what's worth
improving there.

## 16. Simulation-frontend performance fixes (Round 7)

Two scale issues flagged when reviewing the merged visualization layer
(§15), now fixed in `frontend/vis/simulationEngine.js` and
`frontend/vis/logisticsMap.js`. Neither changes what is rendered --
verified by a Node-based equivalence harness (not included in the
shipped tree) that ran the old and new `SimulationEngine` against 20+
synthetic multi-vehicle scenarios across a forward sweep, random seeks,
and boundary times: 4,840 snapshot comparisons, zero mismatches.

**`SimulationEngine.snapshot()`** used to rescan the ENTIRE event list
(for cumulative visited-farmer/visited-market state) and re-derive each
vehicle's trip grouping from scratch, on every single animation frame --
an O(total events) cost per frame regardless of how much simulated time
actually advanced. Replaced with: an incremental cursor over the sorted
event array for the visited-sets (only processes events newly crossed
since the last frame during forward playback; a backward seek pays a
one-time full rebuild, not a per-frame one), and a one-time (constructor
only) precompute of each vehicle's trips as a short, dispatch-time-sorted
array, searched with binary search per frame instead of a linear scan.
Also added `visitedGeneration`, a counter on the snapshot that bumps only
when the visited sets' actual content changed this call -- consumed by
the fix below.

**`LogisticsMap._render()`** rebuilt every deck.gl layer -- including the
full farmer/route/pooling data arrays -- from scratch on every call, even
though `setVehiclePositions()`/`setVisitedSets()` (called every animation
frame during playback) only ever change vehicle positions and which
stops are visited; the farmer/route/market/pooling data itself doesn't
change until a new solution, stage, or compare-solution is loaded. Added
`_memoLayers()`: a small per-layer-group cache keyed by whatever that
group actually depends on (the solution reference, `vis.colored`,
`compareMode`, or `visitedGeneration` from the fix above), so a group is
only rebuilt when one of its own dependencies actually changes --
returning the exact same layer-instance array otherwise, which also lets
deck.gl skip re-diffing that layer when it's passed to
`overlay.setProps({layers})` again. Verified in isolation (build-count
assertions confirming a cache hit for identical deps and a rebuild for
each of solution/stage/compare/generation changing) -- not something a
Python test can reach, since deck.gl/MapLibre only run in a browser.

**Net effect**: per-animation-frame cost during playback now scales with
what actually changed since the last frame (vehicle positions, and only
the specific farmers/markets newly visited) instead of with total
farmer/event count -- the fix targeted the exact n=1,000-10,000 concern
raised when this layer was reviewed, without changing any rendered
output.

## 17. Economic dispatch (Round 8)

**Problem.** Before this round ILO dispatched every pool that could get a truck, even at a loss, and the truck
it spent on a loss-making trip was then unavailable to a profitable one. Seen on a real-market scenario
(Bihar potato/onion, 34 synthetic farmers, 4-vehicle fleet): one 166 kg pool lost INR 3,200 while 2,392 kg
(18.8 %) in other pools "never got a truck".

**Mechanism** (`run_our_system_v2(..., withhold_uneconomic=True)`, default; `False` reproduces the old behaviour exactly):
1. Plan once with every pool, then withhold every dispatched pool whose true net return is < `DISPATCH_MIN_NET` (0) and
   re-plan (freed vehicle-time and market capacity can make other pools profitable); repeat to a fixed point.
2. Bounded local search over *which pools run* (drop a low earner when others are starved, drop a lone loser,
   re-admit a withheld pool). A move is kept only if total net return strictly improves.
3. The whole search is repeated under several vehicle-claim orders (ready / qty / deadline / slack, plus
   `N_RANDOM_ORDERS` fixed-seed random ones) and the best plan found is kept. No single order wins everywhere.
Withheld pools are reported separately (`withheld`, `withheld_uneconomic_kg`; counted as NOT served in `pct_qty_served`).
Baselines are unchanged. Guards: local search only up to `LOCAL_SEARCH_MAX_POOLS`, random orders only up to
`RANDOM_ORDERS_MAX_POOLS`, multi-start only up to `MULTISTART_MAX_POOLS`.

**Provenance (read this).** The withhold / claim-order / local-search code was already present in the working
copy at the start of this round with no recorded origin. It was not trusted on sight: it was reviewed line by line,
audited for constraint violations, and measured against the original (below) before being kept. This round added
the random claim orders, the lone-loser drop move, the `app.js` pool-card display for withheld pools, the tests in
`backend/tests/test_economic_dispatch.py`, and this section.

**Measured** (same inputs, original `algorithms_v2.py` vs. current; 36 scenarios; never worse in any):

| Scenario set | Mean net return | Served % | Loss-making pools |
|---|---|---|---|
| Real Bihar markets, 3 fleet sizes x 8 seeds (24) | 154,287 -> 162,047 (**+5.0 %**) | 91.8 -> 93.3 | 19 -> 3 |
| Project synthetic, n = 20/40/80 x 4 seeds (12) | 117,014 -> 132,412 (**+13.2 %**) | 69.3 -> 69.3 | 2 -> 0 |
| Larger synthetic, n = 100/200/400/800 (1 seed each) | +5.5 / +10.6 / +7.4 / +14.3 % | - | - |
| Exact MILP, n = 5,6 (6 proven-optimal instances) | ILO = 96.8 % of optimum before **and** after (identical) | - | - |

Audit of every plan (each farmer in exactly one pool, truck capacity, per-market capacity, kg accounting,
net = revenue - cost): 0 violations in 36 plans.

**Costs / limits.** Runtime rises from ~0.03-0.6 s to ~0.7-4 s (n = 12-800). Remaining loss-making pools (3 in 24
real scenarios, INR -19 to -73 each) are cases where withholding them lowers the *total* because it changes how the
greedy vehicle assignment treats other pools. Search-budget increases give diminishing returns (10x local-search
evaluations: +0.16 %; 24 vs 8 random orders: ~+0.2 %). The exact MILP only verifies n <= ~6, so the true gap to
the optimum at n ~ 30+ is **not** measured. Not addressed: pool formation itself (clustering / bin-packing) is
unchanged, and idle vehicles are still free in this model, so larger fleets never cost extra.

---

## 18. Realistic status-quo baselines (Round 9)

**Why.** The two original baselines were not what farmers actually do, so "ILO beats them" proved little.
Measured on the project's synthetic generator (n=1000, 3 seeds): legacy Individual Transport dispatched 277 trips from
the FPO's own scarce fleet, 181 of them at a loss; legacy Proximity Pooling sent every pool to the highest *listed*
price regardless of distance, 93 of 105 trips at a loss. Neither could decline a trip, and produce they did not haul
was valued at Rs 0, although the real alternative is selling at the farm gate to a trader.

**What was added** (`backend/baselines_v3.py`; `algorithms_v2.py` and the legacy baselines are untouched):

| Baseline | Model |
|---|---|
| Farm-gate only | everyone sells at the doorstep: (1 - discount) x median quoted price, no transport |
| Self-haul | each farmer hires a *spot* vehicle (not the FPO fleet, never scarce), nearest mandi buying the crop, **round trip**, goes only if it beats farm-gate |
| Neighbour pooling | <= 4 farmers within 5 km with overlapping time windows share one hired vehicle to the nearest mandi buying all their crops; goes only if it beats everyone's farm-gate sale. No depots, LP, fleet-aware sizing or multi-market split |

`summarize_with_farmgate()` values everything a plan did not haul (withheld / no truck / chose farm-gate) at the
farm-gate price and reports `net_return_incl_farmgate`, the number to compare across algorithms (works for ILO and the
legacy baselines too). `benchmark_baselines_v3.py` prints the comparison. The API returns the new results under
`realistic_baselines` (additive; persisted in a new nullable `plan_runs.result_realistic_baselines` column, migrated
on startup). The three original keys, the visualization adapter and the frontend are unchanged, so the map still shows
the legacy two until the adapter is extended.

**Assumptions (not data).** `FARMGATE_DISCOUNT = 0.20` (sensitivity at 0.10/0.30 is in the benchmark); spot vehicles
are non-refrigerated, same cost table as the FPO's, no markup; farmers know price/spoilage but not market crowding.
`match_ilo_accounting=True` makes the baselines copy ILO's conventions (no return leg, absolute-clock spoilage).

**Result (synthetic data, 3 seeds, value incl. farm-gate, 20% discount).** ILO vs best realistic baseline:
n=50 -15.3%, n=300 -8.3%, n=1000 -9.8% (like-for-like accounting: -12.8% / -8.6% / -9.8%; 10% discount: -19% / -11% / -11%;
30% discount: -13.5% / -5.0% / -8.0%). **On this data ILO currently loses to simply selling at the farm gate**, while it
still beats both legacy baselines by a wide margin. Cause, measured: ILO's economic dispatch withholds a trip only when
net return < 0, not when it is < the farm-gate value of that produce. 83% (n=300) and 86% (n=1000) of the pools ILO
dispatches earn less than farm-gate (hauled net 1.10M vs 1.49M at n=300; 2.01M vs 3.55M at n=1000). The synthetic
geography also puts mandis ~125 km (median) from farmers at n=1000, which favours not hauling.

**Next step this points to:** set `DISPATCH_MIN_NET` to a per-pool opportunity cost (the pool's farm-gate value) in
`run_our_system_v2`, then re-run `benchmark_baselines_v3.py`. Not done here (the brief was the baselines only).
Re-run on the Bihar real-data preset before quoting any figure externally.

**Known limitations.** ILO still charges no return leg and measures spoilage from the absolute clock; the like-for-like
mode neutralises this for the comparison but ILO itself is unchanged. Self-haul/neighbour decisions use expected, not
crowding-adjusted, revenue. Tests: `backend/tests/test_realistic_baselines.py` (existing economic-dispatch tests also
re-run, all passing; run here through a small shim because pytest could not be installed offline).


---

## 19. Behavioural baselines and the rebuilt Bihar preset

### 19.1 Baselines are now behavioural (what the comparison tab shows)
Individual Transport and Proximity Pooling are `run_self_haul_v2` and `run_neighbour_pooling_v2` (`baselines_v3.py`)
in their BEHAVIOURAL tier. Farmers do not compute profit. A farmer (or a group of up to 4 neighbours within 5 km)
hauls iff the nearest mandi buying the crop is within `max_haul_km` (40) AND its posted price beats the trader's offer
by `price_margin` (10%); otherwise they sell at the farm gate. Hired trucks are SPOT hires (not the FPO fleet): they cost
`spot_markup` (1.15x) and arrive `spot_lead_hr` (1 h) after the request. A group waits for its last member, routes
nearest-first, and a pickup after someone's deadline is a no-show (that farmer sells at the farm gate). Because nobody
checks the arithmetic, some trips lose money and some profitable ones are skipped.
All four numbers are ASSUMPTIONS, not data (`Behaviour` dataclass; change them in one place). The RATIONAL tier
(`behaviour=None`: exact economics, hauls only if it beats the farm gate) and the farm-gate-only reference are kept as
yardsticks and returned by the API under `realistic_baselines`; the legacy strawmen are kept there as `legacy_*`.
Farm-gate price = (1 - `FARMGATE_DISCOUNT`) x median mandi price (20%, an ASSUMPTION), via `FarmgatePrices`.

Accounting. ILO v2 charges no empty-return leg and measures spoilage from hour 0. `main.py` therefore costs the
baselines the same way (`match_ilo_accounting=True`) so the comparison is like-for-like; with the physically correct
accounting the baselines would pay a return leg and ILO would not, which tilts the table in ILO's favour.

UI changes: the headline is "farmer value" (net return + value of produce not hauled at the farm-gate price) because a
plain net return scores a farmer who sold at the doorstep as zero. Farm-gate sellers are slate on the map and are listed
in `farmgateFarmerIds`, never in `unservedFarmerIds`; spot trucks appear as "Spot-hired ..." vehicles with ids that cannot
collide with the fleet. The three synthetic demo scenarios were re-run: ILO still beats both baselines in all three under
the like-for-like accounting (cold chain 44.7k vs 37.1k / 31.9k, market arbitrage 53.4k vs 11.8k / 12.3k, fleet scarcity
45.7k vs 42.0k / 42.5k farmer value). In scenario 3 only ILO is limited to the 3-vehicle fleet (the baselines hire), so ILO
sells less produce at a market (46.6% vs 100% / 53.4%) and still earns more.

### 19.2 Rebuilt Bihar preset (`bihar_dec2025_feb2026`)
Source: the India Data Portal "APMC Arrivals and Prices (New Source)" CSV, 27 Oct 2025 - 1 Apr 2026, imported with
`import_idp_csv.py --from 2025-12-01 --to 2026-02-28` and built with `build_real_markets.py`. What changed vs the old preset
(`bihar_mar2026`):
- One window for all mandis (Dec-Feb) instead of 3 Mar - 1 Apr. Potato fell across Bihar from October to March, so a
  one-month window is a snapshot of a falling price, and Piro (Bhojpur, the farmers' own district; the only onion mandi near
  them) stopped reporting on 23 Feb and was invisible to the March window.
- Added Piro (25.33, 84.42; Wikipedia, ~1 km) and Natwar (25.23, 84.16; India Post list; another site says 25.21, 84.25).
  Dropped Barahat (184 km+ from every farmer). Brahmpur, Motihari and Bahadurganj report prices but have no reliable
  coordinates, so they are left out and listed in `meta.dropped_no_coords`.
- Capacity is still the median reported daily arrival, but series where one value repeats on over 70% of days (and at
  least 20 days) are now flagged `capacity_is_placeholder`: Aarah 1.33 t (95% of days), Tajpur 2 t (96%), Natwar 4 t (99%),
  Buxur 5 t (98%), Chakia 60 t (98%), Barahat 4 t (100%). These are reporting defaults, not measurements.
- Farmers and fleet are UNCHANGED (same generator, seed 0, 34 farmers, 8 vehicles): they are SYNTHETIC, so only the mandis
  changed and the two presets are directly comparable on that axis. No FPO records were available.
- Farmer reach to a buying mandi is now: potato median 44 km, 7 of 17 farmers within 40 km; onion median 51 km, 5 of 17
  within 40 km (before: none within 40 km for onion).
Result (ILO v2 vs the behavioural baselines, like-for-like accounting, synthetic farmers, ASSUMED farm-gate discount; farmer
value): discount 10%: +0.7% vs both baselines and vs farm-gate only (no trip pays, so everyone sells at the doorstep);
20%: +32.4% vs Individual, +23.5% vs Proximity, +12.9% vs farm-gate only; 30%: +50.0% / +39.6% / +28.7%.
If farmers will travel further (reach 80-150 km) the behavioural baselines make 16-20 trips and lose money on most of them,
so ILO's lead grows to +88% / +44% at 20% (the baselines' lead over farm-gate shrinks as they haul more). The rational
baselines stay within about 3% of farm-gate only: their best option is almost always not to haul.
Caveats that matter: the size of ILO's lead depends on the assumed discount and on Sheohar's premium (potato Rs 22/kg and
onion Rs 24 against medians of Rs 12.5 and Rs 20), which the baselines never reach because they only visit the nearest
mandi; whether Sheohar's price holds when more volume arrives is untested; and the farmers are synthetic.
Reproduce: `python real_data/import_idp_csv.py <csv> --state Bihar --from 2025-12-01 --to 2026-02-28`, then
`python real_data/build_real_markets.py`, then `python real_data/make_preset_block.py --id bihar_dec2025_feb2026 ...`.


---

## 20. ILO v3 applied to this project

`ilo_v3.py` (Phases 1-5, see its module docstring) now produces the recommended plan (`integrated_logistics_optimization`
in `/plan/compute`). It needs the new options added to `run_our_system_v2` in `algorithms_v2.py` (all default to the old
behaviour; with them off the output is identical to the previous version). ILO v2 is still computed, only as a legacy
reference under `realistic_baselines.legacy_ilo_v2`; `realistic_baselines.ilo_meta` says which plan v3 returned
(`chosen`), its candidate counts and solver status. The comparison baselines are now costed with the correct accounting
(empty return leg, spoilage from pickup), the same as v3. ILO's per-market received-kg (map and story) still comes from an
exact trace; it is empty when v3 returns a baseline plan. Deliberately unhauled pools are flagged `sold_at_farmgate`, so the
map shows them slate, not red; pools that wanted a truck and got none stay red.

### 20.1 Results, rebuilt Bihar preset (synthetic farmers; farm-gate discount ASSUMED; value = net return + farm-gate sales)
At the default 20% discount: ILO v3 Rs 208,586 vs best baseline Rs 167,803 (rational neighbour pooling) = +24.3%; vs
behavioural Individual +54.0%, behavioural Proximity +42.2%, farm-gate only +28.3%. v3 runs 4 trips (8.2 t hauled, 64.5%
sold at a market, 14 farmers at the farm gate); ILO v2 ran 17 trips but its number omits the return leg and counts spoilage
from hour 0, so it is not comparable (it would not survive the honest accounting).
Across discount 5/10/20/30/40%: +12.2 / +15.5 / +24.3 / +33.0 / +53.9% vs the best baseline. If the planner assumes 20% and the
truth is 10% / 30%: +16.4% / +33.3%. Stress tests: mandi capacities x0.5 / x2 / x5: +10.0 / +28.8 / +34.1%; Sheohar's prices
cut 15 / 30 / 45%: +14.5 / +8.7 / +11.2%; Sheohar removed: +9.3%.
Fairness check: the shipped "rational" baselines only visit the NEAREST mandi. A stronger rational baseline that picks the
best mandi per farmer or neighbour group with exact economics (not a shipped baseline) reaches Rs 193-197k / 177-181k /
136-145k at 10 / 20 / 30%; ILO v3 is still +9.4 / +15.3 / +37.8% ahead of it. So the lead is not only market choice.
### 20.2 Demo scenarios (20% discount, same accounting for all)
- Cold chain: ILO v3 56.2k vs behavioural Proximity 56.1k / rational Proximity 55.9k / behavioural Individual 53.3k: a tie
  (+0.1% vs the best). Pulling the mandis further away does not help: at ~32 km +1.9%, at 64 km+ nobody hauls. The earlier
  advantage came from ILO v2's spoilage clock (from hour 0) charged to the baselines; with spoilage counted from pickup the
  refrigeration effect is small at these distances. The scenario shows the mechanism, not a win (its blurb now says so).
- Market arbitrage: 54.3k vs best baseline 13.4k (+306%). Fleet scarcity: 50.4k vs 45.6k (+10.4%), 93% sold at a market in 3
  trips (v2: 2 trips, 47%).
### 20.3 What this does not show
Farmers, lots, ready times and the fleet are synthetic and the farm-gate price is an assumption; the result depends on price
differences between mandis (Sheohar potato Rs 22, Piro Rs 15.9, Buxur Rs 14 against a median of Rs 12.5) being capturable,
and no price response to extra volume is modelled. Six of the mandi-crop capacities are reporting defaults. ILO's own
safeguard never fell back to a baseline in these runs. 71 backend tests pass.
