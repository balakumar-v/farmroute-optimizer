"""
build_regional_presets.py
--------------------------
One India Data Portal "APMC Arrivals and Prices" CSV for a whole state  ->  one frontend preset (a JS block for
frontend/app.js -> SCENARIOS) plus a JSON/markdown record of exactly what was cleaned, imputed and assumed.

    python real_data/build_regional_presets.py --preset karnataka_bengaluru --csv path/to/state.csv
    python real_data/build_regional_presets.py --list

WHAT IS REAL (from the CSV): mandi locations (the portal's own latitude/longitude), prices and daily arrivals.
WHAT IS SYNTHETIC / ASSUMED: the farmers (no public farmer-level data exists), the fleet, and the counts below.

CLEANING (counts are printed and written to the report, nothing is dropped silently)
  row level   modal price <= 0 or missing; modal outside [min, max]; min > max; price unit that is not Rs/quintal;
              arrival unit that is not tonnes/quintal/kg (e.g. "Nos", "Bundle") -> arrival unusable.
  day level   per (mandi, crop): modal price outside [1/3x, 3x] of the series median, or an arrival above 20x the
              series median (typos such as 60,500 t) -> row dropped.
  coordinates the portal's coordinates must fall inside the state's bounding box (common.STATE_BBOX); mandis in a
              district whose coordinates sit > 120 km from the district's other mandis are dropped as suspect;
              identical coordinates for several mandis are flagged. Mandis without coordinates are dropped and
              listed, never given invented coordinates.
  series      a (mandi, crop) needs >= MIN_DAYS days with both price and arrival inside the window, and (after
              the capacity imputation below) must absorb >= MIN_USEFUL_ABSORPTION_KG (1 t) per day.
  plausible   a series is dropped when its median price is outside Rs 2-150/kg (mango 5-400) or its median arrival exceeds a
              per-crop ceiling (e.g. 150 t/day for spinach). Leafy crops are often traded by the bundle but
              labelled "Rs/quintal" and "tonnes", which yields prices like Rs 0.1/kg and 5,000 "tonnes" of spinach.

CAPACITY ("how many kg a mandi absorbs per day") is the median reported daily arrival. Many mandis re-report one
default value every day (the share of days at the single most common value is stored; > 70% over >= 20 days is
flagged). For those the capacity is RAISED to the lower quartile of the non-flagged mandis for the same crop in the
same state and window if the reported number is lower ("imputed_peer_q1"); it is never lowered. The lower quartile,
not the median, because mandi sizes are heavy-tailed (a few giants) and a small mandi should not be inflated to
giant scale. This is an ASSUMPTION about a typical small-to-mid mandi, recorded per series in the output.

COUNTS (all ASSUMPTIONS, written into the preset blurb):
  mandis     the 8 nearest to the farmer cluster centre (extended to 12 until at least 3 crops have 2+ buyers).
  farmers    N_TARGET (60) pickups: a realistic collection round for one FPO. Each crop gets a share of them
             proportional to sqrt(its absorption) (so one dominant crop does not erase the others), but never more
             produce than CROP_ABSORPTION_SHARE (30%) of what the chosen mandis already absorb of that crop per day
             (a farmer group that out-produces the local market is a different problem), and a crop with fewer
             than 3 farmers is left out. The final count can therefore be below 60.
  crop mix   crops with >= 2 buyers among the chosen mandis; each village leans toward one crop (60%).
  layout     farmers live in villages (n/5 villages, within CLUSTER_RADIUS_KM of the centre), not uniformly spread.
  lots       150-600 kg, ready 0-4 h, deadline 6-14 h later (the project generator's own distributions).
  fleet      total capacity = FLEET_RATIO x the day's produce, refrigerated and plain capacity sized separately
             (50% 5 t, 35% 2 t, 15% 1 t vehicles), at least one vehicle per class that is needed.
"""
import argparse
import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # backend/
sys.path.insert(0, str(Path(__file__).resolve().parent))          # real_data/
import build_real_markets as brm                                    # noqa: E402
import import_idp_csv as imp                                        # noqa: E402
from common import DATA, STATE_BBOX                                 # noqa: E402
from logistics_lib_v2 import CROPS, haversine                       # noqa: E402

