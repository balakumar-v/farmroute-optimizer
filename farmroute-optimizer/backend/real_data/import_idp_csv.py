"""
import_idp_csv.py
-----------------
Turns the India Data Portal "APMC arrivals and prices (Agmarknet)" CSV
(https://indiadataportal.com -> Agriculture Marketing; daily, market-centre
level, with latitude/longitude, arrivals in tonnes and modal price in INR/quintal)
into the raw CSV that build_real_markets.py reads.

WHY: Agmarknet's own report API now demands a captcha (TOKEN_OR_CAPTCHA_REQUIRED),
so it can't be scraped. This dataset is the portal's bulk, human-downloadable
copy of the same Agmarknet data. It is updated daily but lags
today (user-observed latest date: 2026-05-31) -- so these are dated, not live, prices. Pick a window with
--from/--to; the script tells you what dates the file actually covers.

HOW TO GET THE FILE (once, manually): indiadataportal.com -> dataset
"Agriculture Marketing" -> resource "APMC arrivals and prices (Agmarknet)"
-> sign in -> "Download Data" -> state the purpose -> "Download CSV File".
It is large (all India, 300+ commodities); this script streams it in chunks.

    python real_data/import_idp_csv.py path/to/file.csv --state Bihar --from 2024-09-01 --to 2024-09-30
"""
import argparse
import re
import sys
from datetime import date

import pandas as pd

from build_real_markets import _dates
from common import COMMODITY_TO_CROP, RAW_DIR

# canonical name -> accepted header spellings (lower-cased, stripped)
ALIASES = {
    "date":         ["report_date", "arrival_date", "date"],
    "state":        ["state_name", "state"],
    "district":     ["district_name", "district"],
    "market":       ["market_center_name", "market_center", "market_name", "market"],
    "lat":          ["latitude", "lat"],
    "lng":          ["longitude", "lng", "lon"],
    "commodity":    ["commodity_name", "commodity", "cmdt_name"],
    "variety":      ["variety", "variety_name"],
    "arrivals":     ["arrival_quantity", "arrivals_tonnes", "arrival_tonnes", "arrivals_in_tonnes", "arrival_qty", "arrivals"],
    "arrivals_unit": ["arrival_units", "arrivals_unit", "unit_name_arrival"],
    "modal":        ["modal_price", "model_price"],
    "price_unit":   ["price_unit", "unit_name_price"],
}
REQUIRED = ["date", "state", "district", "market", "commodity", "modal"]


def _header_ids(header):
    """The portal exports headers like 'Market Center Name (market_center_name)'.
    Return every spelling to match on: the full header and the id inside the final parentheses."""
    h = header.strip().lower()
    ids = [h]
    m = re.search(r"\(([^()]*)\)\s*$", h)
    if m:
        ids.insert(0, m.group(1).strip())
    return ids


def resolve_columns(columns):
    """Map canonical names -> actual header names. Raises SystemExit listing the headers if a required one is missing."""
    norm = {}
    for c in columns:
        for key in _header_ids(c):
            norm.setdefault(key, c)
    found = {}
    for canon, options in ALIASES.items():
        for o in options:
            if o in norm:
                found[canon] = norm[o]
                break
    missing = [c for c in REQUIRED if c not in found]
    if missing:
        sys.exit(f"CSV is missing expected columns {missing}.\nHeaders found: {list(columns)}\n"
                 "Paste these headers to me and I'll extend ALIASES.")
    return found


