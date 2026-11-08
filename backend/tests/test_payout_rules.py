"""Split rules (payout_rules.py), operator fee, downside range and the fairness report."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import advisor
import ilo_v3 as V
import payout_rules as PR
from baselines_v3 import FARMGATE_DISCOUNT, FarmgatePrices, run_farmgate_baseline_v2, summarize_with_farmgate
from logistics_lib_v2 import Farmer, Market, generate_scenario_v2


def _farmer(i, lat, lng, qty=100.0, crop="tomato"):
    return Farmer(id=i, lat=lat, lng=lng, crop=crop, qty_kg=qty, ready_hr=6.0, deadline_hr=14.0,
                  needs_refrigeration=False)


def _prices():
    return FarmgatePrices([Market(id=1, lat=13.0, lng=80.0, price={"tomato": 30.0}, capacity_kg=1e6)], discount=0.2)


def _pool_result(net, revenue, cost):
    return {"net_return": net, "revenue": revenue, "transport_cost": cost}


def test_kg_rule_matches_the_original_formula():
    prices = _prices()
    members = [_farmer(1, 13.0, 80.0, 100), _farmer(2, 13.1, 80.0, 300)]
    res = _pool_result(net=12000.0, revenue=13000.0, cost=1000.0)
    out = PR.split_trip("kg", members, res, prices)
    fg = {f.id: prices.value(f) for f in members}
    surplus = 12000.0 - sum(fg.values())
    assert out[1] == pytest.approx(fg[1] + surplus * 0.25)
    assert out[2] == pytest.approx(fg[2] + surplus * 0.75)


def test_cost_aware_charges_the_farmer_who_adds_the_detour():
    prices = _prices()
    # three equal lots; farmer 3 is ~44 km further down the road than the others
    order = [_farmer(1, 13.00, 80.00), _farmer(2, 13.01, 80.00), _farmer(3, 13.40, 80.00)]
    res = _pool_result(net=8400.0, revenue=9000.0, cost=600.0)
    kg = PR.split_trip("kg", order, res, prices)
    ca = PR.split_trip("cost_aware", order, res, prices, per_km_cost=12.0)
    assert ca[3] < kg[3]                           # the far farmer carries more of the pickup cost
    assert ca[1] > kg[1] and ca[2] > kg[2]
    assert sum(ca.values()) == pytest.approx(8400.0)
    assert all(ca[i] >= 2400.0 - 1e-9 for i in ca)


@pytest.mark.parametrize("rule", PR.SPLIT_RULES)
@pytest.mark.parametrize("seed", [1, 2])
def test_every_rule_sums_to_net_return_and_respects_the_floor(rule, seed):
    farmers, fleet, markets = generate_scenario_v2(n_farmers=40, n_markets=3, seed=seed)
    res = V.run_ilo_v3(farmers, copy.deepcopy(fleet), markets, split_rule=rule)
    prices = FarmgatePrices(markets, FARMGATE_DISCOUNT)
    by_id = {f.id: f for f in farmers}
    hauled = [r for r in res if r["vehicle_id"] is not None]
    assert hauled
    for r in hauled:
        assert sum(r["per_farmer_net"].values()) == pytest.approx(r["net_return"], rel=1e-6, abs=1e-6)
        for fid, v in r["per_farmer_net"].items():
            assert v >= prices.value(by_id[fid]) - 1e-6
        assert r["split_rule"] == rule


def test_lift_to_floor_keeps_the_total():
    prices = _prices()
    order = [_farmer(1, 13.0, 80.0, 50), _farmer(2, 13.0, 80.0, 500), _farmer(3, 13.5, 80.0, 50)]
    fg = {f.id: prices.value(f) for f in order}
    pay = {1: fg[1] - 200.0, 2: fg[2] + 900.0, 3: fg[3] + 100.0}
    net = sum(fg.values()) + 400.0
    out = PR._lift_to_floor(order, pay, fg, net)
    assert sum(out.values()) == pytest.approx(net)
    assert all(out[i] >= fg[i] - 1e-9 for i in out)


# ---------------------------------------------------------------- advisor: fee, range, fairness
def _plan(seed=1, n=40, rule="kg"):
    farmers, fleet, markets = generate_scenario_v2(n_farmers=n, n_markets=3, seed=seed)
    res, meta = V.run_ilo_v3(farmers, copy.deepcopy(fleet), markets, return_meta=True, split_rule=rule)
    fs = len(fleet)
    snap = {"farmers": [f.__dict__ for f in farmers],
            "fleet": [{"id": v.id, "type_name": v.type_name, "capacity_kg": v.capacity_kg,
                       "refrigerated": v.refrigerated, "fixed_cost": v.fixed_cost, "per_km_cost": v.per_km_cost}
                      for v in fleet],
            "markets": [{"id": m.id, "lat": m.lat, "lng": m.lng, "price": m.price, "capacity_kg": m.capacity_kg}
                        for m in markets]}
    fg = run_farmgate_baseline_v2(farmers, markets)
    return json.loads(json.dumps({
        "input_snapshot": snap,
        "integrated_logistics_optimization": {"pools": res, "summary": summarize_with_farmgate(res, farmers, markets, fs)},
        "realistic_baselines": {"assumptions": {"farmgate_discount": FARMGATE_DISCOUNT}, "ilo_meta": meta,
                                "farmgate_only": {"pools": fg, "summary": summarize_with_farmgate(fg, farmers, markets, fs)}}}))


@pytest.fixture(scope="module")
def plan():
    return _plan()


def test_default_fee_is_zero_and_totals_match(plan, monkeypatch):
    monkeypatch.delenv("OPERATOR_FEE_PCT", raising=False)
    out = advisor.payout_statements(plan)
    assert out["operator_fee_total_inr"] == 0
    assert out["total_inr"] == pytest.approx(out["plan_value_inr"], rel=1e-6)


def test_fee_is_taken_from_gain_only_and_totals_plus_fee_match(plan):
    out = advisor.payout_statements(plan, fee_pct=10.0)
    assert out["operator_fee_total_inr"] > 0
    assert out["total_inr"] + out["operator_fee_total_inr"] == pytest.approx(out["plan_value_inr"], rel=1e-6)
    for s in out["statements"]:
        doorstep = next(l["value"] for l in s["lines"] if l["key"] == "doorstep_value")
        assert s["total_inr"] >= doorstep - 1e-6                   # a fee never pushes anyone below the doorstep
        assert s["operator_fee_inr"] >= 0
        if s["status"] != "hauled":
            assert s["operator_fee_inr"] == 0


def test_fee_is_capped_by_env(plan, monkeypatch):
    monkeypatch.setenv("OPERATOR_FEE_PCT", "400")
    assert advisor.operator_fee_pct() == 50.0
    monkeypatch.setenv("OPERATOR_FEE_PCT", "abc")
    assert advisor.operator_fee_pct() == 0.0


def test_range_low_never_exceeds_planned(plan):
    for s in advisor.payout_statements(plan)["statements"]:
        r = s["range_inr"]
        assert r["low"] <= r["planned"] + 1e-6
        assert r["planned"] == pytest.approx(s["total_inr"])


def test_farmer_cards_carry_only_own_range(plan):
    snap = plan["input_snapshot"]
    cards = advisor.farmer_cards(plan, {"routes": []}, "2026-01-01T00:00:00Z", None, None)
    for c in cards.values():
        assert set(c["payout"]["range_inr"]) == {"low", "planned"}
        assert "operator_fee_inr" in c["payout"]


def test_fairness_metrics_shape_and_bounds(plan):
    m = advisor.fairness_metrics(plan)
    n = len(plan["input_snapshot"]["farmers"])
    assert m["farmers"] == n and sum(m["by_status"].values()) == n
    assert 0 <= m["gaining"] <= n
    assert 0.0 <= m["gini_of_gains"] <= 1.0
    assert m["total_gain_inr"] >= -1e-6
    assert m["min_hauled_gain_inr"] >= -1e-6
    assert m["split_rules"] == ["kg"]


def test_fairness_reports_the_rule_used():
    assert advisor.fairness_metrics(_plan(seed=2, n=30, rule="cost_aware"))["split_rules"] == ["cost_aware"]


def test_gini_extremes():
    assert advisor._gini([5, 5, 5, 5]) == pytest.approx(0.0)
    assert advisor._gini([0, 0, 0, 10]) == pytest.approx(0.75)
