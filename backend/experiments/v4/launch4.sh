#!/bin/sh
cd "$(dirname "$0")/../.."
for s in 0 1 2; do
 ORACLE_KMAX=5 ORACLE_OUT=oracle_multi.jsonl python3 experiments/v4/oracle.py 15 $s
 ORACLE_KMAX=5 ORACLE_SINGLE_CROP=1 ORACLE_OUT=oracle_single.jsonl python3 experiments/v4/oracle.py 15 $s
done
