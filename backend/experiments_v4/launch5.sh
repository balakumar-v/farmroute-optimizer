#!/bin/sh
cd /home/claude/farmroute-optimizer-main/backend
R=experiments_v4/run_grid.py; O=experiments_v4/results_main.jsonl
python3 $R $O G 60 0,1,2,3,4,5 BEST+MIX,C13+CG2+V1
python3 $R $O D 150 0,1,2,3,4,5 BEST+MIX,C13+CG2+V1
python3 $R experiments_v4/results_scale.jsonl D 300 1,2 V0_zip,BEST,knn_forced
