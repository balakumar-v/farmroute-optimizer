# Planner-variant study

Measures whether optional changes to ILO's candidate generation, spoilage handling and column selection improve farmer value. Every switch defaults to off; the code lives in the hooks in `ilo_v3.py`, in `ilo_v3_ext.py` and in `algorithms_v2.keep_pool_order`.

## Switches (environment variables)

`ILO_KEEP_ORDER` (C1) | `ILO_SIM_SPOIL` (C3) | `ILO_BOTH_DIRS` (C2) | `ILO_CW_LAMBDAS` | `ILO_ENRICH` (V1) |
`ILO_MIXED` (mixed-crop Clarke-Wright) | `ILO_CAP_SLACK` | `ILO_ROAD_DBSCAN` | `ILO_COLGEN=<rounds>` (dual-guided column generation) |
`ILO_SP_TIME_LIMIT` | `ILO_CW_ALL_PAIRS_MAX`

## Protocol

- `common.py`: one protocol for every variant: the same scenario, seed and road matrix. Roads are a synthetic road network (a jittered lattice with some edges removed and a few fast corridors, all-pairs shortest paths), so results do not depend on an online routing service.
- `variants.py`: the variants compared, as sets of the switches above. `run_grid.py`: runs one family, size and seed list, and can be resumed. `analyze.py`: paired comparison table.
- `oracle.py`: complete-column oracle for small instances (n = 15 to 20), an upper bound for what better column selection could reach.

## Results

Each line of a `.jsonl` file is one run (family, size, seed, variant, value, gain over farm-gate, runtime, which plan was chosen, solver status).

| File | Contents |
|---|---|
| `results_main.jsonl` | Main grid: families G (60 farmers) and D (150 farmers), all main variants, several seeds |
| `results_turn.jsonl` | Turnaround-time sensitivity |
| `results_scale.jsonl` | Larger instances (family D, 300 farmers) |
| `results_n15.jsonl` | Small instances (family G, 15 farmers) |
| `results_knn.jsonl` | Clarke-Wright restricted to nearest-neighbour pairs (family D, 150 farmers) |
| `results_presets.jsonl` | The real-data presets |
| `results_mixfix.jsonl` | Mixed-crop runs on a preset |
| `oracle.jsonl`, `oracle_single.jsonl`, `oracle_multi.jsonl` | Complete-column oracle (n = 15) |

Reprint the main table from `backend/`: `python3 experiments_v4/analyze.py experiments_v4/results_main.jsonl`