MIN_DAYS = 15
PRICE_BAND = 3.0                 # keep modal prices within [median / 3, median * 3] of their series
ARRIVAL_SPIKE = 20.0             # drop arrivals above 20x the series median
DISTRICT_OUTLIER_KM = 120.0
N_TARGET = 60
CROP_ABSORPTION_SHARE = 0.30
MIN_FARMERS_PER_CROP = 3
MEAN_LOT_KG = 375.0              # mean of the 150-600 kg lot distribution
MIN_USEFUL_ABSORPTION_KG = 1000.0   # a mandi taking < 1 t/day of a crop (under 3 lots) is not a market for a pickup round
PLAUSIBLE_PRICE_KG = (2.0, 150.0)
PLAUSIBLE_PRICE_KG_BY_CROP = {"mango": (5.0, 400.0)}      # premium mango (e.g. Alphonso) really does trade near Rs 250-300/kg
PLAUSIBLE_MAX_ARRIVAL_KG = {"spinach": 150_000, "cauliflower": 500_000, "mango": 1_000_000, "tomato": 2_500_000,
                            "onion": 6_000_000, "potato": 3_000_000}
CLUSTER_RADIUS_KM = 18.0
VILLAGE_JITTER_KM = 1.2
VILLAGE_CROP_LEAN = 0.6
FLEET_RATIO = 1.5
REGIONAL_DIR = DATA / "regional"

PRESETS = {
    "karnataka_bengaluru": dict(
        state="Karnataka", frm="2026-02-01", to="2026-04-30", seed=11,
        label="Karnataka mandis around Bengaluru, Feb-Apr 2026: tomato, onion, potato, cauliflower, mango",
        hub="Bengaluru Apmc"),
    "up_aligarh": dict(
        state="Uttar Pradesh", frm="2025-11-01", to="2026-01-31", seed=12,
        label="Uttar Pradesh mandis around Aligarh, Nov 2025 - Jan 2026: potato, onion, tomato, cauliflower, spinach",
        hub="Aligarh Apmc"),
    "maharashtra_junnar": dict(
        state="Maharashtra", frm="2026-02-01", to="2026-04-30", seed=13,
        label="Maharashtra mandis around Junnar (Pune), Feb-Apr 2026: onion, tomato, potato, cauliflower, spinach",
        hub="Junnar(Otur) Apmc"),
    "mp_indore": dict(
        state="Madhya Pradesh", frm="2026-02-01", to="2026-04-30", seed=14,
        label="Madhya Pradesh mandis around Indore, Feb-Apr 2026: onion, potato, tomato, cauliflower",
        hub="Indore Apmc"),
    "tamil_nadu_vellore": dict(
        state="Tamil Nadu", frm="2026-01-04", to="2026-02-08", seed=15, min_days=5, min_absorption_kg=300, max_mandi_km=150,
        label="Tamil Nadu mandis around Vellore, Jan-Feb 2026: tomato, onion, potato",
        hub="Vellore Apmc",
        coords=[("Vellore", "Thirupathur Apmc", 12.4955, 78.5730, "approximate town centre, not from the portal"),
                ("Vellore", "Gudiyatham(Uzhavar Sandhai )", 12.9540, 78.8710, "approximate town centre, not from the portal")],
        notes=["Two files merged: Vellore district has daily data (~36 days per mandi in this window); other districts have only 5 sampled days (all Sundays)",
               "Thirupathur and Gudiyatham coordinates are approximate town centres added by hand (a few km uncertain)",
               "Most yards are Uzhavar Sandhai (farmers' markets), so prices look retail-like; only Vellore, Thirupathur, Tindivanam and Ulundurpettai are APMC wholesale yards",
               "Tamil Nadu yards are small (0.3-9 t/day per crop), so the farmer count is capped well below the other presets; thresholds lowered to 5 days and 0.3 t/day"]),
}


# ----------------------------------------------------------------------------------------------------------------
# 1. read + clean
# ----------------------------------------------------------------------------------------------------------------
def _col(columns, ident):
    return next((c for c in columns if c.strip().lower().endswith(f"({ident})")), None)


