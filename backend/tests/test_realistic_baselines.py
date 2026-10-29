"""
Tests for baselines_v3.py (farm-gate / self-haul / neighbour pooling, rational and behavioural tiers). Synthetic
data only (the project's own deterministic generator); no real-data or network access. Tests of the RATIONAL
tier pass behaviour=None explicitly; the default is the behavioural tier.
"""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import baselines_v3 as B
from algorithms_v2 import run_ilo_v2
from logistics_lib_v2 import Farmer, Market, fresh_capacity, generate_scenario_v2

CASES = [(30, 1), (100, 2), (300, 3)]


def _scn(n, seed):
    return generate_scenario_v2(n_farmers=n, n_markets=3, seed=seed)


def _farmer(i, lat, lng, crop="potato", qty=300.0, ready=1.0, deadline=12.0):
    return Farmer(id=i, lat=lat, lng=lng, crop=crop, qty_kg=qty, ready_hr=ready, deadline_hr=deadline,
                  needs_refrigeration=False)


def _market(price=10.0, lat=25.9, lng=85.2, cap=100000.0, crops=("potato", "onion")):
    return Market(id=0, lat=lat, lng=lng, price={c: price for c in crops}, capacity_kg={c: cap for c in crops})


@pytest.mark.parametrize("n,seed", CASES)
@pytest.mark.parametrize("algo", ["self_haul", "neighbour"])
def test_every_farmer_appears_exactly_once(n, seed, algo):
    farmers, fleet, markets = _scn(n, seed)
    run = B.run_self_haul_v2 if algo == "self_haul" else B.run_neighbour_pooling_v2
    res = run(farmers, fleet, markets, fresh_capacity(markets), behaviour=None)
    ids = sorted(i for r in res for i in r["farmer_ids"])
    assert ids == sorted(f.id for f in farmers)


@pytest.mark.parametrize("n,seed", CASES)
def test_never_worse_than_farmgate_by_decision_rule(n, seed):
    """Every hired trip was chosen because its EXPECTED value beat the farm gate; realised value can still
    fall short only through market crowding (unsold), so allow it only when something went unsold."""
    farmers, fleet, markets = _scn(n, seed)
    ref = B.reference_prices(markets)
    by = {f.id: f for f in farmers}
    for run in (B.run_self_haul_v2, B.run_neighbour_pooling_v2):
        for r in run(farmers, fleet, markets, fresh_capacity(markets), behaviour=None):
            if r["vehicle_id"] is None:
                continue
            fg = sum(B.farmgate_value(by[i], ref) for i in r["farmer_ids"])
            assert r["net_return"] >= fg - 1e-6 or r["unsold_kg"] > 0


def test_spot_hires_use_negative_ids_and_never_touch_the_fpo_fleet():
    farmers, fleet, markets = _scn(100, 2)
    before = [(v.id, v.available_at_hr) for v in fleet]
    res = B.run_neighbour_pooling_v2(farmers, fleet, markets, fresh_capacity(markets), behaviour=None)
    assert [(v.id, v.available_at_hr) for v in fleet] == before
    assert all(r["vehicle_id"] is None or r["vehicle_id"] < 0 for r in res)
    s = B.summarize_with_farmgate(res, farmers, markets, len(fleet))
    assert s["fpo_vehicles_used"] == 0 and s["vehicle_utilization_pct"] == 0
    assert s["vehicles_used"] == s["spot_trips"] == sum(r["vehicle_id"] is not None for r in res)


def test_farmgate_only_pays_the_discounted_reference_price():
    farmers = [_farmer(0, 25.6, 84.9, qty=400.0)]
    markets = [_market(price=10.0)]
    res = B.run_farmgate_baseline_v2(farmers, markets)
    s = B.summarize_with_farmgate(res, farmers, markets, fleet_size=1, discount=0.25)
    assert s["net_return"] == 0 and s["farmgate_revenue"] == pytest.approx(400 * 10 * 0.75)


def test_far_mandi_means_farmgate_near_mandi_means_haul():
    f = [_farmer(0, 25.6, 84.9, qty=1000.0)]
    far = [_market(price=10.0, lat=27.5, lng=86.9)]
    near = [_market(price=10.0, lat=25.65, lng=84.95)]
    assert B.run_self_haul_v2(f, [], far, fresh_capacity(far), behaviour=None)[0]["vehicle_id"] is None
    assert B.run_self_haul_v2(f, [], near, fresh_capacity(near), behaviour=None)[0]["vehicle_id"] is not None


