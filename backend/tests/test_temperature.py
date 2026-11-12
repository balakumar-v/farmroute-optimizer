"""Simulated DHT22 room temperature -> unrefrigerated spoilage. Synthetic data; deterministic."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ilo_v3 as V
import temperature_sim as T
from baselines_v3 import summarize_with_farmgate
from logistics_lib_v2 import (ambient_spoil_factor, generate_scenario_v2, spoilage_fraction, use_ambient_temp)


def test_off_by_default_and_reference_is_neutral():
    base = spoilage_fraction("onion", False, 5.0)
    with use_ambient_temp(25.0):
        assert spoilage_fraction("onion", False, 5.0) == base
    with use_ambient_temp(None):
        assert spoilage_fraction("onion", False, 5.0) == base


def test_warmer_spoils_more_only_when_unrefrigerated():
    with use_ambient_temp(20.0):
        cool, cool_r = spoilage_fraction("tomato", False, 5.0), spoilage_fraction("tomato", True, 5.0)
    with use_ambient_temp(30.0):
        warm, warm_r = spoilage_fraction("tomato", False, 5.0), spoilage_fraction("tomato", True, 5.0)
    assert warm > cool and abs(warm / cool - 2.0) < 1e-9      # Q10 = 2 over 10 C
    assert warm_r == cool_r
    assert abs(ambient_spoil_factor(35.0) - 2 ** 1.0) < 1e-9


def test_readings_stay_in_room_range_and_always_move():
    T.seed(7)
    prev, seen = None, []
    for _ in range(200):
        r = T.next_reading()
        assert 20.0 <= r["temp_c"] <= 30.0 and r["sensor"] == "DHT22" and r["simulated"]
        if prev is not None:
            assert r["temp_c"] != prev
        prev = r["temp_c"]
        seen.append(prev)
    assert max(seen) - min(seen) > 1.5                      # wanders across most of the 27-30 C room band


def test_plan_spoilage_follows_temperature():
    farmers, fleet, markets = generate_scenario_v2(n_farmers=30, n_markets=3, seed=1)
    out = {}
    for t in (20.0, 30.0):
        with use_ambient_temp(t):
            res = V.run_ilo_v3(farmers, fleet, markets)
        out[t] = summarize_with_farmgate(res, farmers, markets, len(fleet))["total_spoilage_kg"]
    assert out[30.0] > out[20.0]


def test_describe_curve_matches_current_reading():
    reading = {"temp_c": 26.0, "previous_temp_c": 24.0, "sensor": "DHT22", "simulated": True}
    pools = [{"vehicle_id": 1, "spoilage_loss_kg": 10.0}, {"vehicle_id": 2, "spoilage_loss_kg": 4.0}]
    d = T.describe(reading, pools, [{"id": 1, "refrigerated": False}, {"id": 2, "refrigerated": True}])
    assert d["unrefrigerated_trips"] == 1 and d["refrigerated_trips"] == 1
    at = {c["temp_c"]: c["spoilage_kg"] for c in d["curve"]}
    assert at[30.0] > at[20.0] > 4.0                         # reefer share (4 kg) never moves
    assert abs(d["unrefrigerated_spoilage_kg"] + d["refrigerated_spoilage_kg"] - 14.0) < 1e-9