def load_clean(csv_path, state, frm, to, chunk_rows=300_000):
    """Stream the raw CSV, keep the state's supported crops inside the window, apply the row-level cleaning.
    Returns (frame in the builder's schema, report dict)."""
    from datetime import date
    frm_d, to_d = date.fromisoformat(frm), date.fromisoformat(to)
    states = {state.strip().lower()}
    frames, cols, mincol, maxcol = [], None, None, None
    rep = Counter()
    for chunk in pd.read_csv(csv_path, chunksize=chunk_rows, dtype=str, keep_default_na=False, low_memory=False):
        if cols is None:
            cols = imp.resolve_columns(chunk.columns)
            mincol, maxcol = _col(chunk.columns, "min_price"), _col(chunk.columns, "max_price")
        rep["raw_rows_total"] += len(chunk)
        out, _seen = imp.convert_chunk(chunk, cols, states, frm_d, to_d)
        if out.empty:
            continue
        rep["rows_in_state_window_supported_crops"] += len(out)
        out["min_price"] = pd.to_numeric(chunk.loc[out.index, mincol], errors="coerce") if mincol else float("nan")
        out["max_price"] = pd.to_numeric(chunk.loc[out.index, maxcol], errors="coerce") if maxcol else float("nan")
        frames.append(out)
    if not frames:
        sys.exit(f"No rows for {state} between {frm} and {to} with a supported crop.")
    df = pd.concat(frames)
    df["modal"] = brm._num(df["model_price"])
    pf = df["unit_name_price"].map(brm.price_per_kg_factor)
    af = df["unit_name_arrival"].map(brm.arrival_kg_factor)

    def drop(mask, reason):
        nonlocal df, pf, af
        rep[reason] += int(mask.sum())
        keep = ~mask
        df, pf, af = df[keep], pf[keep], af[keep]

    drop(pf.isna(), "dropped_price_unit_not_rs_per_quintal_or_kg")
    drop(~(df["modal"] > 0), "dropped_modal_price_missing_or_nonpositive")
    both = df["min_price"].notna() & df["max_price"].notna() & (df["min_price"] > 0) & (df["max_price"] > 0)
    drop(both & (df["min_price"] > df["max_price"]), "dropped_min_price_above_max_price")
    drop(both & ((df["modal"] < df["min_price"] * 0.999) | (df["modal"] > df["max_price"] * 1.001)),
         "dropped_modal_price_outside_min_max")
    rep["arrival_unit_unusable_rows (price kept, arrival ignored: Nos/Bundle...)"] = int(af.isna().sum())
    df["price_kg"] = df["modal"] * pf
    df["arr_kg"] = brm._num(df["arrival_qty"]) * af

    key = ["state_name", "district_name", "market_name", "crop"]
    med_p = df.groupby(key)["price_kg"].transform("median")
    drop((df["price_kg"] > med_p * PRICE_BAND) | (df["price_kg"] < med_p / PRICE_BAND), "dropped_price_outlier_vs_series_median")
    pos = df["arr_kg"].where(df["arr_kg"] > 0)
    med_a = pos.groupby([df[k] for k in key]).transform("median")
    spike = df["arr_kg"] > med_a * ARRIVAL_SPIKE
    ex = df.loc[spike, ["market_name", "crop", "arrival_date", "arr_kg"]].head(5)
    rep["arrival_spike_examples"] = [f"{r.market_name} {r.crop} {r.arrival_date}: {r.arr_kg / 1000:,.0f} t" for r in ex.itertuples()]
    drop(spike, "dropped_arrival_spike_over_20x_series_median")
    rep["rows_after_cleaning"] = len(df)
    return df.drop(columns=["modal", "price_kg", "arr_kg", "min_price", "max_price"]), dict(rep)


# ----------------------------------------------------------------------------------------------------------------
# 2. markets: build, validate coordinates, impute placeholder capacities
# ----------------------------------------------------------------------------------------------------------------
def drop_implausible_series(markets):
    """Remove (mandi, crop) series with implausible implied prices/arrivals (unit confusion). Returns the dropped list."""
    dropped = []
    for m in markets:
        for c in list(m["price"]):
            p, cap = m["price"][c], m["capacity_kg"][c]
            why = None
            lo, hi = PLAUSIBLE_PRICE_KG_BY_CROP.get(c, PLAUSIBLE_PRICE_KG)
            if not (lo <= p <= hi):
                why = f"price Rs {p:g}/kg outside {lo:g}-{hi:g}"
            elif cap > PLAUSIBLE_MAX_ARRIVAL_KG[c]:
                why = f"median arrival {cap / 1000:,.0f} t/day above the {PLAUSIBLE_MAX_ARRIVAL_KG[c] / 1000:,.0f} t ceiling"
            if why:
                dropped.append(f"{m['name']} {c}: {why}")
                for k in ("price", "capacity_kg", "n_days", "last_date", "capacity_top_share", "capacity_is_placeholder"):
                    m[k].pop(c, None)
    return dropped, [m for m in markets if m["price"]]


