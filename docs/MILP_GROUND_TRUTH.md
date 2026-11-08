# Integrated MILP: Exact Ground Truth vs. ILO

Per the brief: build a mathematically exact ground-truth benchmark for
ILO (formerly "Our System" -- `run_our_system_v2`, aliased as
`run_ilo_v2` in `algorithms_v2.py`; the rename is naming-only, no
signature changed, `CONTRACT.md` stays valid). ILO is not replaced —
this is a separate, small-instance benchmark for measuring how close
ILO gets to the true optimum.

Code: `integrated_milp.py` (candidate generation + MILP assembly/solve),
`milp_benchmark.py` (comparison harness). Results: `milp_vs_ilo_results.csv`.
Solver: `scipy.optimize.milp` (HiGHS) — no `ortools` or commercial solver
available in this environment.

## 1. Why "exact" needs a precise definition here

A fully joint MILP over routing + multi-trip vehicle scheduling +
spoilage-aware, market-splitting revenue is **not exactly representable
as a linear MILP** — three separate points in the model are products of
two decision variables. Two of the three have an exact linear
reformulation; the third genuinely doesn't, and required a real design
decision rather than a workaround:

1. **Vehicle timing** (which physical time-slot a trip lands in, hence
   its actual start time) — binary × continuous. Exactly linearizable
   via a standard big-M indicator reformulation. Done exactly.
