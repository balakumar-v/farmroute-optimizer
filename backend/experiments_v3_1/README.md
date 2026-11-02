# Experiments behind the v3.1 changes (Oct 2026)

Scripts that produced the numbers in `ALGORITHM_AND_RESULTS_V2.md` sections 22 to 25. Run them from `backend/`
(`python experiments_v3_1/<script>.py`), except `price_flexibility_regression.py`, which expects to run from
`backend/real_data/`. All use the synthetic generator (`generate_scenario_v2`), so they test the mechanisms,
not your region. Several take 3 to 10 minutes (HiGHS solves plus simulator replays); pipe the output to a file.

| Script | Question | Section |
|---|---|---|
| `scalability.py` | How does ILO v3's value and runtime change with n? | 22.1 |
| `fleet_aware_vs_blind.py` | Does the fleet-aware set partition beat the fleet-blind one? (committed case list is the second half of the original sweep, 2 seeds) | 22.2 |
| `road_circuity_truth_vs_planner.py` | What does it cost to plan with the wrong road circuity? | 22.3 |
| `price_flexibility_regression.py` | What price flexibility (eta) do the Agmarknet files imply? | 22.4 |
| `price_impact_belief_vs_truth.py` | Does planning with price impact pay, and what if eta is wrong? | 22.4 |
| `discount_assumption_vs_truth.py` | Which farm-gate discount should the planner assume? | 22.5 |
| `monte_carlo_filter.py` | Does withholding fragile trips improve the downside? | 22.6 |
| `spoilage_sensitivity.py` | Do ILO's ranking and plans depend on the spoilage parameters? | 23 |
| `trip_structure_probe.py` | Capacity x3, top-K cut, mixed-crop trips and capacity binding on synthetic scenarios (SP objective) | 24 |
| `trip_structure_end_to_end.py` | The same, full pipeline, n=150 | 24 |
| `trip_structure_presets.py` | The same on the five real-data presets (`python experiments_v3_1/trip_structure_presets.py [preset keys]`) | 24 |
| `soft_capacity.py` | Hard vs soft mandi capacity: planner belief vs scoring world, presets and synthetic | 25 |
| `_trip_helpers.py` | shared helper (mixed-crop candidate generator); not a script | - |

Seeds are fixed in each script. Results move a little with HiGHS version and platform (time-limited MILPs).