def drop_tiny_series(markets, min_kg=MIN_USEFUL_ABSORPTION_KG):
    """After imputation: remove (mandi, crop) series that absorb less than MIN_USEFUL_ABSORPTION_KG per day. The
    farmers would all converge on the nearest mandi and most of the produce could not be sold there, which says more
    about the choice of a trivially small yard than about the algorithms."""
    dropped = []
    for m in markets:
        for c in list(m["price"]):
            if m["capacity_kg"][c] < min_kg:
                dropped.append(f"{m['name']} {c}: {m['capacity_kg'][c] / 1000:.2f} t/day")
                for k in ("price", "capacity_kg", "n_days", "last_date", "capacity_top_share", "capacity_is_placeholder",
                          "capacity_source", "capacity_reported_kg"):
                    m[k].pop(c, None)
    return dropped, [m for m in markets if m["price"]]


def coordinate_outliers(markets):
    """Mandis whose point is > DISTRICT_OUTLIER_KM from the median point of the district's other mandis."""
    by = defaultdict(list)
    for m in markets:
        by[(m["state"], m["district"])].append(m)
    bad = []
    for ms in by.values():
        if len(ms) < 3:
            continue
        for m in ms:
            others = [o for o in ms if o is not m]
            clat, clng = median(o["lat"] for o in others), median(o["lng"] for o in others)
            if haversine(m["lat"], m["lng"], clat, clng) > DISTRICT_OUTLIER_KM:
                bad.append(m["name"])
    return bad


def _q1(values):
    v = sorted(values)
    k = (len(v) - 1) * 0.25
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def impute_capacities(markets):
    """Raise placeholder capacities to the lower quartile of the state's non-placeholder mandis for the crop.
    Never lowers a value."""
    peers = defaultdict(list)
    for m in markets:
        for c, v in m["capacity_kg"].items():
            if not m["capacity_is_placeholder"][c]:
                peers[c].append(v)
    peer_med = {c: _q1(v) for c, v in peers.items() if len(v) >= 5}
    n_flag = n_imp = 0
    for m in markets:
        m["capacity_source"], m["capacity_reported_kg"] = {}, {}
        for c in list(m["capacity_kg"]):
            m["capacity_reported_kg"][c] = m["capacity_kg"][c]
            m["capacity_source"][c] = "reported"
            if m["capacity_is_placeholder"][c]:
                n_flag += 1
                if c in peer_med and m["capacity_kg"][c] < peer_med[c]:
                    m["capacity_kg"][c] = round(peer_med[c], 1)
                    m["capacity_source"][c] = "imputed_peer_q1"
                    n_imp += 1
    return {"placeholder_series": n_flag, "capacity_raised_to_peer_q1": n_imp,
            "peer_q1_kg": {c: round(v) for c, v in peer_med.items()}}


# ----------------------------------------------------------------------------------------------------------------
# 3. region: hub -> farmer cluster centre -> nearest mandis -> crop mix
# ----------------------------------------------------------------------------------------------------------------
def choose_region(markets, hub_name, max_km=None):
    hub = next((m for m in markets if m["name"] == hub_name), None)
    if hub is None:
        sys.exit(f"Hub mandi {hub_name!r} is not among the usable markets: "
                 f"{sorted(m['name'] for m in markets)[:20]} ...")
    near = [m for m in markets if haversine(hub["lat"], hub["lng"], m["lat"], m["lng"]) <= 60]
    centre = (median(m["lat"] for m in near), median(m["lng"] for m in near))
    ranked = sorted(markets, key=lambda m: haversine(centre[0], centre[1], m["lat"], m["lng"]))
    if max_km is not None:   # optional per-preset cap so a sparse-coordinate state cannot pull in mandis 500+ km away
        ranked = [m for m in ranked if haversine(centre[0], centre[1], m["lat"], m["lng"]) <= max_km]
    for k in (8, 9, 10, 11, 12):
        chosen = ranked[:k]
        buyers = Counter(c for m in chosen for c in m["price"])
        crops = [c for c, n in buyers.items() if n >= 2]
        if len(crops) >= 3:
            break
    return hub, centre, chosen, sorted(crops)


