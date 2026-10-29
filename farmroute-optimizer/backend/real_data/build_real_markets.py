"""
build_real_markets.py
---------------------
raw Agmarknet CSV + mandi coordinates  ->  data/real_markets.json, in the exact
shape POST /markets wants ({lat, lng, price:{crop:Rs/kg}, capacity_kg:{crop:kg}}).

How each number is derived (all from REAL reported rows):
  price[crop]        median over days of the day's mean MODAL price across
                     varieties, converted Rs/quintal -> Rs/kg.
  capacity_kg[crop]  median over days (arrival > 0) of the mandi's reported
                     daily ARRIVAL of that crop, converted to kg. This is what the
                     mandi actually absorbed per day -- a proxy for the model's
                     "kg absorbed this cycle", NOT a hard physical limit.
  capacity_top_share share of days on which the reported arrival equals the single most common value. Above
                     PLACEHOLDER_SHARE (0.7) the "arrival" is almost certainly a default that mandi keeps
                     re-reporting (e.g. exactly 4 t on 136 days), not a measurement: the capacity is still
                     emitted (as reported) but flagged, and it should be treated as an assumption.
A (mandi, crop) pair is kept only if it has >= --min-days days with both a
price and an arrival. Mandis without coordinates are dropped (and listed in
meta.dropped_no_coords), never given made-up coordinates.
"""
import argparse
import json
import sys
from datetime import datetime

import pandas as pd

from common import (COMMODITY_TO_CROP, COORDS_CSV, OVERRIDES_CSV, RAW_DIR, REAL_MARKETS_JSON,
                    STATE_BBOX)


PLACEHOLDER_SHARE = 0.7   # > this share of days at one arrival value => treat the capacity as a reporting default


def price_per_kg_factor(unit):
    """Multiplier turning a price in `unit` into Rs/kg. None if unrecognised."""
    u = str(unit).lower()
    if "quintal" in u or "qtl" in u:
        return 1 / 100.0
    if "tonne" in u or "ton" in u or u.strip().endswith("mt"):
        return 1 / 1000.0
    if "kg" in u or "kilo" in u:
        return 1.0
    return None


def arrival_kg_factor(unit):
    """Multiplier turning an arrival quantity in `unit` into kg. None if unrecognised."""
    u = str(unit).lower()
    if "quintal" in u or "qtl" in u:
        return 100.0
    if "tonne" in u or "ton" in u or u.strip().endswith("mt"):
        return 1000.0
    if "kg" in u or "kilo" in u:
        return 1.0
    return None


def _num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False), errors="coerce")


def _dates(s):
    """Parse a date column that may mix ISO (2026-09-10) and dd-mm-yyyy / dd/mm/yyyy.
    Explicit per-format passes: pandas>=2 infers ONE format from the first value
    and blanks everything that doesn't match, so a single call is not safe."""
    s = s.astype(str).str.strip().str.slice(0, 10)
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        todo = out.isna()
        if not todo.any():
            break
        out[todo] = pd.to_datetime(s[todo], format=fmt, errors="coerce")
    return out


def load_coords():
    frames = []
    if COORDS_CSV.exists():
        frames.append(pd.read_csv(COORDS_CSV))
    if OVERRIDES_CSV.exists():
        frames.append(pd.read_csv(OVERRIDES_CSV))   # later rows win
    if not frames:
        return {}
    c = pd.concat(frames, ignore_index=True).drop_duplicates(["state", "district", "market"], keep="last")
    return {(r.state, r.district, r.market): (float(r.lat), float(r.lng), r.source) for r in c.itertuples()}


def embedded_coords(df):
    """Per-market (lat, lng, 'dataset') from latitude/longitude columns in the raw rows, if present.
    Zero/blank values are ignored and a point outside its state's bounding box is rejected
    (treated as missing, so the market is dropped and listed rather than mis-placed)."""
    if "latitude" not in df.columns or "longitude" not in df.columns:
        return {}
    d = df[["state_name", "district_name", "market_name", "latitude", "longitude"]].copy()
    d["latitude"], d["longitude"] = _num(d["latitude"]), _num(d["longitude"])
    d = d[(d["latitude"].abs() > 0) & (d["longitude"].abs() > 0)].dropna()
    out = {}
    for (st, di, mk), g in d.groupby(["state_name", "district_name", "market_name"]):
        lat, lng = float(g["latitude"].median()), float(g["longitude"].median())
        box = STATE_BBOX.get(st)
        if box and not (box[0] <= lat <= box[2] and box[1] <= lng <= box[3]):
            continue
        out[(st, di, mk)] = (lat, lng, "dataset")
    return out


def shared_coordinate_warnings(markets):
    """Markets in the same district with IDENTICAL coordinates are probably a district
    centroid, not the real mandi location -- flag them so distances are not over-trusted."""
    seen, warns = {}, []
    for m in markets:
        seen.setdefault((m["state"], m["district"], round(m["lat"], 3), round(m["lng"], 3)), []).append(m["name"])
    for (st, di, la, ln), names in seen.items():
        if len(names) > 1:
            warns.append(f"{di}, {st}: {len(names)} markets share one point ({la}, {ln}): {', '.join(names)}")
    return warns


