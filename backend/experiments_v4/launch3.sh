#!/bin/sh
cd /home/claude/farmroute-optimizer-main/backend
for s in 0 1 2 3; do python3 experiments_v4/oracle.py 15 $s; done
python3 experiments_v4/run_grid.py experiments_v4/results_scale.jsonl D 300 1,2 V0_zip,TL120,BEST,knn_forced
