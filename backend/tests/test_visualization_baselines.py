"""
The visualization adapter must handle the behavioural baselines: spot-hired vehicles (not in the FPO fleet) and
farmers who sell at the farm gate. Synthetic data only; no API or database needed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import baselines_v3 as B
from logistics_lib_v2 import fresh_capacity, generate_scenario_v2
from visualization_adapter import build_visualization_solution


def _snapshot(farmers, fleet, markets):
    return {"farmers": [f.__dict__ for f in farmers],
            "fleet": [{"id": v.id, "type_name": v.type_name, "capacity_kg": v.capacity_kg,
                       "refrigerated": v.refrigerated, "fixed_cost": v.fixed_cost, "per_km_cost": v.per_km_cost}
                      for v in fleet],
            "markets": [{"id": m.id, "lat": m.lat, "lng": m.lng, "price": m.price, "capacity_kg": m.capacity_kg}
                        for m in markets]}


def _solution(algo_key, runner):
    farmers, fleet, markets = generate_scenario_v2(n_farmers=60, n_markets=3, seed=11)
    res = runner(farmers, fleet, markets, fresh_capacity(markets))
    summary = B.summarize_with_farmgate(res, farmers, markets, len(fleet))
    sol = build_visualization_solution(algo_key, _snapshot(farmers, fleet, markets),
                                       {"pools": res, "summary": summary})
    return sol, res, farmers, fleet


def test_every_route_resolves_to_a_listed_vehicle_and_spot_ids_never_collide_with_the_fleet():
    for key, run in (("individual_transport", B.run_self_haul_v2), ("proximity_pooling", B.run_neighbour_pooling_v2)):
        sol, res, farmers, fleet = _solution(key, run)
        ids = [v["id"] for v in sol["vehicles"]]
        assert len(ids) == len(set(ids))
        assert all(r["vehicleId"] in set(ids) for r in sol["routes"])
        fleet_ids = {v.id for v in fleet}
        spot = [v for v in sol["vehicles"] if v.get("spotHire")]
        assert all(v["id"] not in fleet_ids and v["typeName"].startswith("Spot-hired") for v in spot)
        assert len(spot) == sum(1 for r in res if r.get("spot_hire"))
        assert all(e["vehicleId"] in set(ids) for e in sol["simulationEvents"])


def test_farmgate_sellers_are_not_reported_as_unserved():
    sol, res, farmers, _ = _solution("individual_transport", B.run_self_haul_v2)
    fg = {i for r in res if r.get("sold_at_farmgate") for i in r["farmer_ids"]}
    assert fg, "scenario should have farm-gate sellers"
    assert set(sol["farmgateFarmerIds"]) == fg
    assert not (set(sol["unservedFarmerIds"]) & fg)
    flagged = {f["id"] for f in sol["farmers"] if f["soldAtFarmGate"]}
    assert flagged == fg and all(not f["served"] for f in sol["farmers"] if f["soldAtFarmGate"])


def test_adapter_does_not_mutate_stored_pools():
    farmers, fleet, markets = generate_scenario_v2(n_farmers=60, n_markets=3, seed=11)
    res = B.run_self_haul_v2(farmers, fleet, markets, fresh_capacity(markets))
    before = [r["vehicle_id"] for r in res]
    build_visualization_solution("individual_transport", _snapshot(farmers, fleet, markets),
                                 {"pools": res, "summary": B.summarize_with_farmgate(res, farmers, markets, len(fleet))})
    assert [r["vehicle_id"] for r in res] == before