def build(raw_df, coords, min_days=5, capacity_scale=1.0):
    df = raw_df.copy()
    df["crop"] = df["cmdt_name"].astype(str).str.strip().str.lower().map(COMMODITY_TO_CROP)
    df = df[df["crop"].notna()]
    df["date"] = _dates(df["arrival_date"])
    df["modal"] = _num(df["model_price"])
    pf = df["unit_name_price"].map(price_per_kg_factor)
    df["price_kg"] = df["modal"] * pf
    df["arr"] = _num(df["arrival_qty"])
    af = df["unit_name_arrival"].map(arrival_kg_factor)
    df["arr_kg"] = df["arr"] * af
    df = df[df["date"].notna()]

    keys = ["state_name", "district_name", "market_name", "crop"]
    price_day = (df[(df["price_kg"] > 0)].groupby(keys + ["date"])["price_kg"].mean().reset_index())
    # Arrival is reported at commodity level and repeated on every variety row
    # of the same (mandi, crop, day): take it ONCE per day, never sum it.
    arr_day = (df[(df["arr_kg"] > 0)].groupby(keys + ["date"])["arr_kg"].first().reset_index())
    both = price_day.merge(arr_day, on=keys + ["date"], how="inner")

    agg = both.groupby(keys).agg(price=("price_kg", "median"), cap=("arr_kg", "median"),
                                 n_days=("date", "nunique"), last_date=("date", "max"),
                                 top_share=("arr_kg", lambda x: float(x.value_counts(normalize=True).iloc[0]))).reset_index()
    agg = agg[agg["n_days"] >= min_days]

    embedded = embedded_coords(df)   # lat/lng carried in the raw rows (India Data Portal export)
    markets, dropped = {}, set()
    for r in agg.itertuples(index=False):
        mk = (r.state_name, r.district_name, r.market_name)
        if mk in coords:                       # explicit cache / manual override always wins
            lat, lng, src = coords[mk]
        elif mk in embedded:
            lat, lng, src = embedded[mk]
        else:
            dropped.add(mk)
            continue
        m = markets.setdefault(mk, {"name": r.market_name, "district": r.district_name, "state": r.state_name,
                                    "lat": lat, "lng": lng, "geocode_source": src,
                                    "price": {}, "capacity_kg": {}, "n_days": {}, "last_date": {},
                                    "capacity_top_share": {}, "capacity_is_placeholder": {}})
        m["price"][r.crop] = round(float(r.price), 2)
        m["capacity_kg"][r.crop] = round(float(r.cap) * capacity_scale, 1)
        m["n_days"][r.crop] = int(r.n_days)
        m["last_date"][r.crop] = r.last_date.strftime("%Y-%m-%d")
        m["capacity_top_share"][r.crop] = round(float(r.top_share), 2)
        m["capacity_is_placeholder"][r.crop] = bool(r.top_share > PLACEHOLDER_SHARE and r.n_days >= 20)
    return list(markets.values()), sorted(dropped)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", default=None, help="raw CSV (default: newest in data/raw)")
    ap.add_argument("--min-days", type=int, default=5)
    ap.add_argument("--capacity-scale", type=float, default=1.0,
                    help="multiply real daily arrivals by this (e.g. 0.05 to model the share one "
                         "FPO could push without moving the market). Default 1.0 = as reported.")
    args = ap.parse_args(argv)

    raw = args.raw
    if raw is None:
        files = sorted(RAW_DIR.glob("agmarknet_*.csv"), key=lambda p: p.stat().st_mtime)
        if not files:
            sys.exit("No raw CSV found. Run scrape_agmarknet.py first.")
        raw = files[-1]
    coords = load_coords()      # optional: raw rows from the India Data Portal already carry lat/lng
    raw_df = pd.read_csv(raw)
    if not coords and "latitude" not in raw_df.columns:
        sys.exit("No coordinates: the raw CSV has no latitude/longitude and no geocoded cache exists. "
                 "Run geocode_mandis.py first.")
    markets, dropped = build(raw_df, coords, args.min_days, args.capacity_scale)
    warns = shared_coordinate_warnings(markets)
    dts = _dates(raw_df["arrival_date"]).dropna()
    per_crop = {}
    for m in markets:
        for c in m["price"]:
            per_crop[c] = per_crop.get(c, 0) + 1
    out = {"meta": {"source": "Agmarknet 2.0 (agmarknet.gov.in), Directorate of Marketing & Inspection, GoI",
                    "raw_file": str(raw), "generated_at": datetime.now().isoformat(timespec="seconds"),
                    "units": {"price": "Rs/kg (Agmarknet modal price, Rs/quintal / 100)",
                              "capacity_kg": "kg/day (median reported daily arrival x capacity_scale)"},
                    "min_days": args.min_days, "capacity_scale": args.capacity_scale,
                    "placeholder_share_threshold": PLACEHOLDER_SHARE,
                    "data_window": [str(dts.min().date()), str(dts.max().date())] if len(dts) else None,
                    "markets_per_crop": per_crop, "coordinate_warnings": warns,
                    "dropped_no_coords": [" | ".join(d) for d in dropped]},
           "markets": markets}
    REAL_MARKETS_JSON.write_text(json.dumps(out, indent=2))
    print(f"{len(markets)} markets -> {REAL_MARKETS_JSON}")
    print("markets quoting each crop:", per_crop or "none")
    for c in ("tomato", "onion", "potato", "cauliflower", "mango", "spinach"):
        if c not in per_crop:
            print(f"  note: no market has enough data for '{c}' in this window (out of season / not traded).")
    print(f"data window: {out['meta']['data_window']}  (this is the DATE OF THE DATA, not today)")
    for w in warns:
        print("  WARNING coordinates:", w)
    if dropped:
        print(f"{len(dropped)} (mandi) had price+arrival data but NO coordinates -> dropped:")
        for d in dropped:
            print("   ", " | ".join(d))


if __name__ == "__main__":
    main()
