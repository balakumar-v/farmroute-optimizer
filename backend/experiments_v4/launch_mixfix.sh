#!/bin/sh
cd /home/claude/farmroute-optimizer-main/backend
python3 experiments_v4/run_grid.py experiments_v4/results_mixfix.jsonl P:up_aligarh 0 0,1,2 BEST+MIX+TL120
