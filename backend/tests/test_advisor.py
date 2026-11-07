"""Fleet advisor (N4), doorstep quote check (N2) and impact counters (N3): read-only views over a stored plan."""
import copy
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import advisor
import ilo_v3 as V
from algorithms_v2 import summarize
from baselines_v3 import FARMGATE_DISCOUNT, run_farmgate_baseline_v2, summarize_with_farmgate
from logistics_lib_v2 import generate_scenario_v2
from visualization_adapter import ALGO_KEYS, build_plan_visualization


def _plan(seed=1, n=40, drop_vehicle=None):
    """A plan in the same JSON shape GET /plan/{id} returns (round-tripped through json like the database does).
    drop_vehicle removes one vehicle id from the fleet first (a breakdown), for re-plan diffs."""
    farmers, fleet, markets = generate_scenario_v2(n_farmers=n, n_markets=3, seed=seed)
    if drop_vehicle is not None:
        fleet = [v for v in fleet if v.id != drop_vehicle]
    res, meta = V.run_ilo_v3(farmers, copy.deepcopy(fleet), markets, return_meta=True)
    fs = len(fleet)
    snap = {
        "farmers": [f.__dict__ for f in farmers],
        "fleet": [{"id": v.id, "type_name": v.type_name, "capacity_kg": v.capacity_kg, "refrigerated": v.refrigerated,
                   "fixed_cost": v.fixed_cost, "per_km_cost": v.per_km_cost} for v in fleet],
        "markets": [{"id": m.id, "lat": m.lat, "lng": m.lng, "price": m.price, "capacity_kg": m.capacity_kg}
                    for m in markets],
    }
    fg = run_farmgate_baseline_v2(farmers, markets)
    plan = {
        "input_snapshot": snap,
        "integrated_logistics_optimization": {
            "pools": res, "summary": summarize_with_farmgate(res, farmers, markets, fs)},
        "realistic_baselines": {
            "assumptions": {"farmgate_discount": FARMGATE_DISCOUNT},
            "ilo_meta": meta,
            "farmgate_only": {"pools": fg, "summary": summarize_with_farmgate(fg, farmers, markets, fs)},
        },
    }
    return json.loads(json.dumps(plan))


@pytest.fixture(scope="module")
def plan():
    return _plan()


def _routes(plan):
    ilo = plan["integrated_logistics_optimization"]
    payload = build_plan_visualization(plan["input_snapshot"], {k: ilo for k in ALGO_KEYS})
    return payload["solutions"]["integrated_logistics_optimization"]["routes"]


def _solution(plan):
    ilo = plan["integrated_logistics_optimization"]
    payload = build_plan_visualization(plan["input_snapshot"], {k: ilo for k in ALGO_KEYS})
    return payload["solutions"]["integrated_logistics_optimization"]


def _hauled_ids(plan):
    return [fid for p in plan["integrated_logistics_optimization"]["pools"] if p["vehicle_id"] is not None
            for fid in p["farmer_ids"]]


# ---------------------------------------------------------------- N4
def test_fleet_advice_covers_the_whole_fleet_and_flags_the_best_class(plan):
    out = advisor.fleet_advice(plan["input_snapshot"], plan["integrated_logistics_optimization"],
                               plan["realistic_baselines"]["ilo_meta"])
    assert out["available"]
    assert sum(c["owned"] for c in out["classes"]) == len(plan["input_snapshot"]["fleet"])
    assert all(c["shadow_value_inr"] >= 0 for c in out["classes"])
    top = max(c["shadow_value_inr"] for c in out["classes"])
    assert (out["best_addition"] is None) == (top <= 1.0)
    if out["best_addition"]:
        assert next(c for c in out["classes"] if c["class"] == out["best_addition"])["shadow_value_inr"] == top


def test_fleet_advice_says_so_when_there_is_no_shadow_value(plan):
    out = advisor.fleet_advice(plan["input_snapshot"], plan["integrated_logistics_optimization"], {})
    assert out["available"] is False and out["reason"]


# ---------------------------------------------------------------- N2
def test_quote_check_flips_exactly_at_the_break_even_quote(plan):
    ids = _hauled_ids(plan)
    assert ids
    for fid in ids:
        be = advisor.quote_check(plan, fid, 1.0)["break_even_quote_per_kg"]
        assert advisor.quote_check(plan, fid, be * 0.99)["decision"] == "haul"
        assert advisor.quote_check(plan, fid, be * 1.01)["decision"] == "sell"