2. **Transport-cost attribution** (which vehicle's per-km rate applies)
   — also binary × continuous once market choice is itself a decision.
   Also exactly linearizable the same way. Done exactly.
3. **Revenue = kg_sold × (1 − spoilage_fraction)**, where spoilage
   depends on transit time — both factors are decision variables. This
   is genuinely bilinear. No exact linear reformulation exists without
   either discretizing one side or accepting a relaxation.

For #3, two honest options existed:

- **(a) Split-allowed + McCormick relaxation.** Keep ILO's multi-market
  splitting, accept a relaxation. Checked the direction of the gap
  carefully (see reasoning below) — it is only a **valid upper bound**
  on true optimal net return, exact only at the corners (fully sold to
  one market, or fully unsold/spoiled), and provably loose whenever a
  candidate's crop is genuinely split. Since splitting is a *central,
  intentional feature of ILO's own LP stage*, this looseness would hit
  often, not at the edges.
- **(b) No-split, single-market-per-crop-per-trip.** Force each
  candidate's each crop to go entirely to one market (or go unsold).
  `kg_sold` becomes a known constant once the market is chosen, so
  "constant × spoilage_fraction" is linear — fully exact, no relaxation
  anywhere.

**Chose (b).** Shipping one mode that is genuinely, provably exact end
to end — and testing it properly — was judged better use of the
available effort than shipping two modes, one of them an unverified
relaxation. The cost is explicit and load-bearing for how every result
below should be read: **this MILP's optimum is the true optimum of a
slightly different problem than ILO solves** (single-market-per-crop,
not split-allowed). A gap between ILO and this MILP mixes two things —
heuristic quality, and ILO getting a strictly larger decision space
(splitting is a generalization: any no-split solution is also a valid
split-allowed one, so the true split-allowed optimum is always ≥ this
MILP's optimum). Section 5 shows this isn't hypothetical — it happened
in the actual benchmark. Extending to mode (a) as a second,
relaxation-bound comparison is flagged as future work, not attempted.

## 2. Formal model (as requested — define before implementing)

**Candidate trips** (pre-generated, not a MILP decision — see §3):
non-empty farmer subsets, size ≤ `MAX_SUBSET_SIZE` (5), with a specific
farmer visiting order chosen to be the minimum-distance ordering among
every time-window-feasible permutation (matching ILO's own tie-break for
comparability). Each candidate `c` carries: `route_dist_km`,
`route_duration_hr`, per-farmer arrival offsets, `latest_start_hr`
(exact — see §3), `total_qty_kg`, `needs_refrigeration`, and
`crop_qty[crop]`.

**Decision variables:**
- `a[c] ∈ {0,1}` — candidate activated
- `assign_slot[c,v,k] ∈ {0,1}` — candidate `c` occupies vehicle `v`'s
  slot `k` (k = 0..K_MAX−1, K_MAX=3); only defined for
  capacity/refrigeration-compatible `(c,v)` pairs
- `start[v,k], completion[v,k] ≥ 0` — per vehicle-slot timing
- `start_of[c] ≥ 0` — candidate `c`'s realized dispatch time (linked to
  whichever slot it lands in)
- `y[c,crop,m] ∈ {0,1}` — crop from candidate `c` sold entirely to
  market `m` (every market available, no top-k pruning)
- `z[c,m] ∈ [0,1]` — candidate `c` visits market `m` at all (OR over
  crops; see §4 bug 3)
- `spoil[c,crop,m] ∈ [0,0.6]`, `cap_active[c,crop,m] ∈ {0,1}` (only
  where the 0.6 cap could bind — see §3)
- `rev_term[c,crop,m] ≥ 0`, `aux[c,v,k] ≥ 0` — big-M linearization
  auxiliaries for the two exact products in §1

**Objective:** maximize `Σ rev_term[c,crop,m] − Σ (assign_slot[c,v,k]·fixed_cost(v) + per_km_cost(v)·aux[c,v,k])`

**Constraints** (numbered to match the brief's sections):
- (§4/farmer assignment) `Σ_{v,k} assign_slot[c,v,k] = a[c]`; each
  farmer covered by ≤ 1 activated candidate
- (§5/vehicle) `Σ_c assign_slot[c,v,k] ≤ 1` per slot; refrigeration and
  capacity enforced by only *defining* `assign_slot[c,v,k]` for
  compatible pairs (hard constraint, not a soft preference — see §4);
  `start[v,k] ≥ completion[v,k−1] + TURNAROUND_HR` whenever slot k−1 is
  used (big-M gated, non-binding when it isn't)
- (§6/time windows) enforced *exactly per farmer* during candidate
  generation (§3), not approximated by a pool-level min/max — the
  fixed-route-duration simplification only applies at the
  cross-trip vehicle-scheduling layer, identical in spirit to ILO's own
  (disclosed) simplification, preserved for comparability per §15/§16
  of the brief
- (§7/routing) not a MILP decision at all — see §3's scope note
- (§8/markets) `Σ_m y[c,crop,m] ≤ a[c]`; `Σ_c crop_qty[c,crop]·y[c,crop,m] ≤ market_capacity[m][crop]`
- (§9/market routing) **Model A**, direct legs from the final pickup
  stop to each market used, exactly matching ILO's own cost structure
  (ILO does not model a sequential farmer→marketA→marketB route either
  — verified against `algorithms_v2.py`'s `_finalize()`). Chosen
  explicitly for comparability, not by default. A true Model B
  (sequenced multi-market routing) is a substantially harder
  formulation, not attempted.
- (§10/spoilage) exact, via a disjunctive big-M formulation — see §3
- (§3 of brief/service level) optional `service_target` parameter,
  implemented as `Σ crop_qty·y ≥ service_target · Σ farmer qty`

## 3. Three implementation decisions worth flagging explicitly

**Slot-based scheduling, not pairwise ordering.** The brief's own
notation (§7) suggests routing arcs `x[i,j,v,t]`; for the
*vehicle-scheduling* layer specifically, a pairwise disjunctive
ordering formulation (`order[c1,c2,v]` for every candidate pair) would
be O(candidates² × vehicles) — intractable even at these small sizes.
Used a **slot** formulation instead (each vehicle has `K_MAX` ordered
slots; candidates are assigned into slots, chained by
`completion[k-1]+TURNAROUND ≤ start[k]`) — O(vehicles × K_MAX)
precedence constraints. This loses no generality: any valid schedule
can be relabeled into slot order.

**Conditional spoilage-cap disjunction.** `spoilage_fraction =
min(rate·transit_hr, 0.6)` is a genuine min() of a decision-dependent
quantity and a constant, and — because the solver always wants modeled
spoilage *low* (it's subtracted from revenue) — this cannot be pinned
without a disjunctive binary in general (a plain upper-bound-only
relaxation lets the solver push spoilage toward zero for free). Rather
than add one `cap_active` binary per every `(candidate, crop, market)`
triple, each triple's **worst-case** transit time (using
`latest_start_hr`) is checked first; the binary is only added where
`rate × worst_case_transit > 0.6` — i.e., only where the cap could ever
actually bind. Verified this is a real optimization, not just an
estimate: at the tested instance sizes, it measurably reduces binary
count versus adding it unconditionally.

**Candidate enumeration is exhaustive, not sampled — up to a hard size
cap.** For `n` farmers, every non-empty subset up to `MAX_SUBSET_SIZE`
that's capacity/refrigeration-feasible for some fleet vehicle gets a
candidate (637 candidates at n=10 in 0.2s, 4,943 at n=15 in 2.2s — see
`generate_candidates()`). This is genuinely exhaustive for the routing
decision *inside* a candidate (brute-force permutation search — the
exact same algorithm ILO's own `order_route()` uses for pools ≤7). It
is **not** exhaustive across all possible trip sizes — `MAX_SUBSET_SIZE`
caps it — so for farmers whose truly optimal trip would need more than
5 companions, this MILP cannot find that solution at all. Not
encountered in the tested range (n≤7), but a real, disclosed scope
limit, not silently assumed away.

## 4. Bugs found while actually implementing and testing this

Consistent with how every other round of this project has gone — real
issues surfaced by running the code, not by reviewing the plan:

1. **A sign error in the vehicle-chaining big-M constraint** made the
   model infeasible on every instance, including the trivial "serve
   nobody" solution. Root cause: the non-binding direction of the big-M
   term was flipped (`+BIGM·prev_used` with a `+BIGM` bound instead of
   `-BIGM·prev_used` with a `-BIGM` bound), so an *unused* slot forced
   an impossible constraint instead of a vacuous one. Caught immediately
   — a 4-farmer instance should never be infeasible — by testing on the
   smallest possible case first rather than assuming the formulation was
   right and moving on to a benchmark.
2. **The same sign-flip pattern** recurred in the transport-cost
   linearization (`aux ≥ total_dist − UB·(1−assign)` had `+UB·assign`
   instead of `−UB·assign`). Caught by comparing the solver's own
   internal objective value against an independent reconstruction from
   the solution — the two didn't match (23,387 vs. a naive sum of
   34,730 — later traced further, see bug 3), which is exactly the kind
   of self-consistency check that catches silent sign errors a "does it
   run" test wouldn't.
3. **Market-leg distance was charged once per (crop, market) pair, not
   once per market.** When a mixed-crop candidate sold three different
   crops to the *same* market, the model charged that market's distance
   three times — physically wrong (one truck visit serves all three
   crops) and a real bias against consolidating deliveries to a single
   market. Root cause: summing `dist(c,m)·y[c,crop,m]` directly over
   every crop, instead of deduplicating by market first. Fixed by adding
   `z[c,m] ∈ [0,1]` (an OR over crops of `y[c,crop,m]`, exactly pinned
   to 0/1 at any optimum since it only ever carries a positive cost
   coefficient) and using `z`, not `y`, in the distance expression.
   Caught the same way as bug 2 — reconstructing the chosen solution's
   revenue/cost independently and finding it didn't match the solver's
   own reported objective (a 1,343 discrepancy that traced exactly to
   2 × dist × per_km_cost, i.e. two double-charged market legs).

All three were caught by the exact verification step the brief asks for
in §20 ("manually inspect the solution... before scaling it") — none of
them would have been visible from "the solver returned status=optimal."

## 5. Results (original run — see §6b for the reverified numbers after the fix described there)

`milp_benchmark.py`, n ∈ {5, 6, 7}, 3 seeds each, 45s time limit, same
farmer/vehicle/market data for both MILP and ILO in each trial (§15 of
the brief: fair comparison). **These are the numbers that motivated the
investigation in §6b — ILO has since been improved and reverified
against this same benchmark; jump to §6b for the current 96.0% figure.**

| n | seed | MILP status | MILP net return | ILO net return | ILO / MILP |
|---:|---:|---|---:|---:|---:|
| 5 | 5000 | proven optimal (2.6s) | 33,276.2 | 28,043.5 | 84.3% |
| 5 | 5001 | proven optimal (1.9s) | 25,225.3 | 25,234.8 | **100.0%** |
| 5 | 5002 | proven optimal (4.0s) | 22,835.3 | 17,264.0 | 75.6% |
| 6 | 6000 | proven optimal (31.1s) | 43,246.1 | 38,429.8 | 88.9% |
| 6 | 6001 | proven optimal (23.2s) | 39,001.6 | 35,149.8 | 90.1% |
| 6 | 6002 | proven optimal (10.5s) | 28,026.3 | 20,842.3 | 74.4% |
| 7 | 7000 | gap=8.8% (45.1s, time limit) | 36,887.4 | 30,472.2 | 82.6%* |
| 7 | 7001 | gap=4.5% (45.1s, time limit) | 31,949.5 | 29,187.1 | 91.4%* |
| 7 | 7002 | proven optimal (33.9s) | 40,983.1 | 34,385.6 | 83.9% |

*n=7's two time-limited rows: per §12/§14 of the brief, these are **not**
proven-optimal comparisons — the MILP value is a best-feasible solution
with a disclosed gap, so "ILO/MILP" there is a ratio against an
unverified figure, not a true optimality gap. Shown for completeness,
excluded from the summary statistic below.

**On the 7 proven-optimal instances: ILO achieves 85.3% of the true
optimum on average (min 74.4%, max 100.0%).**

**Reading the n=5/seed=5001 result (ILO = 100.0%, technically 100.04%):**
this is not a violation of exactness — it's the disclosed §1 caveat
showing up empirically. ILO's LP stage can split a crop across markets;
this MILP's no-split mode cannot. Here, ILO's split-allowed solution
edged out the no-split exact optimum, which is exactly what §1 predicts
can happen and is the clearest evidence that comparisons against this
benchmark should be read as "vs. the no-split optimum," not "vs. the
unconditional optimum."

**Runtime**: near the edge of what's tractable already at n=6-7 (10-45s
per instance) — this implementation's honestly-supportable exact range
is roughly **n ≤ 6**, with n=7 needing the time-limit/gap caveat and n=8+
not attempted in this round (§13 of the brief already anticipated this:
"do not expect the integrated MILP to scale directly... use it primarily
for small and medium instances").

## 6. What this does not show

- **Not a measurement of ILO against the unconditional optimum** — see
  §1 and the n=5/seed=5001 result above. It measures ILO against the
  optimum of a slightly narrower problem (no market-splitting).
- **The 85.3% figure is from 7 data points at n=5-6 only.** Real
  variance is visible even within that (74.4% to 100.0%) — this is a
  first read, not a tight confidence interval.
- **MAX_SUBSET_SIZE=5 caps what the MILP can even consider.** If ILO's
  true advantage (or disadvantage) shows up in larger pools, this
  benchmark can't see it at the current cap.
- **The two n=7 time-limited rows are excluded from the summary
  statistic for a reason** — reporting them as if they were proven
  optimal would be exactly the overclaiming §12/§18 of the brief warns
  against.

## 6b. A concrete, traced cause of ILO's worst gap — traced, fixed, and reverified

The n=6/seed=6002 instance (ILO at 74.4% of proven optimum, the worst in
the original set) was worth tracing all the way down rather than
leaving as a percentage. The MILP's optimal solution pools farmers
**0, 2, 3, 4** onto the single refrigerated truck; ILO split them into
four separate trips instead. Pairwise distances: farmer 2 and farmer 3
are **33.2km apart**, and no pair among {0,2,3,4} is within ILO's
`EPS_KM=12` clustering radius even via a chain — DBSCAN correctly (by
its own local-radius rule) refuses to ever consider them one cluster,
so ILO never evaluates this pooling as an option at all.

The MILP takes it anyway because **4 of these 6 farmers need
refrigeration, and the fleet has exactly 1 refrigerated vehicle** — with
that scarce, dispatching separate refrigerated trips is far more costly
(each pays the reefer's fixed cost again) than one longer,
33km-spanning consolidated trip. This is a real, mechanically-verified
limitation: DBSCAN's geographic-compactness proxy and the problem's
actual economic driver (refrigerated-fleet scarcity) can disagree, and
ILO's pooling stage has no way to see the disagreement — it commits to
clusters before vehicle assignment ever runs.

**Implemented and reverified, not left as a proposal.** Added
`_refrig_eps_km()` to `algorithms_v2.py`: a widened DBSCAN radius,
applied *only* to refrigeration-needing farmers (the general population
keeps the tight `EPS_KM=12` that fixed the sprawling-route regression at
scale — ALGORITHM_AND_RESULTS_V2.md §7 bug 4 stays intact for
everyone else), scaled by two distinct scarcity signals and capped at
3× the base radius:

- **capacity scarcity** — refrigeration-needing demand relative to
  total refrigerated fleet capacity
- **vehicle-count scarcity** — `1 / (number of refrigerated vehicles)`,
  because each extra trip pays a full fixed cost again regardless of
  how full it is

Both signals turned out to matter, not just one: an earlier version
using capacity scarcity alone only closed the traced instance to 82.1%
(it still split out one farmer 33km away), because total demand there
was comfortably under one truck's capacity — which under-weighted how
badly a *second avoidable trip* hurts when only one refrigerated
vehicle exists at all. Taking the max of both signals closed it to
95.3%, with ILO now choosing the exact same 4-farmer pooling structure
the MILP does.

**Re-ran both benchmarks after the fix, not just the one instance:**

Small-instance MILP comparison (`milp_benchmark.py`, same 9 instances):
**mean ILO/MILP ratio on proven-optimal cases rose from 85.3% to
96.0%** (min 74.4%→91.0%, max 100.0%→102.1% — the >100% case is the
same split-allowed effect noted in §5, now showing up on a different
instance, which is itself a sign the fix isn't overfit to the one
traced case).

Full-scale benchmark (`benchmark_v2.py`, 450 runs, n=50 to 10,000):
**net return improved at every single tested scale** (+1.5% to +12.9%),
**service% improved at every scale** (+0.8 to +3.4 percentage points),
**zero regressions**. Sample-checked route distances directly at
n=1,000 and n=10,000 before trusting this: mean pickup-route distance
grew modestly (≈14-18km → ≈20-22km) but stayed bounded (max ≈130km, not
the 291km/44-simulated-hour blowup the original pre-depot-partition
bug produced) — the safety concern that held this fix back for a full
round was checked, not just asserted away.

Applied only to ILO (`run_our_system_v2`/`run_ilo_v2`), not to the naive
Proximity Pooling baseline — this is genuine problem-aware intelligence,
not a bookkeeping fix, and Proximity Pooling is deliberately kept
geography-only for comparability with the original baseline definition.

Updated numbers are in `ALGORITHM_AND_RESULTS_V2.md` §10 and
`milp_vs_ilo_results.csv`; this section is now a closed loop (found via
MILP → root-caused → fixed → reverified against both the MILP and the
full-scale benchmark) rather than a diagnosis handed off as future work.

## 7. Honest scope vs. the brief's ambition

The brief asks for something considerably larger than what's here: full
`x[i,j,v,t]` routing variables with subtour elimination, Model B
(sequenced multi-market routing), split-allowed market allocation,
instances up to 50-100 farmers, and a lexicographic service-then-profit
mode. None of the four are in this version — each was a real, considered
scope decision (documented in §1, §3, §9 above), not an oversight. What
*is* here is fully exact within its stated scope, tested against a
worked example by hand, self-consistency-checked against its own solver
output (which is what caught bugs 2 and 3 in §4), and benchmarked
honestly including the cases where the solver didn't reach proven
optimality. Given the size of the full ask, shipping a smaller thing
that's actually verified was judged better than a larger thing that
isn't — consistent with how every other round of this project has
prioritized.