def test_return_leg_is_charged_unless_matching_ilo_accounting():
    f = [_farmer(0, 25.6, 84.9, qty=1000.0)]
    m = [_market(price=30.0, lat=25.8, lng=85.1)]
    realistic = B.run_self_haul_v2(f, [], m, fresh_capacity(m), behaviour=None)[0]
    like_ilo = B.run_self_haul_v2(f, [], m, fresh_capacity(m), match_ilo_accounting=True, behaviour=None)[0]
    assert realistic["transport_cost"] > like_ilo["transport_cost"]
    assert realistic["route_distance_km"] == pytest.approx(2 * like_ilo["route_distance_km"])


def test_neighbour_groups_respect_radius_size_and_time_windows():
    # 3 farmers ~1 km apart, 1 far away, 1 nearby but ready too late to share a window
    fs = [_farmer(0, 25.600, 84.900), _farmer(1, 25.605, 84.903), _farmer(2, 25.602, 84.907),
          _farmer(3, 26.500, 85.900), _farmer(4, 25.601, 84.901, ready=20.0, deadline=30.0)]
    groups = B._neighbour_groups(fs, radius_km=5.0, max_group=4)
    sets = sorted(sorted(f.id for f in g) for g in groups)
    assert sets == [[0, 1, 2], [3], [4]]
    assert all(len(g) <= 4 for g in groups)
    capped = B._neighbour_groups(fs, radius_km=5.0, max_group=2)
    assert max(len(g) for g in capped) == 2


def test_market_capacity_is_shared_and_leftover_is_unsold():
    farmers = [_farmer(i, 25.600 + 0.001 * i, 84.900, qty=500.0, ready=1.0 + 0.01 * i) for i in range(3)]
    m = [_market(price=30.0, lat=25.62, lng=84.92, cap=800.0)]
    res = B.run_self_haul_v2(farmers, [], m, fresh_capacity(m), behaviour=None)
    assert sum(r["unsold_kg"] for r in res) == pytest.approx(1500 - 800)


def test_mixed_crop_group_splits_when_no_single_mandi_buys_both():
    fs = [_farmer(0, 25.600, 84.900, crop="potato"), _farmer(1, 25.601, 84.901, crop="onion")]
    ms = [Market(id=0, lat=25.62, lng=84.92, price={"potato": 15.0}, capacity_kg={"potato": 1e5}),
          Market(id=1, lat=25.63, lng=84.93, price={"onion": 15.0}, capacity_kg={"onion": 1e5})]
    res = B.run_neighbour_pooling_v2(fs, [], ms, fresh_capacity(ms), behaviour=None)
    assert all(len(r["farmer_ids"]) == 1 for r in res)
    assert {r["markets_used"][0] for r in res if r["vehicle_id"] is not None} <= {0, 1}


def test_summary_values_fallback_for_ilo_too_and_is_deterministic():
    farmers, fleet, markets = _scn(100, 2)
    a = B.summarize_with_farmgate(run_ilo_v2(farmers, copy.deepcopy(fleet), markets), farmers, markets, len(fleet))
    b = B.summarize_with_farmgate(run_ilo_v2(farmers, copy.deepcopy(fleet), markets), farmers, markets, len(fleet))
    assert a == b
    assert a["net_return_incl_farmgate"] == pytest.approx(a["net_return"] + a["farmgate_revenue"])
    assert a["farmgate_kg"] >= a["total_withheld_kg"] + a["total_unserved_no_vehicle_kg"] - 1e-6


# ----------------------------------------------------------------------
# Behavioural tier
# ----------------------------------------------------------------------
def test_behavioural_does_not_haul_beyond_max_haul_km():
    f = [_farmer(0, 25.6, 84.9, qty=1000.0)]
    far = [_market(price=100.0, lat=26.5, lng=85.8)]            # ~130 km, absurdly high price
    res = B.run_self_haul_v2(f, [], far, fresh_capacity(far))
    assert res[0]["vehicle_id"] is None


def test_behavioural_needs_a_clear_price_advantage():
    f = [_farmer(0, 25.60, 84.90, qty=1000.0)]
    m_low = [_market(price=10.0, lat=25.65, lng=84.95)]         # trader offers 0.8 * 10 = 8; 10 < 8 * 1.10 is false...
    # ...so make the mandi barely above the trader's offer: price 8.5 < 1.10 * 8.0 -> stays home
    m_low[0].price = {"potato": 8.5, "onion": 8.5}
    prices = B.FarmgatePrices([_market(price=10.0)], discount=0.20)   # reference 10 -> offer 8.0
    assert B.run_self_haul_v2(f, [], m_low, fresh_capacity(m_low), prices=prices)[0]["vehicle_id"] is None
    m_hi = [_market(price=12.0, lat=25.65, lng=84.95)]
    assert B.run_self_haul_v2(f, [], m_hi, fresh_capacity(m_hi), prices=prices)[0]["vehicle_id"] is not None