def test_every_hauled_farmer_beats_the_assumed_doorstep_price(plan):
    """The planner's no-loss guarantee, seen from the farmer's side: break-even >= the assumed doorstep price."""
    for fid in _hauled_ids(plan):
        q = advisor.quote_check(plan, fid, 1.0)
        assert q["break_even_quote_per_kg"] >= q["assumed_doorstep_per_kg"] - 1e-6


def test_quote_check_for_a_farmer_with_no_trip_and_bad_input(plan):
    pools = plan["integrated_logistics_optimization"]["pools"]
    nt = next(f for p in pools if p["vehicle_id"] is None for f in p["farmer_ids"])
    out = advisor.quote_check(plan, nt, 5.0)
    assert out["decision"] == "no_trip_planned" and out["status"] in ("farmgate", "unserved")
    with pytest.raises(KeyError):
        advisor.quote_check(plan, 10_000, 5.0)
    with pytest.raises(ValueError):
        advisor.quote_check(plan, nt, 0)


# ---------------------------------------------------------------- N3
def test_impact_numbers_are_consistent(plan):
    out = advisor.impact(plan, _routes(plan))
    assert out["kg_reaching_buyers"] <= out["kg_hauled_to_mandi"] + 1e-6
    assert out["gain_per_hauled_farmer_inr"]["min"] >= -1e-6                      # no farmer is worse off
    assert out["rupees_gained_vs_farmgate_only"] >= -1e-6                         # never worse than doing nothing
    assert out["trips_compared"] > 0
    assert out["km_saved_by_pooling"] >= -1e-6
    assert out["assumptions"]["diesel_kg_co2_per_litre"] == advisor.DIESEL_KG_CO2_PER_L


# ---------------------------------------------------------------- #5
def test_payouts_add_up_to_the_plan_value(plan):
    out = advisor.payout_statements(plan)
    assert out["total_inr"] == pytest.approx(out["plan_value_inr"], rel=1e-6)
    assert {s["status"] for s in out["statements"]} <= {"hauled", "farmgate", "unserved"}
    assert len(out["statements"]) == len(plan["input_snapshot"]["farmers"])


def test_no_farmer_is_paid_less_than_the_doorstep_value(plan):
    for s in advisor.payout_statements(plan)["statements"]:
        doorstep = next(l["value"] for l in s["lines"] if l["key"] == "doorstep_value")
        assert s["total_inr"] >= doorstep - 1e-6
        assert all(l["tag"] in ("exact", "derived", "assumed") for l in s["lines"])
        assert (s["trip"] is not None) == (s["status"] == "hauled")


# ---------------------------------------------------------------- N8
def test_diff_of_a_plan_with_itself_is_empty(plan):
    d = advisor.diff_plans(plan, plan)
    assert d["farmers_changed"] == 0 and d["farmers_unchanged"] == len(plan["input_snapshot"]["farmers"])


def test_diff_after_a_breakdown_lists_only_affected_farmers_with_reasons(plan):
    busiest = max((p for p in plan["integrated_logistics_optimization"]["pools"] if p["vehicle_id"] is not None),
                  key=lambda p: p["total_qty_kg"])["vehicle_id"]
    after = _plan(drop_vehicle=busiest)
    d = advisor.diff_plans(plan, after)
    n = len(plan["input_snapshot"]["farmers"])
    assert d["farmers_changed"] >= 1
    assert d["farmers_changed"] + d["farmers_unchanged"] == n
    assert all(c["why"] for c in d["changed"])
    on_broken = {f for p in plan["integrated_logistics_optimization"]["pools"] if p["vehicle_id"] == busiest
                 for f in p["farmer_ids"]}
    assert on_broken <= {c["farmer_id"] for c in d["changed"]}                    # everyone on that truck is told


