"""Monte Carlo replay of a finished plan (stress.py) and the value-gain-sharing-only split."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ilo_v3 as V
import logistics_lib_v2 as L
from baselines_v3 import FarmgatePrices
from logistics_lib_v2 import generate_scenario_v2
from stress import monte_carlo_stress, withhold_fragile


def _plan(seed=1, n=50):
    farmers, fleet, markets = generate_scenario_v2(n_farmers=n, n_markets=3, seed=seed)
    res = V.run_ilo_v3(farmers, copy.deepcopy(fleet), markets)
    return farmers, fleet, markets, res


def test_per_farmer_net_is_value_gain_sharing_and_never_below_the_doorstep_price():
    farmers, fleet, markets, res = _plan()
    prices = FarmgatePrices(markets)
    by = {f.id: f for f in farmers}
    trips = [r for r in res if r["vehicle_id"] is not None]
    assert trips
    for r in trips:
        share = r["per_farmer_net"]
        assert sum(share.values()) == pytest.approx(r["net_return"])
        for i, v in share.items():
            assert v >= prices.value(by[i]) - 1e-6
        assert "per_farmer_value_gain_sharing" not in r


def test_dispatch_hr_recorded_and_zero_noise_replay_matches_the_plan():
    farmers, fleet, markets, res = _plan(seed=2)
    prices = FarmgatePrices(markets)
    trips = [r for r in res if r["vehicle_id"] is not None]
    assert all("dispatch_hr" in r for r in trips)
    mc = monte_carlo_stress(res, farmers, fleet, markets, prices, n_draws=3, travel_sd=0.0, ready_delay_sd_hr=0.0,
                            mandi_price_sd=0.0, farmgate_sd=0.0)
    by = {f.id: f for f in farmers}
    planned = sum(r["net_return"] - prices.value_of([by[i] for i in r["farmer_ids"]]) for r in trips)
    assert mc["plan"]["nominal_gain"] == pytest.approx(planned, rel=0.02)         # replay reproduces the plan
    assert mc["plan"]["sd_gain"] == pytest.approx(0.0, abs=1e-6)                  # no shocks -> no spread
    assert all(t["p_beat"] == 1.0 for t in mc["trips"])


def test_noise_widens_the_distribution_and_speed_is_restored():
    farmers, fleet, markets, res = _plan(seed=3)
    prices = FarmgatePrices(markets)
    speed0 = L.AVG_SPEED_KMPH
    mc = monte_carlo_stress(res, farmers, fleet, markets, prices, n_draws=30, seed=1)
    p = mc["plan"]
    assert L.AVG_SPEED_KMPH == speed0 and V.AVG_SPEED_KMPH == speed0
    assert p["sd_gain"] > 0 and p["p5_gain"] <= p["p50_gain"] <= p["p95_gain"]
    assert p["gain_if_each_trip_chosen_ex_post"] >= p["mean_gain"] - 1e-6
    assert all(0.0 <= t["p_beat"] <= 1.0 and 0.0 <= t["p_lost"] <= 1.0 for t in mc["trips"])


def test_withhold_fragile_keeps_only_robust_trips():
    farmers, fleet, markets, res = _plan(seed=1)
    prices = FarmgatePrices(markets)
    mc = monte_carlo_stress(res, farmers, fleet, markets, prices, n_draws=30, seed=2,
                            mandi_price_sd=0.25, farmgate_sd=0.25)
    out, n = withhold_fragile(res, farmers, mc, min_prob=0.999)
    kept = [r for r in out if r["vehicle_id"] is not None]
    assert len(kept) + n == sum(1 for r in res if r["vehicle_id"] is not None)
    probs = {frozenset(t["farmer_ids"]): t["p_beat"] for t in mc["trips"]}
    assert all(probs[frozenset(r["farmer_ids"])] >= 0.999 for r in kept)


def test_run_ilo_v3_can_attach_mc_and_filter():
    farmers, fleet, markets = generate_scenario_v2(n_farmers=40, n_markets=3, seed=4)
    res, meta = V.run_ilo_v3(farmers, copy.deepcopy(fleet), markets, return_meta=True, mc_draws=10, mc_min_prob=0.8)
    assert meta["monte_carlo"]["n_draws"] == 10 and "trips_withheld_as_fragile" in meta["monte_carlo"]
    for r in res:
        if r["vehicle_id"] is not None:
            assert r["mc"]["p_beat"] >= 0.8


def test_spoilage_shock_widens_the_distribution_and_restores_rates():
    farmers, fleet, markets, res = _plan(seed=3)
    prices = FarmgatePrices(markets)
    rates0 = {c: v["base_spoil_per_hr"] for c, v in L.CROPS.items()}
    kw = dict(n_draws=20, seed=5, travel_sd=0.0, ready_delay_sd_hr=0.0, mandi_price_sd=0.0, farmgate_sd=0.0)
    flat = monte_carlo_stress(res, farmers, fleet, markets, prices, **kw)["plan"]
    shocked = monte_carlo_stress(res, farmers, fleet, markets, prices, spoilage_rate_sd=0.6, **kw)["plan"]
    assert flat["sd_gain"] == pytest.approx(0.0, abs=1e-6)
    assert shocked["sd_gain"] > 0.0 and shocked["shocks"]["spoilage_rate_sd"] == 0.6
    assert {c: v["base_spoil_per_hr"] for c, v in L.CROPS.items()} == rates0


def test_spoilage_params_context_changes_and_restores_the_model():
    base = L.spoilage_fraction("tomato", False, 4.0)
    with L.spoilage_params(rate_scale=2.0, unrefrig_mult=6.0, cap=0.9):
        assert L.spoilage_fraction("tomato", False, 4.0) == pytest.approx(0.9)       # 0.02*2*6*4 = 0.96 -> cap 0.9
        assert L.spoilage_fraction("tomato", True, 4.0) == pytest.approx(0.16)
    assert L.spoilage_fraction("tomato", False, 4.0) == pytest.approx(base)
    assert L.SPOIL_UNREFRIG_MULT == 3.0 and L.SPOIL_CAP == 0.6
