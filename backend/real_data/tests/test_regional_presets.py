"""
Tests for build_regional_presets.py. Every number is a SYNTHETIC FIXTURE built to exercise a code path; none of it is
real Agmarknet data. The end-to-end test writes a tiny CSV in the India Data Portal's own header format.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import build_regional_presets as brp

HEADER = ("Date (date),State Name (state_name),State Code (state_code),District Name (district_name),"
          "District Code (district_code),Market Center Name (market_center_name),Market Center Code (market_center_code),"
          "Market Category (category),Establishment Year (year_of_establishment),Latitude (latitude),Longitude (longitude),"
          "Commodity Name (commodity_name),Commodity Id (commodity_id),Variety (variety),Grade (grade),"
          "Arrival Quantity (arrival_quantity),Arrival Units (arrival_units),Minimum Price (min_price),"
          "Maximum Price (max_price),Modal Price (modal_price),Price Unit (price_unit)")


def _row(day, market, commodity, arrival, modal, lo=None, hi=None, lat=12.9, lng=77.5, unit="Metric Tonnes",
         price_unit="Rs./Quintal", state="Karnataka"):
    lo = modal - 100 if lo is None else lo
    hi = modal + 100 if hi is None else hi
    return (f'"{day}","{state}","29","Dist","1","{market}","1","Primary","1990",{lat},{lng},"{commodity}","1","Other",'
            f'"Other",{arrival},"{unit}",{lo},{hi},{modal},"{price_unit}"')


def _csv(tmp_path, rows):
    p = tmp_path / "state.csv"
    p.write_text(HEADER + "\n" + "\n".join(rows) + "\n")
    return p


# ---------------------------------------------------------------- cleaning
def test_load_clean_drops_each_class_of_bad_row_and_counts_them(tmp_path):
    rows = []
    for d in range(1, 21):
        day = f"2026-03-{d:02d}"
        rows.append(_row(day, "Good Apmc", "Onion", 5 + d % 3, 2000 + 10 * (d % 4)))
    rows.append(_row("2026-03-21", "Good Apmc", "Onion", 5, 0))                                  # zero price
    rows.append(_row("2026-03-22", "Good Apmc", "Onion", 5, 2000, lo=2500, hi=2600))             # modal outside min-max
    rows.append(_row("2026-03-23", "Good Apmc", "Onion", 5, 2000, lo=2200, hi=1900))             # min > max
    rows.append(_row("2026-03-24", "Good Apmc", "Onion", 5, 9000, lo=8900, hi=9100))             # 4.5x the median
    rows.append(_row("2026-03-25", "Good Apmc", "Onion", 60500, 2000))                           # 60,500 t typo
    rows.append(_row("2026-03-26", "Good Apmc", "Onion", 5, 2000, price_unit="Rs./Nos"))        # unusable price unit
    df, rep = brp.load_clean(_csv(tmp_path, rows), "Karnataka", "2026-03-01", "2026-03-31")
    assert rep["dropped_modal_price_missing_or_nonpositive"] == 1
    assert rep["dropped_modal_price_outside_min_max"] == 1
    assert rep["dropped_min_price_above_max_price"] == 1
    assert rep["dropped_price_outlier_vs_series_median"] == 1
    assert rep["dropped_arrival_spike_over_20x_series_median"] == 1
    assert rep["dropped_price_unit_not_rs_per_quintal_or_kg"] == 1
    assert len(df) == 20 and rep["rows_after_cleaning"] == 20


def test_load_clean_keeps_price_but_ignores_arrival_with_a_non_weight_unit(tmp_path):
    rows = [_row(f"2026-03-{d:02d}", "Bundle Apmc", "Spinach", 400, 1500, unit="Bundle") for d in range(1, 21)]
    df, rep = brp.load_clean(_csv(tmp_path, rows), "Karnataka", "2026-03-01", "2026-03-31")
    assert len(df) == 20 and rep["arrival_unit_unusable_rows (price kept, arrival ignored: Nos/Bundle...)"] == 20


# ---------------------------------------------------------------- series filters and imputation
def _mkt(name, crop, price, cap_kg, placeholder=False, top=0.2):
    return {"name": name, "state": "S", "district": "D", "lat": 12.0, "lng": 77.0, "price": {crop: price},
            "capacity_kg": {crop: cap_kg}, "n_days": {crop: 30}, "last_date": {crop: "2026-03-30"},
            "capacity_top_share": {crop: top}, "capacity_is_placeholder": {crop: placeholder}}


def test_implausible_series_are_dropped_with_a_reason():
    ms = [_mkt("A", "spinach", 0.1, 5000), _mkt("B", "spinach", 9.0, 20_000_000), _mkt("C", "spinach", 9.0, 50_000),
          _mkt("D", "mango", 250.0, 20_000)]
    why, kept = brp.drop_implausible_series(ms)
    assert [m["name"] for m in kept] == ["C", "D"]               # premium mango is allowed, bundle-priced spinach is not
    assert len(why) == 2 and "price" in why[0] and "ceiling" in why[1]


def test_imputation_raises_placeholders_to_the_peer_lower_quartile_and_never_lowers():
    peers = [_mkt(f"P{i}", "onion", 10.0, cap) for i, cap in enumerate([10_000, 20_000, 30_000, 40_000, 50_000])]
    small = _mkt("Small", "onion", 10.0, 4_000, placeholder=True, top=1.0)
    big = _mkt("Big", "onion", 10.0, 90_000, placeholder=True, top=0.9)
    rep = brp.impute_capacities(peers + [small, big])
    assert rep["peer_q1_kg"]["onion"] == pytest.approx(20_000)
    assert small["capacity_kg"]["onion"] == pytest.approx(20_000) and small["capacity_source"]["onion"] == "imputed_peer_q1"
    assert big["capacity_kg"]["onion"] == 90_000 and big["capacity_source"]["onion"] == "reported"
    assert small["capacity_reported_kg"]["onion"] == 4_000


def test_imputation_needs_at_least_five_peers():
    ms = [_mkt(f"P{i}", "onion", 10.0, 20_000) for i in range(4)] + [_mkt("S", "onion", 10.0, 4_000, True, 1.0)]
    brp.impute_capacities(ms)
    assert ms[-1]["capacity_kg"]["onion"] == 4_000 and ms[-1]["capacity_source"]["onion"] == "reported"


def test_tiny_series_are_removed_and_empty_mandis_disappear():
    ms = [_mkt("Tiny", "onion", 10.0, 500), _mkt("Fine", "onion", 10.0, 5000)]
    brp.impute_capacities(ms)
    dropped, kept = brp.drop_tiny_series(ms)
    assert [m["name"] for m in kept] == ["Fine"] and len(dropped) == 1


# ---------------------------------------------------------------- counts
def _chosen(onion_kg, tomato_kg, n=3):
    return [{"name": f"M{i}", "capacity_kg": {"onion": onion_kg / n, "tomato": tomato_kg / n},
             "price": {"onion": 10, "tomato": 12}} for i in range(n)]


def test_counts_follow_sqrt_volume_but_are_capped_by_local_absorption():
    counts, vol, wanted = brp.allocate_counts(_chosen(1_000_000, 100_000), ["onion", "tomato"])
    assert counts["onion"] > counts["tomato"] and sum(counts.values()) <= brp.N_TARGET
    # a crop the local mandis barely absorb cannot get more than 30% of its absorption as produce
    counts2, vol2, _ = brp.allocate_counts(_chosen(1_000_000, 20_000), ["onion", "tomato"])
    assert counts2["tomato"] * brp.MEAN_LOT_KG <= brp.CROP_ABSORPTION_SHARE * vol2["tomato"] + brp.MEAN_LOT_KG
    # and a crop that would get fewer than 3 farmers is left out entirely
    counts3, _, wanted3 = brp.allocate_counts(_chosen(1_000_000, 3_000), ["onion", "tomato"])
    assert "tomato" not in counts3 and wanted3["tomato"] < brp.MIN_FARMERS_PER_CROP


def test_farmers_are_deterministic_clustered_in_range_and_match_the_crop_counts():
    chosen = _chosen(600_000, 400_000)
    centre = (13.0, 77.5)
    a, vol, _ = brp.make_farmers(centre, chosen, ["onion", "tomato"], seed=5)
    b, _, _ = brp.make_farmers(centre, chosen, ["onion", "tomato"], seed=5)
    c, _, _ = brp.make_farmers(centre, chosen, ["onion", "tomato"], seed=6)
    assert a == b and a != c
    counts, _, _ = brp.allocate_counts(chosen, ["onion", "tomato"])
    assert {k: sum(f["crop"] == k for f in a) for k in counts} == counts
    from logistics_lib_v2 import haversine
    assert all(haversine(centre[0], centre[1], f["lat"], f["lng"]) <= brp.CLUSTER_RADIUS_KM + 6 for f in a)
    assert all(150 <= f["qty_kg"] <= 600 and 0 <= f["ready_hr"] <= 4 and 6 <= f["deadline_hr"] - f["ready_hr"] <= 14 for f in a)


def test_fleet_capacity_is_the_ratio_times_produce_and_refrigeration_is_sized_separately():
    farmers = ([{"crop": "onion", "qty_kg": 400.0}] * 20) + ([{"crop": "tomato", "qty_kg": 400.0}] * 10)
    comp, prod = brp.fleet_composition(farmers)
    cap = {"truck_5t": 5000, "truck_2t": 2000, "van": 1000, "reefer_5t": 5000, "reefer_2t": 2000, "reefer_van": 1000}
    plain = sum(cap[k] * n for k, n in comp.items() if not k.startswith("reefer"))
    cold = sum(cap[k] * n for k, n in comp.items() if k.startswith("reefer"))
    assert plain == pytest.approx(brp.FLEET_RATIO * prod[False], rel=0.4) and cold > 0
    assert prod[False] == 8000 and prod[True] == 4000          # tomato is refrigerated in the project's crop table


def test_coordinate_outliers_flag_a_mandi_far_from_its_districts_other_mandis():
    ms = [dict(_mkt(f"N{i}", "onion", 10, 5000), lat=12.0 + 0.1 * i, lng=77.0) for i in range(3)]
    ms.append(dict(_mkt("Far", "onion", 10, 5000), lat=18.0, lng=77.0))
    assert brp.coordinate_outliers(ms) == ["Far"]
