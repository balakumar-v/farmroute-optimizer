#!/bin/sh
cd "$(dirname "$0")/../.."
python3 experiments/v4/run_grid.py experiments/v4/results_mixfix.jsonl P:up_aligarh 0 0,1,2 BEST+MIX+TL120
