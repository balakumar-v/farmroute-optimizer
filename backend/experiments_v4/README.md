# experiments_v4 - ILO v3 improvement study (snapshot, queue still running)
Switches (all default OFF; code in ilo_v3.py hooks + ilo_v3_ext.py + algorithms_v2.keep_pool_order):
ILO_KEEP_ORDER (C1) | ILO_SIM_SPOIL (C3) | ILO_BOTH_DIRS (C2) | ILO_CW_LAMBDAS | ILO_ENRICH (V1 = reconstruction of prior session)
ILO_MIXED (mixed-crop CW) | ILO_CAP_SLACK | ILO_ROAD_DBSCAN | ILO_COLGEN=rounds (dual-guided column generation, CG) | ILO_SP_TIME_LIMIT | ILO_CW_ALL_PAIRS_MAX
Protocol: common.py (synthetic road network, same scenario/seed/matrix per variant), variants.py, run_grid.py (resumable),
analyze.py (paired table), oracle.py (complete-column oracle, n=15-20).
Results: results_main.jsonl (G60, D150 x 9 variants x 6 seeds), results_turn.jsonl (turnaround sensitivity),
results_scale.jsonl (D300, may be partial), oracle.jsonl (may be absent).
Re-run table: python3 experiments_v4/analyze.py experiments_v4/results_main.jsonl
Tests after edits, all switches off: 155 pass, 4 fail (same 4 as before: missing agmarknet module). Logs: pytest_after.log.

Extra results: results_n15.jsonl, oracle_multi.jsonl / oracle_single.jsonl (complete-column oracle, n=15), results_scale.jsonl (D300).

Addendum: ILO_ITER (sim-in-the-loop, already in the zip) re-tested uncontended. results_presets.jsonl / results_knn.jsonl /
pytest_default_off.txt / real_data run_preset were produced by a SECOND job sharing this directory (not by the author of the rest);
treat those as unaudited. Runtime figures from the period when both jobs ran are contended (preset rows: secs inflated).

Final addendum: ILO_HOLD_SINGLES=1|2 (algorithms_v2.hold_pools) tested: null (see results_scale.jsonl / results_main.jsonl rows *+HOLD, *+HOLD2).
n=300 SP-vs-simulator gap (27-38%) is UNEXPLAINED: not vehicle starvation, not valuation error, not (mainly) leftover singles.
Tests after all edits, all switches off: 155 pass, 4 fail (missing agmarknet) - see pytest_final2.log.
