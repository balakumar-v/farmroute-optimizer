"""Rescue of pools that got no truck: idle-fleet pass, spot-hire pass, reasons, invariants, fleet_usage."""
import copy
from dataclasses import asdict, is_dataclass

import pytest

import advisor
import ilo_v3 as V
from logistics_lib_v2 import generate_scenario_v2


@pytest.fixture(scope="module")
def scen():
    return generate_scenario_v2(n_farmers=120, n_markets=4, seed=2)


def _run(scen, **kw):
    fa, fl, mk = scen
    return V.run_ilo_v3(fa, copy.deepcopy(fl), mk, return_meta=True, return_trace=True, **kw)


def _unserved_kg(res):
    return sum(r.get("unserved_no_vehicle_kg", 0) for r in res)


def test_rescue_reduces_unserved(scen):
    off = _run(scen, rescue_unserved=False, spot_fallback=False)[0]
    on = _run(scen)[0]
    assert _unserved_kg(on) < _unserved_kg(off)


def test_each_farmer_exactly_once(scen):
    res = _run(scen)[0]
    ids = [i for r in res for i in r["farmer_ids"]]
    assert sorted(ids) == sorted(f.id for f in scen[0])


def test_flags_off_restores_old_behaviour(scen):
    res, meta, _ = _run(scen, rescue_unserved=False, spot_fallback=False)
    assert not meta.get("rescue", {}).get("changed")
    assert not any(r.get("spot_hire") for r in res)


def test_spot_pools_carry_spec_and_trace(scen):
    res, meta, trace = _run(scen)
    spot = [r for r in res if r.get("spot_hire")]
    assert spot and all(r["vehicle_spec"]["capacity_kg"] > 0 and r["vehicle_id"] < 0 for r in spot)
    hauled = [i for i, r in enumerate(res) if r["vehicle_id"] is not None]
    assert all(str(i) in trace for i in hauled)


def test_unserved_pools_have_reason(scen):
    res = _run(scen)[0]
    left = [r for r in res if r["vehicle_id"] is None and r.get("unserved_no_vehicle_kg", 0) > 0]
    assert all(r.get("no_truck_reason") for r in left)


def test_fleet_usage(scen):
    fa, fl, _ = scen
    res = _run(scen)[0]
    d = lambda o: asdict(o) if is_dataclass(o) else o
    plan = {"input_snapshot": {"fleet": [d(v) for v in fl], "farmers": [d(f) for f in fa]},
            "integrated_logistics_optimization": {"pools": res}}
    u = advisor.fleet_usage(plan)
    assert u["fleet_size"] == len(fl) and 0 <= u["dispatched"] <= u["fleet_size"]
    assert u["dispatched"] + u["idle"] == u["fleet_size"]
    assert 0 < u["avg_load_pct"] <= 100
    assert u["spot_trips"] == sum(1 for r in res if r.get("spot_hire"))
    assert abs(u["unserved_kg"] - sum(x["kg"] for x in u["unserved"])) < 1e-6
    assert all(x["reason"] for x in u["unserved"])
