#!/bin/sh
cd /home/claude/farmroute-optimizer-main/backend
V=V0_zip,V1_cw5+enrich,C1_keeporder,C3_simspoil,C13,C123,C13+V1,C13+CG2,C13+CG2+V1
python3 experiments_v4/run_grid.py experiments_v4/results_main.jsonl G 60 0,1,2,3,4,5 $V
python3 experiments_v4/run_grid.py experiments_v4/results_main.jsonl D 150 0,1,2,3,4,5 $V
