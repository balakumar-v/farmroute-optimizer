"""
geocode_mandis.py
-----------------
Agmarknet gives mandi NAMES but no coordinates. This script looks each mandi
up on OpenStreetMap's Nominatim (free, needs internet, max 1 request/sec per
their usage policy) and caches results in data/mandi_coords.csv.

Safeguards against silent wrong answers:
  * a hit is accepted only if it falls inside the state's bounding box;
  * nothing is guessed -- an unresolved mandi stays unresolved and is listed
    at the end so you can fix it by hand in data/mandi_coords_overrides.csv
    (same columns; overrides always win and are never overwritten);
  * every resolved row records the exact query that matched, so you can spot-check
    it on a map.

    python real_data/geocode_mandis.py                 # uses the newest raw CSV
    python real_data/geocode_mandis.py --raw data/raw/xyz.csv
"""
import argparse
import re
import sys
import time

import pandas as pd
import requests

from build_real_markets import embedded_coords
from common import COORDS_CSV, OVERRIDES_CSV, RAW_DIR, STATE_BBOX

NOMINATIM = "https://nominatim.openstreetmap.org/search"
# Replace with your own contact per Nominatim's usage policy.
USER_AGENT = "farmroute-optimizer-course-project/1.0 (student project; contact: set-your-email@example.com)"
COLS = ["state", "district", "market", "lat", "lng", "source", "query"]

# Spelling variants where Agmarknet's name differs from OSM's well-known one.
ALIASES = {"aarah": "Arrah", "munghair": "Munger", "buxur": "Buxar"}


def clean_name(market):
    """'Patna (Musallahpur) APMC' -> ('Patna', 'Musallahpur')."""
    paren = re.search(r"\(([^)]*)\)", market)
    core = re.sub(r"\([^)]*\)", " ", market)
    core = re.sub(r"\bAPMC\b", " ", core, flags=re.I)
    core = re.sub(r"\s+", " ", core).strip(" ,")
    core = ALIASES.get(core.lower(), core)
    return core, (paren.group(1).strip() if paren else None)


def build_queries(market, district, state):
    core, paren = clean_name(market)
    qs = [f"{core}, {district}, {state}, India", f"{core}, {state}, India"]
    if paren:
        qs.insert(0, f"{paren}, {district}, {state}, India")
    # de-dupe, keep order
    return list(dict.fromkeys(qs))


def in_bbox(lat, lng, state):
    box = STATE_BBOX.get(state)
    if box is None:
        return True   # unknown state: no sanity filter available
    return box[0] <= lat <= box[2] and box[1] <= lng <= box[3]


def nominatim(query, session):
    r = session.get(NOMINATIM, params={"q": query, "format": "jsonv2", "limit": 1,
                                       "countrycodes": "in"}, timeout=30)
    r.raise_for_status()
    hits = r.json()
    return (float(hits[0]["lat"]), float(hits[0]["lon"]), hits[0].get("display_name", "")) if hits else None


def resolve(market, district, state, session, sleep=1.1):
    for q in build_queries(market, district, state):
        time.sleep(sleep)
        hit = nominatim(q, session)
        if hit and in_bbox(hit[0], hit[1], state):
            return hit[0], hit[1], q, hit[2]
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", default=None, help="raw CSV from scrape_agmarknet.py (default: newest in data/raw)")
    args = ap.parse_args(argv)

    raw = args.raw
    if raw is None:
        files = sorted(RAW_DIR.glob("agmarknet_*.csv"), key=lambda p: p.stat().st_mtime)
        if not files:
            sys.exit("No raw CSV found. Run scrape_agmarknet.py first.")
        raw = files[-1]
    full = pd.read_csv(raw)
    df = full[["state_name", "district_name", "market_name"]].drop_duplicates()
    print(f"{len(df)} distinct mandis in {raw}")
    from_dataset = set(embedded_coords(full))   # markets whose lat/lng the dataset already provides

    have = pd.read_csv(COORDS_CSV) if COORDS_CSV.exists() else pd.DataFrame(columns=COLS)
    known = set(zip(have.state, have.district, have.market)) | from_dataset
    if OVERRIDES_CSV.exists():
        ov = pd.read_csv(OVERRIDES_CSV)
        known |= set(zip(ov.state, ov.district, ov.market))

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    new_rows, unresolved = [], []
    todo = [r for r in df.itertuples(index=False) if (r.state_name, r.district_name, r.market_name) not in known]
    print(f"{len(todo)} to geocode ({len(df) - len(todo)} already cached/overridden)")
    for i, r in enumerate(todo, 1):
        res = resolve(r.market_name, r.district_name, r.state_name, session)
        if res:
            new_rows.append({"state": r.state_name, "district": r.district_name, "market": r.market_name,
                             "lat": round(res[0], 5), "lng": round(res[1], 5), "source": "nominatim", "query": res[2]})
            print(f"  [{i}/{len(todo)}] {r.market_name} ({r.district_name}): {res[0]:.4f}, {res[1]:.4f}\n"
                  f"        OSM matched: {res[3]}   <- check this names the right district")
        else:
            unresolved.append((r.state_name, r.district_name, r.market_name))
            print(f"  [{i}/{len(todo)}] {r.market_name}: UNRESOLVED")

    if new_rows:
        COORDS_CSV.parent.mkdir(parents=True, exist_ok=True)
        pd.concat([have, pd.DataFrame(new_rows)], ignore_index=True).to_csv(COORDS_CSV, index=False)
    print(f"\nResolved {len(new_rows)}, unresolved {len(unresolved)}. Cache: {COORDS_CSV}")
    if unresolved:
        print("Add these to data/mandi_coords_overrides.csv by hand (columns: " + ",".join(COLS) + "):")
        for s, d, m in unresolved:
            print(f"  {s} | {d} | {m}")


if __name__ == "__main__":
    main()