def convert_chunk(chunk, cols, states, frm, to):
    """Filter one chunk and return (rows in builder's schema, seen_dates_for_state_crops)."""
    st = chunk[cols["state"]].astype(str).str.strip().str.lower()
    cm = chunk[cols["commodity"]].astype(str).str.strip().str.lower()
    keep = st.isin(states) & cm.isin(COMMODITY_TO_CROP)
    sub = chunk[keep]
    if sub.empty:
        return pd.DataFrame(), pd.Series(dtype="datetime64[ns]")
    dates = _dates(sub[cols["date"]])
    seen = dates.dropna()
    inwin = dates.between(pd.Timestamp(frm), pd.Timestamp(to))
    sub, dates = sub[inwin], dates[inwin]
    if sub.empty:
        return pd.DataFrame(), seen

    def col(name, default=""):
        return sub[cols[name]] if name in cols else pd.Series(default, index=sub.index)

    out = pd.DataFrame({
        "arrival_date": dates.dt.strftime("%Y-%m-%d"),
        "state_name": col("state").astype(str).str.strip(),
        "district_name": col("district").astype(str).str.strip(),
        "market_name": col("market").astype(str).str.strip(),
        "cmdt_name": col("commodity").astype(str).str.strip(),
        "variety_name": col("variety"),
        "model_price": col("modal"),
        # Dataset dictionary: prices INR/quintal, arrivals tonnes. If the unit columns are
        # blank we fall back to those documented units; unrecognised units are dropped later.
        "unit_name_price": col("price_unit").replace("", pd.NA).fillna("INR / quintal"),
        "arrival_qty": col("arrivals"),
        "unit_name_arrival": col("arrivals_unit").replace("", pd.NA).fillna("Tonnes"),
        "latitude": col("lat") if "lat" in cols else pd.NA,
        "longitude": col("lng") if "lng" in cols else pd.NA,
    })
    out.insert(0, "crop", out["cmdt_name"].str.lower().map(COMMODITY_TO_CROP))
    return out, seen


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", help="path to the downloaded India Data Portal CSV (.csv / .csv.gz / .zip)")
    ap.add_argument("--state", nargs="+", default=["Bihar"])
    ap.add_argument("--from", dest="frm", required=True, help="window start YYYY-MM-DD")
    ap.add_argument("--to", required=True, help="window end YYYY-MM-DD")
    ap.add_argument("--chunk", type=int, default=500_000, help="rows per chunk (memory control)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    frm, to = date.fromisoformat(args.frm), date.fromisoformat(args.to)
    states = {s.strip().lower() for s in args.state}
    frames, seen_min, seen_max, total = [], None, None, 0
    cols = None
    for chunk in pd.read_csv(args.csv, chunksize=args.chunk, dtype=str, keep_default_na=False, low_memory=False):
        if cols is None:
            cols = resolve_columns(chunk.columns)
            print("column mapping:", {k: v for k, v in cols.items()})
        total += len(chunk)
        out, seen = convert_chunk(chunk, cols, states, frm, to)
        if len(seen):
            lo, hi = seen.min(), seen.max()
            seen_min = lo if seen_min is None else min(seen_min, lo)
            seen_max = hi if seen_max is None else max(seen_max, hi)
        if len(out):
            frames.append(out)
        print(f"  scanned {total:,} rows, kept {sum(len(f) for f in frames):,}", end="\r", flush=True)
    print()

    if seen_min is not None:
        print(f"file covers {seen_min.date()} .. {seen_max.date()} for {sorted(args.state)} x project crops")
    if not frames:
        sys.exit("No rows in that window. Choose --from/--to inside the covered dates above "
                 "(or check --state spelling).")
    res = pd.concat(frames, ignore_index=True)
    print("price units seen:", sorted(res["unit_name_price"].unique())[:6])
    print("arrival units seen:", sorted(res["unit_name_arrival"].unique())[:6])
    print("rows per crop:", res["crop"].value_counts().to_dict())
    print("markets:", res[["state_name", "district_name", "market_name"]].drop_duplicates().shape[0])

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = args.out or RAW_DIR / f"agmarknet_idp_{'-'.join(s.replace(' ', '') for s in args.state)}_{frm}_{to}.csv"
    res.to_csv(path, index=False)
    print(f"Wrote {len(res):,} rows -> {path}")


if __name__ == "__main__":
    main()
