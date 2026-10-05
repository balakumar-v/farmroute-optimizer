"""
Tests for ilo_v3.py and the v3 options of run_our_system_v2. Synthetic data only; deterministic.
"""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import baselines_v3 as B
import ilo_v3 as V
from algorithms_v2 import run_our_system_v2
from logistics_lib_v2 import Farmer, Market, fresh_capacity, generate_scenario_v2, make_fleet


def _farmer(i, lat, lng, crop="potato", qty=300.0, ready=1.0, deadline=14.0):
    return Farmer(id=i, lat=lat, lng=lng, crop=crop, qty_kg=qty, ready_hr=ready, deadline_hr=deadline,
                  needs_refrigeration=False)


def _market(mid=0, price=15.0, lat=25.9, lng=85.2, cap=100000.0):
    return Market(id=mid, lat=lat, lng=lng, price={"potato": price}, capacity_kg={"potato": cap})


def _summ(res, farmers, markets, fleet, prices):
    return B.summarize_with_farmgate(res, farmers, markets, len(fleet), prices=prices)


@pytest.mark.parametrize("n,seed,d", [(30, 1, 0.15), (40, 2, 0.30), (30, 3, 0.05)])
def test_v3_never_below_any_baseline(n, seed, d):
    farmers, fleet, markets = generate_scenario_v2(n_farmers=n, n_markets=3, seed=seed)
    prices = B.FarmgatePrices(markets, d)
    res = V.run_ilo_v3(farmers, fleet, markets, prices=prices)
    v3 = _summ(res, farmers, markets, fleet, prices)["net_return_incl_farmgate"]
    mk = lambda: fresh_capacity(markets)  # noqa: E731
    base = [_summ(B.run_farmgate_baseline_v2(farmers, markets), farmers, markets, fleet, prices)]
    for beh in (None, B.DEFAULT_BEHAVIOUR):
        base.append(_summ(B.run_self_haul_v2(farmers, fleet, markets, mk(), prices=prices, behaviour=beh), farmers, markets, fleet, prices))
        base.append(_summ(B.run_neighbour_pooling_v2(farmers, fleet, markets, mk(), prices=prices, behaviour=beh), farmers, markets, fleet, prices))
    assert v3 >= max(b["net_return_incl_farmgate"] for b in base) - 1e-6


def test_every_farmer_exactly_once_and_fleet_untouched():
    farmers, fleet, markets = generate_scenario_v2(n_farmers=40, n_markets=3, seed=5)
    before = [(v.id, v.available_at_hr) for v in fleet]
    res = V.run_ilo_v3(farmers, fleet, markets, discount=0.2)
    assert sorted(i for r in res for i in r["farmer_ids"]) == sorted(f.id for f in farmers)
    assert [(v.id, v.available_at_hr) for v in fleet] == before


def test_no_dispatched_trip_earns_less_than_its_farmgate_value_and_gain_sharing_is_individually_rational():
    farmers, fleet, markets = generate_scenario_v2(n_farmers=60, n_markets=3, seed=7)
    prices = B.FarmgatePrices(markets, 0.20)
    by = {f.id: f for f in farmers}
    for r in V.run_ilo_v3(farmers, fleet, markets, prices=prices):
        if r["vehicle_id"] is None:
            continue
        members = [by[i] for i in r["farmer_ids"]]
        assert r["net_return"] >= prices.value_of(members) - 1e-6
        share = r["per_farmer_value_gain_sharing"]
        assert sum(share.values()) == pytest.approx(r["net_return"])
        assert all(share[f.id] >= prices.value(f) - 1e-6 for f in members)


def test_without_safeguard_or_set_partition_flags_change_what_is_returned():
    farmers, fleet, markets = generate_scenario_v2(n_farmers=30, n_markets=3, seed=1)
    _, meta = V.run_ilo_v3(farmers, fleet, markets, discount=0.15, set_partition=False, safeguard=False, return_meta=True)
    assert list(meta["plan_values"]) == ["A:ilo_pools"] and meta["chosen"] == "A:ilo_pools"
    _, meta2 = V.run_ilo_v3(farmers, fleet, markets, discount=0.15, return_meta=True)
    assert "B:set_partition" in meta2["plan_values"] and any(k.startswith("fallback:") for k in meta2["plan_values"])


