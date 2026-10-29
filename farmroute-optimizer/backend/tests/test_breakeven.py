"""Per-trip break-even doorstep price and discount stress-testing of a finished ILO plan."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ilo_v3 as V
from baselines_v3 import FarmgatePrices
from logistics_lib_v2 import generate_scenario_v2


def _plan(seed=1, n=60):
    farmers, fleet, markets = generate_scenario_v2(n_farmers=n, n_markets=3, seed=seed)
    res, meta = V.run_ilo_v3(farmers, copy.deepcopy(fleet), markets, return_meta=True)
    return farmers, markets, res, meta


def test_break_even_is_the_price_at_which_the_trip_is_neutral():
    farmers, markets, res, _ = _plan()
    prices = FarmgatePrices(markets)
    by = {f.id: f for f in farmers}
    trips = [r for r in res if r["vehicle_id"] is not None]
    assert trips
    for r in trips:
        be = r["breakeven"]
        members = [by[i] for i in r["farmer_ids"]]
        assert be["price_scale"] >= 1.0 - 1e-9                                   # repaired plans beat the farm gate
        # scale the assumed doorstep price by lambda*: farm-gate value == the trip's net return
        assert be["price_scale"] * prices.value_of(members) == pytest.approx(r["net_return"])
        # same statement through the discount: at d* the doorstep value equals the trip's net return
        assert FarmgatePrices(markets, discount=be["breakeven_discount"]).value_of(members) == pytest.approx(
            r["net_return"])


def test_stress_is_monotone_and_the_quote_rule_never_hurts():
    farmers, markets, res, meta = _plan(seed=2)
    st = meta["discount_stress"]
    ds = sorted(st)
    for lo, hi in zip(ds, ds[1:]):                                                # bigger discount -> bigger gain
        assert st[lo]["gain_dispatch_all"] <= st[hi]["gain_dispatch_all"] + 1e-6
    for d in ds:
        assert st[d]["gain_with_quote_rule"] >= st[d]["gain_dispatch_all"] - 1e-6
        assert st[d]["gain_with_quote_rule"] >= -1e-6
    assert st[0.20]["trips_losing"] == 0                                          # the assumed discount: repaired plan
    assert st[0.20]["gain_dispatch_all"] == pytest.approx(st[0.20]["gain_with_quote_rule"])


def test_stress_can_be_switched_off():
    farmers, fleet, markets = generate_scenario_v2(n_farmers=30, n_markets=3, seed=3)
    _, meta = V.run_ilo_v3(farmers, copy.deepcopy(fleet), markets, return_meta=True, stress_discounts=None)
    assert "discount_stress" not in meta