def test_behavioural_farmers_haul_at_a_loss_where_rational_ones_would_not():
    # tiny lot, mandi 35 km away with a clearly higher price: the rule says go, the arithmetic says do not
    f = [_farmer(0, 25.60, 84.90, qty=100.0)]
    m = [_market(price=12.0, lat=25.91, lng=84.90)]
    prices = B.FarmgatePrices([_market(price=10.0)], discount=0.20)
    beh = B.run_self_haul_v2(f, [], m, fresh_capacity(m), prices=prices)[0]
    rat = B.run_self_haul_v2(f, [], m, fresh_capacity(m), prices=prices, behaviour=None)[0]
    assert beh["vehicle_id"] is not None and beh["net_return"] < B.farmgate_value(f[0], {"potato": 10.0})
    assert rat["vehicle_id"] is None


def test_behavioural_spot_hire_costs_the_markup():
    f = [_farmer(0, 25.60, 84.90, qty=1000.0)]
    m = [_market(price=30.0, lat=25.70, lng=85.00)]
    beh = B.run_self_haul_v2(f, [], m, fresh_capacity(m))[0]
    rat = B.run_self_haul_v2(f, [], m, fresh_capacity(m), behaviour=None)[0]
    assert beh["transport_cost"] == pytest.approx(B.DEFAULT_BEHAVIOUR.spot_markup * rat["transport_cost"])


def test_behavioural_group_waits_for_last_member_and_early_deadline_misses_out():
    early = _farmer(0, 25.600, 84.900, qty=400.0, ready=1.0, deadline=3.0)
    late = _farmer(1, 25.601, 84.901, qty=400.0, ready=10.0, deadline=24.0)
    m = [_market(price=40.0, lat=25.65, lng=84.95)]
    res = B.run_neighbour_pooling_v2([early, late], [], m, fresh_capacity(m))
    hauled = [r for r in res if r["vehicle_id"] is not None]
    gate = [r for r in res if r["vehicle_id"] is None]
    assert [r["farmer_ids"] for r in hauled] == [[1]] and [r["farmer_ids"] for r in gate] == [[0]]


def test_behavioural_groups_ignore_time_windows_but_rational_groups_do_not():
    fs = [_farmer(0, 25.600, 84.900, ready=1.0, deadline=3.0), _farmer(1, 25.601, 84.901, ready=10.0, deadline=24.0)]
    assert len(B._neighbour_groups(fs, check_windows=False)) == 1
    assert len(B._neighbour_groups(fs, check_windows=True)) == 2


def test_farmgate_prices_resolution_order():
    mk = [_market(price=10.0)]
    f = _farmer(0, 25.6, 84.9, qty=100.0)
    assert B.FarmgatePrices(mk, 0.2).per_kg(f) == pytest.approx(8.0)
    assert B.FarmgatePrices(mk, 0.2, per_kg={"potato": 6.5}).per_kg(f) == pytest.approx(6.5)
    assert B.FarmgatePrices(mk, 0.2, per_kg={"potato": 6.5}, price_fn=lambda x: 5.0).per_kg(f) == pytest.approx(5.0)


def test_farmgate_pools_are_flagged_so_the_ui_never_shows_them_as_unserved():
    farmers = [_farmer(0, 25.6, 84.9, qty=400.0)]
    m = [_market(price=10.0, lat=27.5, lng=86.9)]                # far away: behavioural farmer stays home
    r = B.run_self_haul_v2(farmers, [], m, fresh_capacity(m))[0]
    assert r["vehicle_id"] is None and r.get("sold_at_farmgate") is True
    assert B.run_farmgate_baseline_v2(farmers, m)[0]["sold_at_farmgate"] is True


def test_hired_trips_carry_a_vehicle_spec_for_the_visualization_adapter():
    farmers = [_farmer(0, 25.60, 84.90, qty=1000.0)]
    m = [_market(price=30.0, lat=25.70, lng=85.00)]
    r = B.run_self_haul_v2(farmers, [], m, fresh_capacity(m))[0]
    spec = r["vehicle_spec"]
    assert r["spot_hire"] is True and r["vehicle_id"] < 0
    assert spec["capacity_kg"] >= 1000.0 and spec["refrigerated"] is False and spec["fixed_cost"] > 0
