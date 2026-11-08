#!/bin/sh
cd "$(dirname "$0")/../.."
python3 experiments/v4/run_grid.py experiments/v4/results_scale.jsonl D 300 0,1,2 C13+HOLD,BEST+HOLD
python3 experiments/v4/run_grid.py experiments/v4/results_main.jsonl D 150 0,1,2,3,4,5 BEST+HOLD
python3 experiments/v4/run_grid.py experiments/v4/results_main.jsonl G 60 0,1,2,3,4,5 BEST+HOLD
