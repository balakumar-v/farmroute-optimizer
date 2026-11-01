#!/bin/sh
cd /home/claude/farmroute-optimizer-main/backend
python3 experiments_v4/run_grid.py experiments_v4/results_scale.jsonl D 300 0,1,2 C13,C13+CAP90,C13+CAP80
