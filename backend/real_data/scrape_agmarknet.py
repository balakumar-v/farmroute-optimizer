"""
scrape_agmarknet.py
-------------------
Downloads daily mandi price + arrival rows from the official Agmarknet 2.0
API (api.agmarknet.gov.in) for the project's 6 crops, via the `agmarknet`
PyPI client, and writes ONE raw CSV.

STATUS (verified against the live API, Oct 2026): the report endpoint now requires a captcha
(HTTP 400, code TOKEN_OR_CAPTCHA_REQUIRED), so this script cannot download data and does NOT
try to get around it. Use import_idp_csv.py with the India Data Portal bulk CSV instead
(see README). This file is kept for the --probe/--diagnose tooling in case access reopens.

Run on a machine with normal internet access:

    python real_data/scrape_agmarknet.py --probe        # 1 tiny request: check schema/units
    python real_data/scrape_agmarknet.py --diagnose     # if a request fails: tries variants, prints server replies
    python real_data/scrape_agmarknet.py --state Bihar --days 30

Design notes
  * The SDK ships a SNAPSHOT of Agmarknet's filter tables (market/district IDs
    and the allowed date range) and uses it by default. We pass use_cache=False so
    IDs and date limits come from the LIVE /filters endpoint instead.
  * The requested window is clamped to the live "both" date range; the default
    end date is yesterday (today's feed is incomplete) or the server's latest
    allowed date, whichever is earlier.
  * On any API failure the HTTP status and the server's reply body are printed.
  * Agmarknet 2.0 went live 2025-11-07; windows must be <= 1 year.
"""
import argparse
import sys
from datetime import date, timedelta

import pandas as pd

from common import CROPS, RAW_DIR

EXPECTED_COLS = {"arrival_date", "state_name", "district_name", "market_name",
                 "cmdt_name", "model_price", "unit_name_price",
                 "arrival_qty", "unit_name_arrival"}
FILTERS_PATH = "/daily-price-arrival/filters"


def describe_error(exc):
    """One readable block: message + HTTP status + (truncated) server reply."""
    parts = [str(exc)]
    status = getattr(exc, "status_code", None)
    body = getattr(exc, "response_text", None)
    if status is not None:
        parts.append(f"HTTP status: {status}")
    if body:
        parts.append(f"server reply: {body[:600]}")
    return "\n    ".join(parts)


def captcha_required(exc):
    return "TOKEN_OR_CAPTCHA_REQUIRED" in (getattr(exc, "response_text", "") or "")


def live_both_range(api):
    """(from, to) dates the server currently allows for combined price+arrival
    reports, or None if the filters call fails / has an unexpected shape."""
    from agmarknet import AgmarknetError
    try:
        payload = api._session.get_json(FILTERS_PATH)
        both = payload["data"]["range_data"][0]["both"]
        return date.fromisoformat(both["from_date"]), date.fromisoformat(both["to_date"])
    except (AgmarknetError, KeyError, IndexError, TypeError, ValueError) as exc:
        print(f"WARNING: could not read live date range ({exc.__class__.__name__}: {exc}); "
              "using the requested window as-is.", file=sys.stderr)
        return None


def clamp_window(frm, to, live):
    """Clamp [frm, to] into the server's allowed range, keeping length if possible."""
    if live is None:
        return frm, to
    lo, hi = live
    length = (to - frm).days
    if to > hi:
        to = hi
        frm = max(to - timedelta(days=length), lo)
    if frm < lo:
        frm = lo
    return frm, to


def fetch_crop(api, crop, states, frm, to, data_type="both", district=None):
    cmdt_id, group_id = CROPS[crop]
    kwargs = dict(from_date=frm, to_date=to, data_type=data_type,
                  commodity=cmdt_id, group=group_id, state=states, limit=1000)
    if district is not None:
        kwargs["district"] = district
    df = api.report(**kwargs)
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df.insert(0, "crop", crop)
    return df