def test_cw_routes_respect_capacity_and_time_windows():
    from algorithms_v2 import _simulate_end_time
    farmers = [_farmer(i, 25.55 + 0.01 * (i % 6), 84.80 + 0.01 * (i // 6), qty=400.0) for i in range(12)]
    m = _market(lat=25.95, lng=85.30)
    routes = list(V._cw_routes(farmers, m, qmax=1000.0))
    assert routes, "expected merges"
    for order in routes:
        assert sum(f.qty_kg for f in order) <= 1000.0 + 1e-9
        assert _simulate_end_time(order, True)[0]
        assert len({f.id for f in order}) == len(order)


def test_consolidation_beats_separate_long_hauls():
    # three separate villages ~25 km apart, mandi ~100 km away: one shared truck beats three trips
    farmers = [_farmer(0, 25.40, 84.60, qty=900.0), _farmer(1, 25.60, 84.60, qty=900.0), _farmer(2, 25.50, 84.82, qty=900.0)]
    markets = [_market(price=18.0, lat=26.40, lng=85.70)]
    fleet = make_fleet({"truck_5t": 3})
    prices = B.FarmgatePrices(markets, 0.30)
    cands, _ = V.generate_candidates(farmers, fleet, markets, prices, margin=0.0, consolidate=True)
    best_pooled = max((c for c in cands.values() if len(c["ids"]) == 3), key=lambda c: c["delta"], default=None)
    assert best_pooled is not None
    singles = [c["delta"] for c in cands.values() if len(c["ids"]) == 1]
    assert best_pooled["delta"] > sum(singles)


def test_set_partition_is_disjoint_and_respects_market_capacity():
    farmers, fleet, markets = generate_scenario_v2(n_farmers=80, n_markets=3, seed=4)
    prices = B.FarmgatePrices(markets, 0.30)
    cands, _ = V.generate_candidates(farmers, fleet, markets, prices, margin=0.0)
    chosen, status = V.solve_set_partition(cands, markets)
    assert status in ("optimal", "time_limit_best_found")
    ids = [i for c in chosen for i in c["ids"]]
    assert len(ids) == len(set(ids))
    used = {}
    for c in chosen:
        for crop, q in c["qty_by_crop"].items():
            used[(c["market"].id, crop)] = used.get((c["market"].id, crop), 0.0) + q
    cap = {m.id: m.capacity_kg for m in markets}
    assert all(q <= cap[mid][crop] + 1e-6 for (mid, crop), q in used.items())


def test_opportunity_cost_dispatch_holds_every_dispatched_pool_to_the_farmgate_hurdle():
    farmers, fleet, markets = generate_scenario_v2(n_farmers=60, n_markets=3, seed=9)
    prices = B.FarmgatePrices(markets, 0.20)
    by = {f.id: f for f in farmers}
    res = run_our_system_v2(farmers, copy.deepcopy(fleet), markets, farmgate_value_fn=lambda p: prices.value_of(p),
                            fix_route_duration=True, spoilage_from_pickup=True, charge_return_leg=True)
    for r in res:
        if r["vehicle_id"] is not None:
            assert r["net_return"] >= prices.value_of([by[i] for i in r["farmer_ids"]]) - 1e-6


def test_return_leg_flag_raises_transport_cost_and_defaults_leave_it_alone():
    f = [_farmer(0, 25.6, 84.9, qty=800.0)]
    mk = [_market(price=30.0, lat=25.8, lng=85.1)]
    fleet = make_fleet({"truck_2t": 1})
    base = run_our_system_v2(f, copy.deepcopy(fleet), mk, withhold_uneconomic=False)[0]
    same = run_our_system_v2(f, copy.deepcopy(fleet), mk, withhold_uneconomic=False, charge_return_leg=False)[0]
    ret = run_our_system_v2(f, copy.deepcopy(fleet), mk, withhold_uneconomic=False, charge_return_leg=True)[0]
    assert base == same and ret["transport_cost"] > base["transport_cost"]


def test_farmgate_price_input_changes_the_plan():
    farmers, fleet, markets = generate_scenario_v2(n_farmers=40, n_markets=3, seed=2)
    cheap = B.FarmgatePrices(markets, per_kg={c: 0.1 for c in {f.crop for f in farmers}})   # trader pays almost nothing
    rich = B.FarmgatePrices(markets, per_kg={c: 1000.0 for c in {f.crop for f in farmers}})  # trader pays more than any mandi
    hauled = lambda p: sum(r["vehicle_id"] is not None for r in V.run_ilo_v3(farmers, fleet, markets, prices=p, safeguard=False))  # noqa: E731
    assert hauled(cheap) > 0 and hauled(rich) == 0


def test_trace_aligns_with_final_pools_and_only_covers_dispatched_trips():
    farmers, fleet, markets = generate_scenario_v2(n_farmers=60, n_markets=3, seed=7)
    res, meta, trace = V.run_ilo_v3(farmers, fleet, markets, discount=0.20, return_meta=True, return_trace=True)
    if meta["chosen"].startswith("fallback:"):
        assert trace == {}
    for key in trace:
        assert res[int(key)]["vehicle_id"] is not None and trace[key]["crop_allocations"]
    sold = sum(max(0.0, r["total_qty_kg"] - r["unsold_kg"]) for r in res if r["vehicle_id"] is not None)
    traced = sum(e["kg"] for pt in trace.values() for edges in pt["crop_allocations"].values() for e in edges)
    if trace:
        assert traced == pytest.approx(sold, rel=1e-6, abs=1e-6)


def test_deliberately_unhauled_pools_are_flagged_as_farmgate_sales_not_failures():
    farmers, fleet, markets = generate_scenario_v2(n_farmers=60, n_markets=3, seed=7)
    res = V.run_ilo_v3(farmers, fleet, markets, prices=B.FarmgatePrices(markets, 0.05))   # hauling rarely pays
    for r in res:
        if r["vehicle_id"] is None and r.get("withheld"):
            assert r["sold_at_farmgate"] is True
        if r["vehicle_id"] is None and r["unserved_no_vehicle_kg"] > 0:
            assert not r.get("sold_at_farmgate")
