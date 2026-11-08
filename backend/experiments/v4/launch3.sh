#!/bin/sh
cd "$(dirname "$0")/../.."
for s in 0 1 2 3; do python3 experiments/v4/oracle.py 15 $s; done
python3 experiments/v4/run_grid.py experiments/v4/results_scale.jsonl D 300 1,2 V0_zip,TL120,BEST,knn_forced