def run_diagnose(api, states, frm, to, live):
    """Try a ladder of variants of the failing request and print each outcome."""
    from agmarknet import AgmarknetError
    print(f"live 'both' range from server: {live}")
    tests = [
        ("onion, both, clamped window",        dict(frm=frm, to=to, data_type="both")),
        ("onion, price-only, same window",     dict(frm=frm, to=to, data_type="price")),
        ("onion, both, one district (Patna)",  dict(frm=frm, to=to, data_type="both", district="Patna")),
        ("onion, both, 7 days earlier",        dict(frm=frm - timedelta(days=7), to=to - timedelta(days=7), data_type="both")),
    ]
    for label, kw in tests:
        try:
            df = fetch_crop(api, "onion", states, kw["frm"], kw["to"], kw["data_type"], kw.get("district"))
            print(f"[OK  ] {label}: {len(df)} rows")
        except AgmarknetError as exc:
            print(f"[FAIL] {label}:\n    {describe_error(exc)}")
        except Exception as exc:   # lookup/validation problems from the SDK
            print(f"[FAIL] {label}: {exc.__class__.__name__}: {exc}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", nargs="+", default=["Bihar"])
    ap.add_argument("--crops", nargs="+", default=list(CROPS), choices=list(CROPS))
    ap.add_argument("--days", type=int, default=30, help="window length in days (default 30)")
    ap.add_argument("--to", default=None, help="window end YYYY-MM-DD (default: yesterday)")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
    ap.add_argument("--probe", action="store_true",
                    help="fetch ONE crop for 3 days, print columns/units/sample rows, write nothing")
    ap.add_argument("--diagnose", action="store_true",
                    help="try several request variants and print the server's reply to each")
    ap.add_argument("--out", default=None, help="output CSV path (default data/raw/agmarknet_<state>_<from>_<to>.csv)")
    args = ap.parse_args(argv)

    from agmarknet import Agmarknet, AgmarknetError   # imported late so --help works without it
    to = date.fromisoformat(args.to) if args.to else date.today() - timedelta(days=1)
    days = 3 if (args.probe or args.diagnose) else args.days
    frm = to - timedelta(days=days - 1)
    if (to - frm).days > 365:
        sys.exit("Window must be <= 1 year (Agmarknet API limit).")
    crops = ["onion"] if args.probe else args.crops

    # use_cache=False -> live market/district IDs instead of the SDK's bundled snapshot.
    api = Agmarknet(request_delay=args.delay, use_cache=False)
    live = live_both_range(api)
    new_frm, new_to = clamp_window(frm, to, live)
    if (new_frm, new_to) != (frm, to):
        print(f"Window clamped to server's allowed range {live}: {frm}..{to} -> {new_frm}..{new_to}")
    frm, to = new_frm, new_to

    if args.diagnose:
        run_diagnose(api, args.state, frm, to, live)
        return

    frames, failed = [], []
    for crop in crops:
        print(f"[{crop}] {args.state} {frm} -> {to} ...", flush=True)
        try:
            df = fetch_crop(api, crop, args.state, frm, to)
        except AgmarknetError as exc:
            if captcha_required(exc):
                sys.exit("Agmarknet's report API now requires a captcha, so automated download is blocked "
                         "(and is deliberately not bypassed here).\nUse the bulk CSV route instead: "
                         "python real_data/import_idp_csv.py <downloaded.csv> --state Bihar --from YYYY-MM-DD --to YYYY-MM-DD")
            print(f"  FAILED:\n    {describe_error(exc)}", file=sys.stderr)
            failed.append(crop)
            continue
        print(f"  {len(df)} rows", flush=True)
        if len(df):
            frames.append(df)

    if not frames:
        sys.exit("No rows downloaded. Run with --diagnose and share the output.")
    out = pd.concat(frames, ignore_index=True)

    missing = EXPECTED_COLS - set(out.columns)
    if missing:
        sys.exit(f"Schema drift: missing columns {sorted(missing)}. Got: {list(out.columns)}")

    if args.probe:
        print("\ncolumns:", list(out.columns))
        print("price units:", out["unit_name_price"].dropna().unique().tolist())
        print("arrival units:", out["unit_name_arrival"].dropna().unique().tolist())
        print(out.head(5).to_string())
        return

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = args.out or RAW_DIR / f"agmarknet_{'-'.join(s.replace(' ', '') for s in args.state)}_{frm}_{to}.csv"
    out.to_csv(path, index=False)
    print(f"\nWrote {len(out)} rows -> {path}")
    if failed:
        print(f"WARNING: no data for crops: {failed}", file=sys.stderr)


if __name__ == "__main__":
    main()
