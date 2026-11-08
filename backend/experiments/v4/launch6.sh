#!/bin/sh
cd "$(dirname "$0")/../.."
python3 experiments/v4/run_grid.py experiments/v4/results_scale.jsonl D 300 0,1,2 C13,C13+CAP90,C13+CAP80
