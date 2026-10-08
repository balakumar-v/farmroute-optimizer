"""
calibrate_circuity.py -- fit the road-circuity factor (road km / straight-line km) from real road distances.

INPUT  CSV with columns lat1,lng1,lat2,lng2,road_km  (>= ~100-200 farmer->mandi / farmer->farmer pairs from the
       region you plan in; road_km from OSRM /route or /table, Google Distance Matrix, or a few odometer logs).
       Quick OSRM fill-in (self-hosted):  GET /route/v1/driving/{lng1},{lat1};{lng2},{lat2}?overview=false
       -> routes[0].distance (metres).
OUTPUT prints the fit and (with --out) writes JSON {"road_circuity": k, "n": .., "p10": .., "p90": ..}.

The planner then uses it via  logistics_lib_v2.set_road_circuity(k)  or  FARMROUTE_ROAD_CIRCUITY=k.
Fit = median of per-pair ratios (robust to a few detours); ratios < 1 (bad geocodes) and pairs under 2 km
(ratio dominated by snapping error) are dropped. The p10/p90 spread says how risky one global factor is:
a wide spread means use a real matrix (OSRM) instead of a factor.

    python calibrate_circuity.py pairs.csv --out circuity.json
"""
import argparse
import csv
import json
import statistics

from logistics_lib_v2 import crow_km


def fit(rows, min_km=2.0):
    ratios = []
    for r in rows:
        d = crow_km(float(r["lat1"]), float(r["lng1"]), float(r["lat2"]), float(r["lng2"]))
        road = float(r["road_km"])
        if d >= min_km and road >= d:
            ratios.append(road / d)
    if len(ratios) < 20:
        raise SystemExit(f"need >= 20 usable pairs, got {len(ratios)}")
    ratios.sort()
    q = lambda p: ratios[min(len(ratios) - 1, int(p * len(ratios)))]          # noqa: E731
    return {"road_circuity": round(statistics.median(ratios), 3), "n": len(ratios),
            "p10": round(q(0.10), 3), "p90": round(q(0.90), 3)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--out")
    a = ap.parse_args()
    with open(a.csv, newline="") as fh:
        res = fit(list(csv.DictReader(fh)))
    print(res)
    if res["p90"] - res["p10"] > 0.5:
        print("WARNING: wide spread -> one global factor is a poor model here; prefer an OSRM matrix.")
    if a.out:
        json.dump(res, open(a.out, "w"), indent=2)
