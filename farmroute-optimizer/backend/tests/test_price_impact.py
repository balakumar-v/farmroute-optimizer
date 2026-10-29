"""Volume-dependent mandi prices: the model, its use in the set-partitioning MILP, the LP nodes and the baselines."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import baselines_v3 as B
import ilo_v3 as V
from logistics_lib_v2 import Market, fresh_capacity, generate_scenario_v2, market_demand_nodes
from price_impact import PriceImpact, estimate_price_flexibility


def _mkt(price=20.0, cap=4000.0):
    return Market(id=0, lat=25.9, lng=85.2, price={"tomato": price}, capacity_kg={"tomato": cap})


def test_tranches_cover_capacity_with_decreasing_slopes_and_match_revenue():
    m = _mkt()
    for scale in (0.5, 1.0, 3.5):
        pi = PriceImpact(scale=scale)
        tr = pi.tranches(m, "tomato")
        assert sum(w for _a, w, _s in tr) == pytest.approx(4000.0)
        assert all(tr[i][2] >= tr[i + 1][2] for i in range(len(tr) - 1))
        assert sum(w * s for _a, w, s in tr) == pytest.approx(pi.revenue(m, "tomato", 4000.0))
        assert tr[0][2] <= 20.0 + 1e-9


def test_zero_scale_is_the_fixed_price_model():
    m = _mkt()
    pi = PriceImpact(scale=0.0)
    assert pi.revenue(m, "tomato", 3000.0) == pytest.approx(20.0 * 3000.0)


def test_demand_nodes_from_price_impact_keep_total_capacity():
    ms = [_mkt()]
    nodes = market_demand_nodes(ms, "tomato", PriceImpact())
    assert sum(n["capacity_kg"] for n in nodes) == pytest.approx(4000.0)
    assert [n["price"] for n in nodes] == sorted((n["price"] for n in nodes), reverse=True)


def test_set_partition_sends_less_volume_when_prices_respond():
    farmers, fleet, markets = generate_scenario_v2(n_farmers=60, n_markets=3, seed=1)
    prices = B._as_prices(markets, B.FARMGATE_DISCOUNT, None)
    cands, _ = V.generate_candidates(farmers, fleet, markets, prices, 0.0)
    free, _ = V.solve_set_partition(cands, markets)
    hit, _ = V.solve_set_partition(cands, markets, PriceImpact(scale=10.0))
    q = lambda trips: sum(sum(c["qty_by_crop"].values()) for c in trips)                      # noqa: E731
    assert q(hit) <= q(free) + 1e-6
    assert len(hit) <= len(free)


def test_baseline_revenue_falls_when_prices_respond():
    farmers, fleet, markets = generate_scenario_v2(n_farmers=60, n_markets=3, seed=2)
    rev = lambda res: sum(r["revenue"] for r in res)                                           # noqa: E731
    flat = B.run_neighbour_pooling_v2(farmers, fleet, markets, fresh_capacity(markets))
    hit = B.run_neighbour_pooling_v2(farmers, fleet, markets, fresh_capacity(markets),
                                     price_impact=PriceImpact(scale=10.0))
    assert rev(hit) < rev(flat)
    zero = B.run_neighbour_pooling_v2(farmers, fleet, markets, fresh_capacity(markets),
                                      price_impact=PriceImpact(scale=0.0))
    assert rev(zero) == pytest.approx(rev(flat))


def test_estimator_recovers_a_planted_slope(tmp_path):
    import numpy as np
    import pandas as pd
    rng = np.random.default_rng(0)
    rows = []
    for mk in range(8):
        base_a, base_p = rng.uniform(5, 30), rng.uniform(1000, 3000)
        for day in range(60):
            a = base_a * np.exp(rng.normal(0, 0.4))
            p = base_p * (a / base_a) ** -0.2 * np.exp(rng.normal(0, 0.03))
            rows.append(dict(crop="tomato", arrival_date=f"2026-01-{day % 28 + 1:02d}-{day // 28}", market_name=f"m{mk}",
                             model_price=p, unit_name_price="Rs./Quintal", arrival_qty=a,
                             unit_name_arrival="Metric Tonnes"))
    pd.DataFrame(rows).to_csv(tmp_path / "x.csv", index=False)
    out = estimate_price_flexibility([tmp_path / "x.csv"])
    assert out["tomato"]["eta"] == pytest.approx(0.2, abs=0.04)


# ---------------------------------------------------------------------------
# Soft capacity: the cap becomes a price instead of a wall
# ---------------------------------------------------------------------------
def test_soft_capacity_extends_tranches_beyond_a_normal_day_with_decreasing_slopes():
    m = _mkt()
    hard, soft = PriceImpact(), PriceImpact.soft(3.0)
    assert hard.capacity_multiple == 1.0 and soft.capacity_multiple == 3.0
    tr = soft.tranches(m, "tomato")
    assert sum(w for _a, w, _s in tr) == pytest.approx(3.0 * 4000.0)
    assert all(tr[i][2] >= tr[i + 1][2] for i in range(len(tr) - 1))
    assert PriceImpact(capacity_multiple=1.0).tranches(m, "tomato") == hard.tranches(m, "tomato")   # M=1 is the old model
    # same price curve inside the first day's capacity
    assert soft.revenue(m, "tomato", 4000.0) == pytest.approx(hard.revenue(m, "tomato", 4000.0))
    assert soft.revenue(m, "tomato", 8000.0) > soft.revenue(m, "tomato", 4000.0)                   # still increasing


def test_soft_capacity_never_lowers_the_set_partition_objective():
    farmers, fleet, markets = generate_scenario_v2(n_farmers=150, n_markets=3, seed=1)               # capacity binds here
    prices = B._as_prices(markets, B.FARMGATE_DISCOUNT, None)
    res = {}
    for name, pi in (("hard", PriceImpact(scale=3.5)), ("soft", PriceImpact.soft(3.0, scale=3.5))):
        cands, _ = V.generate_candidates(farmers, fleet, markets, prices, 0.0, cap_mult=pi.capacity_multiple,
                                         markets_per_trip=3)
        chosen, _ = V.solve_set_partition(cands, markets, pi)
        fixed = sum(c["delta"] - c["rev"] for c in chosen)
        by_key = {}
        for c in chosen:
            for crop, q in c["qeff_by_crop"].items():
                by_key[(c["market"].id, crop)] = by_key.get((c["market"].id, crop), 0.0) + q
        mk = {m.id: m for m in markets}
        res[name] = (fixed + sum(pi.revenue(mk[k[0]], k[1], q) for k, q in by_key.items()),
                     sum(sum(c["qty_by_crop"].values()) for c in chosen))
    assert res["soft"][0] >= res["hard"][0] - 1e-6          # more options at a falling price can only help
    assert res["soft"][1] >= res["hard"][1] - 1e-6          # and it hauls at least as much


def test_run_ilo_v3_scores_baselines_in_the_same_soft_capacity_world():
    farmers, fleet, markets = generate_scenario_v2(n_farmers=150, n_markets=3, seed=1)               # capacity binds here
    best = {}
    for name, truth in (("hard", PriceImpact(scale=3.5)), ("soft", PriceImpact.soft(3.0, scale=3.5))):
        _, meta = V.run_ilo_v3(farmers, copy.deepcopy(fleet), markets, return_meta=True, true_price_impact=truth)
        assert meta["params"]["capacity_multiple_belief"] == 1.0 and meta["params"]["true_price_impact"] is True
        best[name] = max(v for k, v in meta["plan_values"].items() if k.startswith("fallback"))
    assert best["soft"] >= best["hard"] - 1e-6              # baselines may also sell past a normal day, at falling prices


def test_multi_market_candidates_offer_one_trip_at_several_mandis_and_default_is_unchanged():
    farmers, fleet, markets = generate_scenario_v2(n_farmers=60, n_markets=4, seed=1)
    prices = B._as_prices(markets, B.FARMGATE_DISCOUNT, None)
    one, _ = V.generate_candidates(farmers, fleet, markets, prices, 0.0)
    assert all(isinstance(k, frozenset) for k in one)                       # legacy: one best mandi per trip
    many, _ = V.generate_candidates(farmers, fleet, markets, prices, 0.0, markets_per_trip=3)
    assert all(isinstance(k, tuple) for k in many)
    per_trip = {}
    for (ids, mid) in many:
        per_trip.setdefault(ids, set()).add(mid)
    assert max(len(v) for v in per_trip.values()) <= 3 and max(len(v) for v in per_trip.values()) >= 2
    assert set(per_trip) >= set(one)                                         # every legacy trip is still offered
