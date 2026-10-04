"""
Regression tests for ILO's economic dispatch (algorithms_v2.run_our_system_v2).

Background: with withhold_uneconomic=False (the behaviour before economic dispatch) the planner dispatches
every pool that can get a truck, even at a loss, and leaves other pools without a truck. The default plan
withholds loss-making trips so their vehicle-time and market capacity go to profitable ones.
All scenarios are the project's own synthetic generator (deterministic seeds); nothing here is real data.
"""
import copy
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import algorithms_v2 as A
from logistics_lib_v2 import generate_scenario_v2

LOSS_CASE = (20, 304)     # original behaviour dispatches a losing pool here
SMALL_CASES = [(n, s) for n in (12, 16, 20) for s in (300, 304, 310, 319)]


def _run(n, seed, **kw):
    farmers, fleet, markets = generate_scenario_v2(n_farmers=n, n_markets=3, seed=seed)
    res = A.run_our_system_v2(farmers, copy.deepcopy(fleet), markets, **kw)
    return farmers, fleet, markets, res


def _net(res):
    return sum(r["net_return"] for r in res)


def _loss_pools(res):
    return [r for r in res if r["vehicle_id"] is not None and r["net_return"] < 0]


def test_old_behaviour_dispatches_a_loss_and_default_does_not():
    n, seed = LOSS_CASE
    _, _, _, old = _run(n, seed, withhold_uneconomic=False)
    _, _, _, new = _run(n, seed)
    assert len(_loss_pools(old)) >= 1                       # the defect this feature fixes
    assert _loss_pools(new) == []
    assert _net(new) > _net(old)
    assert sum(r.get("withheld_uneconomic_kg", 0) for r in new) > 0   # produce deliberately not shipped


@pytest.mark.parametrize("n,seed", SMALL_CASES)
def test_never_worse_than_dispatch_everything(n, seed):
    _, _, _, old = _run(n, seed, withhold_uneconomic=False)
    _, _, _, new = _run(n, seed)
    assert _net(new) >= _net(old) - 1e-6


@pytest.mark.parametrize("n,seed", SMALL_CASES)
def test_plan_is_valid(n, seed):
    farmers, fleet, markets = generate_scenario_v2(n_farmers=n, n_markets=3, seed=seed)
    res, trace = A.run_our_system_v2(farmers, copy.deepcopy(fleet), markets, return_trace=True)
    qty = {f.id: f.qty_kg for f in farmers}
    cap = {v.id: v.capacity_kg for v in fleet}
    seen = Counter(i for r in res for i in r["farmer_ids"])
    assert set(seen) == set(qty) and all(c == 1 for c in seen.values())      # every farmer in exactly one pool
    for r in res:
        total = sum(qty[i] for i in r["farmer_ids"])
        assert total == pytest.approx(r["total_qty_kg"])
        if r["vehicle_id"] is not None:
            assert total <= cap[r["vehicle_id"]] + 1e-6                       # truck capacity respected
        if r.get("withheld"):
            assert r["revenue"] == 0 and r["transport_cost"] == 0 and r["vehicle_id"] is None
        assert r["net_return"] == pytest.approx(r["revenue"] - r["transport_cost"])
        assert r["unsold_kg"] + r["unserved_no_vehicle_kg"] + r.get("withheld_uneconomic_kg", 0) <= total + 1e-6
    used = Counter()
    for t in trace.values():
        for crop, edges in t.crop_allocations.items():
            for e in edges:
                used[(e["market_id"], crop)] += e["kg"]
    caps = {m.id: m.capacity_kg for m in markets}
    for (mid, crop), kg in used.items():
        assert kg <= caps[mid].get(crop, 0) + 1e-3                            # market capacity respected


def test_summary_counts_withheld_produce_as_not_served():
    n, seed = LOSS_CASE
    farmers, fleet, markets, res = _run(n, seed)
    s = A.summarize(res, len(farmers), len(fleet))
    withheld = sum(r.get("withheld_uneconomic_kg", 0) for r in res)
    assert withheld > 0 and s["total_withheld_kg"] == pytest.approx(withheld)
    expected = 100 * (1 - (s["total_unsold_kg"] + s["total_unserved_no_vehicle_kg"] + withheld) / s["total_qty_kg"])
    assert s["pct_qty_served"] == pytest.approx(expected)


def test_deterministic():
    n, seed = LOSS_CASE
    a = _run(n, seed)[3]
    b = _run(n, seed)[3]
    assert [(r["farmer_ids"], r["vehicle_id"], round(r["net_return"], 6)) for r in a] == \
           [(r["farmer_ids"], r["vehicle_id"], round(r["net_return"], 6)) for r in b]


def test_random_claim_orders_never_hurt_and_can_be_disabled(monkeypatch):
    n, seed = SMALL_CASES[0]
    with_rand = _net(_run(n, seed)[3])
    monkeypatch.setattr(A, "N_RANDOM_ORDERS", 0)
    without = _net(_run(n, seed)[3])
    assert with_rand >= without - 1e-6
