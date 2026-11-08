#!/bin/sh
cd "$(dirname "$0")/../.."
R=experiments/v4/run_grid.py
sh experiments/v4/launch_main.sh
python3 $R experiments/v4/results_turn.jsonl G 60 0,1,2,3 V0_zip,V0@T0,V0@T2.5,BEST,BEST@T0,BEST@T2.5
python3 $R experiments/v4/results_turn.jsonl D 150 0,1,2,3 V0_zip,V0@T0,V0@T2.5,BEST,BEST@T0,BEST@T2.5
python3 $R experiments/v4/results_scale.jsonl D 300 0,1,2 V0_zip,TL120,BEST,BEST+TL120,knn_forced
for s in 0 1 2 3; do python3 experiments/v4/oracle.py 15 $s; done
for s in 0 1 2; do python3 experiments/v4/oracle.py 20 $s; done