# ---------------------------------------------------------------- #4
def test_driver_sheet_lists_every_trip_in_order_with_consistent_weights(plan):
    sol = _solution(plan)
    pools = plan["integrated_logistics_optimization"]["pools"]
    for vid in {p["vehicle_id"] for p in pools if p["vehicle_id"] is not None}:
        sheet = advisor.driver_sheet(plan, sol, vid)
        want = sorted(p["total_qty_kg"] for p in pools if p["vehicle_id"] == vid)
        assert sorted(t["total_kg"] for t in sheet["trips"]) == pytest.approx(want, abs=0.05)   # the adapter rounds pickups to 2 dp
        starts = [t["dispatch_hr"] for t in sheet["trips"]]
        assert starts == sorted(starts)
        for t in sheet["trips"]:
            kinds = [s["type"] for s in t["stops"]]
            n_pick = kinds.count("pickup")
            assert n_pick >= 1 and kinds == ["pickup"] * n_pick + ["dropoff"] * (len(kinds) - n_pick) and len(kinds) > n_pick
            etas = [s["eta_hr"] for s in t["stops"]]
            assert None not in etas and etas == sorted(etas) and etas[0] >= t["dispatch_hr"]
            picks = [s["kg"] for s in t["stops"] if s["type"] == "pickup"]
            drops = [s["kg"] for s in t["stops"] if s["type"] == "dropoff"]
            if len(drops) == 1:                      # one mandi: gets everything picked up. Several: kg per mandi is not recorded
                assert drops[0] == pytest.approx(sum(picks), abs=0.05)
            assert t["route_link"].startswith("https://www.google.com/maps/dir/")


def test_driver_sheet_rejects_a_vehicle_with_no_trips(plan):
    with pytest.raises(KeyError):
        advisor.driver_sheet(plan, _solution(plan), 99999)


# ---------------------------------------------------------------- the three endpoints, against a real Postgres
@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs DATABASE_URL (a Postgres)")
def test_endpoints_end_to_end():
    from collections import Counter
    from fastapi.testclient import TestClient
    import main
    farmers, fleet, markets = generate_scenario_v2(n_farmers=30, n_markets=3, seed=4)
    with TestClient(main.app) as c:
        c.post("/reset")
        for f in farmers:
            assert c.post("/farmers", json={k: getattr(f, k) for k in
                          ("lat", "lng", "crop", "qty_kg", "ready_hr", "deadline_hr")}).status_code == 200
        for t, n in Counter(v.type_name for v in fleet).items():
            assert c.post("/vehicles", json={"type_name": t, "count": n}).status_code == 200
        for m in markets:
            assert c.post("/markets", json={"lat": m.lat, "lng": m.lng, "price": m.price,
                                            "capacity_kg": m.capacity_kg}).status_code == 200
        pid = c.post("/plan/compute?road_distances=false").json()["id"]
        fa = c.get(f"/plan/{pid}/fleet-advice").json()
        assert fa["available"] and fa["classes"]
        imp = c.get(f"/plan/{pid}/impact").json()
        assert imp["kg_hauled_to_mandi"] > 0 and imp["co2_kg_saved_by_pooling"] >= -1e-6
        hauled = next(f for p in c.get(f"/plan/{pid}").json()["integrated_logistics_optimization"]["pools"]
                      if p["vehicle_id"] is not None for f in p["farmer_ids"])
        q = c.post(f"/plan/{pid}/quote-check", json={"farmer_id": hauled, "quote_per_kg": 0.5}).json()
        assert q["decision"] == "haul"
        assert c.post(f"/plan/{pid}/quote-check", json={"farmer_id": 99999, "quote_per_kg": 5}).status_code == 404
        assert c.post(f"/plan/{pid}/quote-check", json={"farmer_id": hauled, "quote_per_kg": -1}).status_code == 422
        assert c.get("/plan/99999/impact").status_code == 404
        pay = c.get(f"/plan/{pid}/payout").json()
        assert pay["total_inr"] == pytest.approx(pay["plan_value_inr"], rel=1e-6)
        assert c.get(f"/plan/{pid}/payout/{hauled}").json()["status"] == "hauled"
        assert c.get(f"/plan/{pid}/payout/99999").status_code == 404
        vid = next(p["vehicle_id"] for p in c.get(f"/plan/{pid}").json()["integrated_logistics_optimization"]["pools"]
                   if p["vehicle_id"] is not None)
        assert c.get(f"/plan/{pid}/driver-sheet/{vid}").json()["trips"]
        assert c.get(f"/plan/{pid}/driver-sheet/99999").status_code == 404
        pid2 = c.post("/plan/compute?road_distances=false").json()["id"]            # same inputs -> nothing changes
        assert c.get(f"/plan/{pid2}/diff/{pid}").json()["farmers_changed"] == 0
