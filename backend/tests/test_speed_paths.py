"""The planner's speed-ups must not change its answers: the allocation cache hands out independent copies and agrees with
a fresh solve, the single-pool shortcut equals the LP it replaces, and a whole plan is the same with the cache off."""
import copy
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import algorithms_v2 as A
import ilo_v3 as V
from logistics_lib_v2 import generate_scenario_v2


def _infos(fleet, markets, crop, rng, n):
    out = []
    for _ in range(n):
        m = rng.choice(markets)
        out.append({"total_qty": rng.choice([0.0, 40.0, 300.0, 900.0, 2500.0]),
                    "last_point": (m.lat + rng.uniform(-0.3, 0.3), m.lng + rng.uniform(-0.3, 0.3)),
                    "first_point": (m.lat + rng.uniform(-0.3, 0.3), m.lng + rng.uniform(-0.3, 0.3)),
                    "t_after_pickup": rng.uniform(0.2, 5.0), "vehicle": rng.choice(fleet)})
    return out


def _same(a, b):
    assert len(a) == len(b)
    for x, y in zip(a, b):
        assert x["revenue"] == pytest.approx(y["revenue"], rel=1e-9, abs=1e-9)
        assert x["spoil_loss_kg"] == pytest.approx(y["spoil_loss_kg"], rel=1e-9, abs=1e-9)
        assert x["unsold_kg"] == pytest.approx(y["unsold_kg"], rel=1e-9, abs=1e-9)
        assert x["market_dist"].keys() == y["market_dist"].keys()
        assert [(e["market_id"], e["price"]) for e in x["edges"]] == [(e["market_id"], e["price"]) for e in y["edges"]]
        assert [e["kg"] for e in x["edges"]] == pytest.approx([e["kg"] for e in y["edges"]], rel=1e-9, abs=1e-9)


@pytest.fixture
def world():
    _, fleet, markets = generate_scenario_v2(n_farmers=30, n_markets=4, seed=3)
    A._ALLOC_CACHE.clear()
    return fleet, markets, sorted({c for m in markets for c in m.price})


def test_a_single_pool_shortcut_equals_the_lp_it_replaces(world):
    fleet, markets, crops = world
    rng = random.Random(7)
    for _ in range(60):
        crop, elastic = rng.choice(crops), rng.choice([False, True])
        one = _infos(fleet, markets, crop, rng, 1)
        # the same pool next to a pool of 0 kg goes through the LP (2 pools) and must give the same answer for pool 0
        padded = one + [{**one[0], "total_qty": 0.0}]
        got = A.allocate_markets_lp(one, crop, markets, elastic_pricing=elastic)
        ref = A.allocate_markets_lp(padded, crop, markets, elastic_pricing=elastic)[:1]
        _same(got, ref)


def test_the_cache_agrees_with_a_fresh_solve_for_many_pools(world, monkeypatch):
    fleet, markets, crops = world
    rng = random.Random(11)
    cases = [(rng.choice(crops), _infos(fleet, markets, rng.choice(crops), rng, rng.randint(1, 5)), rng.choice([False, True]))
             for _ in range(40)]
    for crop, infos, rl in cases:
        monkeypatch.setenv("ALLOC_CACHE_MAX", "0")
        fresh = A.allocate_markets_lp(infos, crop, markets, return_leg=rl)
        monkeypatch.setenv("ALLOC_CACHE_MAX", "4000")
        _same(A.allocate_markets_lp(infos, crop, markets, return_leg=rl), fresh)      # miss, stored
        _same(A.allocate_markets_lp(infos, crop, markets, return_leg=rl), fresh)      # hit


def test_a_cached_answer_cannot_be_changed_by_the_caller(world):
    fleet, markets, crops = world
    infos = _infos(fleet, markets, crops[0], random.Random(5), 3)
    infos = [{**p, "total_qty": 800.0} for p in infos]
    first = A.allocate_markets_lp(infos, crops[0], markets)
    snap = copy.deepcopy(first)
    for r in first:                                   # what the planner does to the dicts it gets back
        r["crop"] = "x"; r["edges"].append({"market_id": -1, "price": 0, "kg": 1, "dist_km": 0}); r["market_dist"][-1] = 0
    _same(A.allocate_markets_lp(infos, crops[0], markets), snap)


def test_different_prices_or_pools_do_not_share_a_cache_entry(world):
    fleet, markets, crops = world
    crop = crops[0]
    infos = [{**p, "total_qty": 500.0} for p in _infos(fleet, markets, crop, random.Random(2), 2)]
    a = A.allocate_markets_lp(infos, crop, markets)
    markets[0].price[crop] = markets[0].price.get(crop, 10.0) * 3          # one market's price moves
    b = A.allocate_markets_lp(infos, crop, markets)
    assert [r["revenue"] for r in a] != [r["revenue"] for r in b]
    more = [{**infos[0], "total_qty": 1500.0}, infos[1]]
    assert A.allocate_markets_lp(more, crop, markets)[0]["revenue"] != b[0]["revenue"]


def test_the_cache_is_bounded(world, monkeypatch):
    fleet, markets, crops = world
    monkeypatch.setenv("ALLOC_CACHE_MAX", "5")
    rng = random.Random(1)
    for _ in range(40):
        A.allocate_markets_lp(_infos(fleet, markets, crops[0], rng, 2), crops[0], markets)
    assert len(A._ALLOC_CACHE) <= 5


def test_a_whole_plan_is_the_same_with_the_cache_off(monkeypatch):
    farmers, fleet, markets = generate_scenario_v2(n_farmers=30, n_markets=3, seed=3)

    def run():
        res, meta = V.run_ilo_v3(farmers, copy.deepcopy(fleet), markets, return_meta=True)
        return [(r["vehicle_id"], tuple(r["farmer_ids"]), round(r["net_return"], 6)) for r in res], round(meta["final_value"], 6)

    monkeypatch.setenv("ALLOC_CACHE_MAX", "0")
    off = run()
    monkeypatch.setenv("ALLOC_CACHE_MAX", "4000"); A._ALLOC_CACHE.clear()
    assert run() == off


def test_the_set_partition_time_limit_defaults_low_and_can_be_raised(monkeypatch):
    assert V.SP_TIME_LIMIT_S == 5.0 and V.SP_MIP_GAP == 1e-4
    monkeypatch.setenv("ILO_SP_TIME_LIMIT", "30")
    assert V._env_f("ILO_SP_TIME_LIMIT", V.SP_TIME_LIMIT_S) == 30.0