def crop_weights(chosen, crops):
    vol = {c: sum(m["capacity_kg"].get(c, 0.0) for m in chosen) for c in crops}
    return {c: math.sqrt(v) for c, v in vol.items()}, vol


# ----------------------------------------------------------------------------------------------------------------
# 4. synthetic farmers + fleet with realistic counts
# ----------------------------------------------------------------------------------------------------------------
def _km_to_deg(lat, km_n, km_e):
    return km_n / 111.2, km_e / (111.2 * math.cos(math.radians(lat)))


def allocate_counts(chosen, crops):
    """Farmers per crop: sqrt-volume shares of N_TARGET, capped by the crop's local absorption, dropping tiny crops."""
    weights, vol = crop_weights(chosen, crops)
    tot = sum(weights.values())
    n_c = {}
    for c in crops:
        want = round(N_TARGET * weights[c] / tot)
        cap = int(CROP_ABSORPTION_SHARE * vol[c] / MEAN_LOT_KG)
        n_c[c] = min(want, cap)
    kept = {c: n for c, n in n_c.items() if n >= MIN_FARMERS_PER_CROP}
    return kept, vol, {c: n_c[c] for c in crops}


def make_farmers(centre, chosen, crops, seed):
    counts, vol, wanted = allocate_counts(chosen, crops)
    if not counts:
        sys.exit("No crop has enough local absorption for even three farmers.")
    rng = random.Random(seed)
    n = sum(counts.values())
    n_vill = max(4, round(n / 5))
    pool = [c for c, k in counts.items() for _ in range(k)]
    rng.shuffle(pool)
    villages = []
    for _ in range(n_vill):
        r = CLUSTER_RADIUS_KM * math.sqrt(rng.random())
        th = rng.uniform(0, 2 * math.pi)
        dn, de = _km_to_deg(centre[0], r * math.cos(th), r * math.sin(th))
        villages.append((centre[0] + dn, centre[1] + de, rng.choice(pool)))
    # assign crops so the per-crop COUNTS are exact; a farmer takes its village's lean crop while that crop's quota
    # lasts (60% of the time), otherwise whatever the quota still allows
    left = dict(counts)
    farmers = []
    for i in range(n):
        vlat, vlng, lean = villages[i % n_vill] if i < n_vill else rng.choice(villages)
        if left.get(lean, 0) > 0 and rng.random() < VILLAGE_CROP_LEAN:
            crop = lean
        else:
            crop = rng.choice([c for c, k in left.items() if k > 0])
        left[crop] -= 1
        jn, je = _km_to_deg(vlat, rng.gauss(0, VILLAGE_JITTER_KM), rng.gauss(0, VILLAGE_JITTER_KM))
        ready = rng.uniform(0, 4)
        farmers.append({"lat": round(vlat + jn, 5), "lng": round(vlng + je, 5), "crop": crop,
                        "qty_kg": round(rng.uniform(150, 600), 1), "ready_hr": round(ready, 2),
                        "deadline_hr": round(ready + rng.uniform(6, 14), 2)})
    farmers.sort(key=lambda f: (f["ready_hr"], f["lat"]))
    return farmers, vol, wanted


def fleet_composition(farmers):
    prod = {True: 0.0, False: 0.0}
    for f in farmers:
        prod[CROPS[f["crop"]]["needs_refrigeration"]] += f["qty_kg"]
    comp = {}
    for refrig, names in ((False, ("truck_5t", "truck_2t", "van")), (True, ("reefer_5t", "reefer_2t", "reefer_van"))):
        target = FLEET_RATIO * prod[refrig]
        if target <= 0:
            continue
        n5, n2, n1 = round(0.50 * target / 5000), round(0.35 * target / 2000), round(0.15 * target / 1000)
        if n5 + n2 + n1 == 0:
            n2 = 1
        for name, n in zip(names, (n5, n2, n1)):
            if n:
                comp[name] = n
    return comp, prod


# ----------------------------------------------------------------------------------------------------------------
# 5. render
# ----------------------------------------------------------------------------------------------------------------
def _d(d):
    return "{ " + ", ".join(f"{k}: {v}" for k, v in d.items()) + " }"


