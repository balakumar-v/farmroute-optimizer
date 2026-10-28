"""
Tests for the spoilage-first mode of ILO v3 (run_ilo_v3_spoilage_first, spoil_weight). Synthetic data; deterministic.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import baselines_v3 as B
import ilo_v3 as V
from logistics_lib_v2 import generate_scenario_v2


def _scenario(n=30, seed=1):
    return generate_scenario_v2(n_farmers=n, n_markets=3, seed=seed)


def _summ(res, farmers, markets, fleet):
    return B.summarize_with_farmgate(res, farmers, markets, len(fleet))


def test_zero_weight_changes_nothing():
    farmers, fleet, markets = _scenario()
    a = _summ(V.run_ilo_v3(farmers, fleet, markets), farmers, markets, fleet)
    b = _summ(V.run_ilo_v3(farmers, fleet, markets, spoil_weight=0.0), farmers, markets, fleet)
    assert a["net_return_incl_farmgate"] == b["net_return_incl_farmgate"]
    assert a["total_spoilage_kg"] == b["total_spoilage_kg"]


def test_spoilage_first_cuts_spoilage_within_the_value_budget():
    farmers, fleet, markets = _scenario(30, 1)
    base = _summ(V.run_ilo_v3(farmers, fleet, markets), farmers, markets, fleet)
    res, meta = V.run_ilo_v3_spoilage_first(farmers, fleet, markets, max_value_sacrifice=0.10, return_meta=True)
    out = _summ(res, farmers, markets, fleet)
    assert meta["mode"] == "spoilage"
    assert out["net_return_incl_farmgate"] >= 0.90 * base["net_return_incl_farmgate"] - 1e-6
    assert out["total_spoilage_kg"] < 0.7 * base["total_spoilage_kg"]          # this scenario: 426 kg -> ~261 kg
    assert out["total_spoilage_kg"] > 0                                         # not the degenerate "haul nothing"


@pytest.mark.parametrize("seed", [1, 3])
def test_never_more_spoilage_or_less_than_budget_than_returns_plan(seed):
    farmers, fleet, markets = _scenario(30, seed)
    for eps in (0.0, 0.10):
        res, meta = V.run_ilo_v3_spoilage_first(farmers, fleet, markets, max_value_sacrifice=eps, return_meta=True)
        sf = meta["spoilage_first"]
        out = _summ(res, farmers, markets, fleet)
        assert out["total_spoilage_kg"] <= sf["returns_plan_spoilage_kg"] + 1e-6
        assert out["net_return_incl_farmgate"] >= (1 - eps) * sf["returns_plan_value"] - 1e-6


def test_frontier_starts_with_the_returns_plan():
    farmers, fleet, markets = _scenario(30, 3)
    _, meta = V.run_ilo_v3_spoilage_first(farmers, fleet, markets, return_meta=True)
    fr = meta["spoilage_first"]["frontier"]
    assert fr[0]["weight"] == 0 and len(fr) == len(V.SPOIL_WEIGHTS)
    assert meta["spoilage_first"]["chosen_weight"] in {x["weight"] for x in fr}


def test_trip_score_equals_net_when_weight_zero_and_penalises_spoilage_otherwise():
    farmers, fleet, markets = _scenario(10, 1)
    prices = B.FarmgatePrices(markets, 0.2)
    vt = V._fleet_types(fleet)
    e0 = V._eval_trip([farmers[0]], markets, prices, vt, 0.0)
    e1 = V._eval_trip([farmers[0]], markets, prices, vt, 0.0, spoil_weight=2.0)
    assert e0["score"] == e0["net"]
    assert e1["net"] == pytest.approx(e0["net"]) or e1["market"].id != e0["market"].id   # real net is never rewritten
    assert e1["score"] == pytest.approx(e1["net"] - 2.0 * e1["spoil_val"])


def test_invalid_arguments_are_rejected():
    farmers, fleet, markets = _scenario(10, 1)
    with pytest.raises(ValueError):
        V.run_ilo_v3_spoilage_first(farmers, fleet, markets, weights=(1.0, 3.0))
    with pytest.raises(ValueError):
        V.run_ilo_v3_spoilage_first(farmers, fleet, markets, max_value_sacrifice=1.0)