def make_blurb(cfg, report, imp_rep, chosen, crops, vol, farmers, comp, prod, centre, dropped_coords, bad_coords,
               implausible, tiny):
    names = ", ".join(m["name"].replace(" Apmc", "") for m in chosen)
    cc = Counter(f["crop"] for f in farmers)
    veh = sum(comp.values())
    cap = sum({"truck_5t": 5000, "reefer_5t": 5000, "truck_2t": 2000, "reefer_2t": 2000, "van": 1000,
               "reefer_van": 1000, "mini_pickup": 500}[k] * v for k, v in comp.items())
    n_series = sum(len(m["price"]) for m in chosen)
    ph = sum(1 for m in chosen for c in m["price"] if m["capacity_is_placeholder"][c])
    im = sum(1 for m in chosen for c in m["price"] if m["capacity_source"][c] == "imputed_peer_q1")
    cleaned = (report.get("dropped_modal_price_outside_min_max", 0) + report.get("dropped_price_outlier_vs_series_median", 0)
               + report.get("dropped_arrival_spike_over_20x_series_median", 0)
               + report.get("dropped_modal_price_missing_or_nonpositive", 0) + report.get("dropped_min_price_above_max_price", 0))
    parts = [
        f"REAL: {len(chosen)} {cfg['state']} mandis ({names}) with prices and daily arrivals from Agmarknet via India Data Portal, "
        f"{cfg['frm']} to {cfg['to']} (median of days; mandi coordinates are the portal's own). "
        f"Cleaned before use: {cleaned:,} rows dropped (prices outside min/max or 3x off the series median, arrival typos above 20x the median, "
        f"non-positive prices); {len(implausible)} mandi-crop series with implausible units (e.g. bundle prices labelled per quintal) dropped; "
        f"mandis without coordinates ({len(dropped_coords)}) or with suspect ones ({len(bad_coords)}) left out, and {len(tiny)} mandi-crop series "
        f"absorbing under {cfg.get('min_absorption_kg', MIN_USEFUL_ABSORPTION_KG) / 1000:g} t/day removed (too small to be a market for a pickup round). "
        f"Capacity is the median reported daily arrival, a proxy and not a limit: {ph} of {n_series} mandi-crop series here repeat one value on "
        f"70%+ of days, and {im} of those were raised to the state's lower-quartile arrival for that crop, which is an assumption. "
        f"SYNTHETIC: {len(farmers)} farmers ({', '.join(f'{c} {n}' for c, n in cc.most_common())}) in villages within {CLUSTER_RADIUS_KM:.0f} km of "
        f"({centre[0]:.2f}, {centre[1]:.2f}) and a {veh}-vehicle fleet; no public farmer or fleet data exists. "
        f"Counts are assumptions: about {N_TARGET} pickups per collection round (shared across crops by local volume, never more than "
        f"{CROP_ABSORPTION_SHARE:.0%} of a crop's daily absorption by these mandis), lots 150-600 kg, fleet capacity {cap / 1000:.0f} t = "
        f"{FLEET_RATIO:g}x the day's {sum(prod.values()) / 1000:.1f} t of produce. "
        f"The farm-gate price used in the comparison is an assumption too."]
    return " ".join(parts)


def make_about(cfg, report, imp_rep, chosen, crops, vol, farmers, comp, prod, centre, dropped_coords, bad_coords, implausible, tiny):
    """The same facts as make_blurb, but as short labelled lists for the frontend's "About the data" panel."""
    min_kg = cfg.get("min_absorption_kg", MIN_USEFUL_ABSORPTION_KG)
    names = ", ".join(m["name"].replace(" Apmc", "").replace("(Uzhavar Sandhai )", "").replace("(Uzhavar Sandhai)", "").strip() for m in chosen)
    cc = Counter(f["crop"] for f in farmers)
    veh = sum(comp.values())
    cap = sum({"truck_5t": 5000, "reefer_5t": 5000, "truck_2t": 2000, "reefer_2t": 2000, "van": 1000,
               "reefer_van": 1000, "mini_pickup": 500}[k] * v for k, v in comp.items())
    ph = sum(1 for m in chosen for c in m["price"] if m["capacity_is_placeholder"][c])
    cleaned = (report.get("dropped_modal_price_outside_min_max", 0) + report.get("dropped_price_outlier_vs_series_median", 0)
               + report.get("dropped_arrival_spike_over_20x_series_median", 0)
               + report.get("dropped_modal_price_missing_or_nonpositive", 0) + report.get("dropped_min_price_above_max_price", 0))
    capacity = ["Mandi capacity = median reported daily arrival: a proxy, not a hard limit"]
    if ph:
        capacity.append(f"{ph} mandi-crop series repeat one value on 70%+ of days; treat their capacity as an assumption")
    sections = [
        {"title": "Real", "items": [
            f"{len(chosen)} {cfg['state']} mandis: {names}",
            f"Prices and daily arrivals: Agmarknet via India Data Portal, {cfg['frm']} to {cfg['to']} (median of days)",
            "Mandi coordinates: the portal's own"]},
        {"title": "Synthetic", "items": [
            f"{len(farmers)} farmers ({', '.join(f'{c} {n}' for c, n in cc.most_common())}) in villages within {CLUSTER_RADIUS_KM:.0f} km of ({centre[0]:.2f}, {centre[1]:.2f}); lots 150-600 kg",
            f"{veh}-vehicle fleet, {cap / 1000:.0f} t = {FLEET_RATIO:g}x the day's {sum(prod.values()) / 1000:.1f} t of produce",
            "No public farmer or fleet data exists"]},
        {"title": "Assumptions", "items": capacity + [
            f"About {N_TARGET} pickups per round, never more than {CROP_ABSORPTION_SHARE:.0%} of a crop's daily absorption by these mandis",
            "The farm-gate price used in the comparison is assumed"]},
    ]
    if cfg.get("notes"):
        sections.append({"title": "Data caveats", "items": list(cfg["notes"])})
    sections.append({"title": "Cleaning", "items": [
        f"{cleaned:,} rows dropped (price or arrival outliers, invalid prices); {len(implausible)} series with implausible units (e.g. bundle prices) dropped",
        f"{len(dropped_coords)} mandis without coordinates and {len(bad_coords)} with suspect ones left out",
        f"{len(tiny)} mandi-crop series absorbing under {min_kg / 1000:g} t/day removed (too small for a pickup round)"]})
    return {"sections": sections}


def render_block(preset_id, cfg, blurb, farmers, comp, chosen, centre, about=None):
    q = json.dumps
    desc = f"    about: {q(about)}," if about else f"    blurb: {q(blurb)},"   # structured panel if given, else the legacy paragraph
    out = [f"  {preset_id}: {{", '    category: "real",', f"    label: {q(cfg['label'])},", desc, "    farmers: ["]
    for f in farmers:
        out.append(f'      {{ lat: {f["lat"]}, lng: {f["lng"]}, crop: "{f["crop"]}", qty_kg: {f["qty_kg"]}, '
                   f'ready_hr: {f["ready_hr"]}, deadline_hr: {f["deadline_hr"]} }},')
    out += ["    ],", "    vehicles: ["]
    out += [f'      {{ type_name: "{t}", count: {n} }},' for t, n in comp.items() if n]
    out += ["    ],", "    markets: ["]
    for m in chosen:
        d = haversine(centre[0], centre[1], m["lat"], m["lng"])
        notes = []
        for c in m["capacity_kg"]:
            if m["capacity_source"][c] == "imputed_peer_q1":
                notes.append(f'{c} capacity raised from {m["capacity_reported_kg"][c] / 1000:g} t (reported on '
                             f'{m["capacity_top_share"][c]:.0%} of days) to the state lower quartile')
            elif m["capacity_is_placeholder"][c]:
                notes.append(f'{c} capacity {m["capacity_kg"][c] / 1000:g} t repeats on {m["capacity_top_share"][c]:.0%} of days')
        note = (" | " + "; ".join(notes)) if notes else ""
        out.append(f'      {{ lat: {round(m["lat"], 5)}, lng: {round(m["lng"], 5)}, price: {_d(m["price"])}, '
                   f'capacity_kg: {_d({k: round(v) for k, v in m["capacity_kg"].items()})} }}, '
                   f'// {m["name"].replace(" Apmc", "")} ({m["district"]}), {d:.0f} km from farmer centre{note}')
    out += ["    ],", "  },"]
    return "\n".join(out)


def build_preset(preset_id, cfg, csv_path, out_dir=REGIONAL_DIR, hub=None):
    out_dir.mkdir(parents=True, exist_ok=True)
    df, report = load_clean(csv_path, cfg["state"], cfg["frm"], cfg["to"])
    emb_all = brm.embedded_coords(df)
    min_days = cfg.get("min_days", MIN_DAYS)   # a preset may lower it when its CSV samples few days (e.g. tamil_nadu: 5 days per mandi)
    # Manual coordinates for mandis the portal left blank (per preset, visible in PRESETS): (district, market, lat, lng, source)
    manual = {(cfg["state"], d_, m_): (la, ln, src) for d_, m_, la, ln, src in cfg.get("coords", [])}
    markets, dropped = brm.build(df, manual, min_days=min_days)
    implausible, markets = drop_implausible_series(markets)
    bad = coordinate_outliers(markets)
    markets = [m for m in markets if m["name"] not in bad]
    warns = brm.shared_coordinate_warnings(markets)
    imp_rep = impute_capacities(markets)
    min_kg = cfg.get("min_absorption_kg", MIN_USEFUL_ABSORPTION_KG)   # a preset may lower it for small farmers-market yards
    tiny, markets = drop_tiny_series(markets, min_kg)
    hub_m, centre, chosen, crops = choose_region(markets, hub or cfg["hub"], cfg.get("max_mandi_km"))
    farmers, vol, wanted = make_farmers(centre, chosen, crops, cfg["seed"])
    comp, prod = fleet_composition(farmers)
    blurb = make_blurb(cfg, report, imp_rep, chosen, crops, vol, farmers, comp, prod, centre, dropped, bad, implausible, tiny)
    about = make_about(cfg, report, imp_rep, chosen, crops, vol, farmers, comp, prod, centre, dropped, bad, implausible, tiny)
    block = render_block(preset_id, cfg, blurb, farmers, comp, chosen, centre, about=about)
    record = {"preset_id": preset_id, "config": cfg, "cleaning": report, "usable_markets_in_state_window": len(markets),
              "markets_dropped_no_or_invalid_coordinates": len(dropped), "markets_dropped_suspect_coordinates": bad,
              "shared_coordinate_warnings": warns, "series_dropped_implausible": implausible,
              "series_dropped_tiny_capacity": tiny,
              "capacity_imputation": imp_rep, "hub": hub_m["name"],
              "farmer_cluster_centre": centre, "mix_crops": crops, "mix_volume_kg": vol, "farmers_wanted_by_crop_after_absorption_cap": wanted,
              "assumptions": {"min_days": min_days, "min_useful_absorption_kg": min_kg, "n_target": N_TARGET, "crop_absorption_share": CROP_ABSORPTION_SHARE,
                              "min_farmers_per_crop": MIN_FARMERS_PER_CROP, "mean_lot_kg": MEAN_LOT_KG,
                              "plausible_price_kg": PLAUSIBLE_PRICE_KG, "plausible_price_kg_by_crop": PLAUSIBLE_PRICE_KG_BY_CROP, "plausible_max_arrival_kg": PLAUSIBLE_MAX_ARRIVAL_KG, "cluster_radius_km": CLUSTER_RADIUS_KM,
                              "village_crop_lean": VILLAGE_CROP_LEAN, "fleet_ratio": FLEET_RATIO, "seed": cfg["seed"]},
              "n_farmers": len(farmers), "fleet": comp, "produce_kg_by_refrigeration": {str(k): v for k, v in prod.items()},
              "markets": chosen}
    (out_dir / f"{preset_id}.json").write_text(json.dumps(record, indent=1, default=str))
    (out_dir / f"{preset_id}.js").write_text(block + "\n")
    return block, record


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preset", choices=sorted(PRESETS))
    ap.add_argument("--csv", help="the state's India Data Portal CSV")
    ap.add_argument("--hub", default=None, help="override the hub mandi name")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args(argv)
    if args.list or not args.preset:
        for k, v in PRESETS.items():
            print(f"{k:<22} {v['state']:<16} {v['frm']}..{v['to']}  hub {v['hub']}")
        return
    if not args.csv:
        sys.exit("--csv is required")
    block, rec = build_preset(args.preset, PRESETS[args.preset], args.csv, hub=args.hub)
    print(json.dumps({k: rec[k] for k in ("series_dropped_implausible", "capacity_imputation", "n_farmers", "fleet",
                                           "mix_crops", "farmers_wanted_by_crop_after_absorption_cap")}, indent=1, default=str))
    print("wrote", REGIONAL_DIR / f"{args.preset}.js", "and .json")


if __name__ == "__main__":
    main()
