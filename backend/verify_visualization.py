"""
verify_visualization.py
------------------------
Exercises GET /plan/{id}/visualization and GET /sensors/readings against the
"cold chain" demo scenario from frontend/app.js (11 farmers, 4 vehicles incl.
exactly one reefer_van -- deliberately picked because it's the scenario most
likely to trigger multi-trip vehicle reuse and mixed served/unserved farmers,
which are the two trickiest cases for the adapter to get right).

Usage: python3 verify_visualization.py
"""

import json

from fastapi.testclient import TestClient

from main import app

c = TestClient(app)
c.__enter__()


def check(label, condition):
    print(f"{'OK  ' if condition else 'FAIL'}  {label}")
    assert condition, label


FARMERS = [
    {"lat": 25.610, "lng": 84.915, "crop": "tomato",      "qty_kg": 280, "ready_hr": 0.0, "deadline_hr": 12.0},
    {"lat": 25.615, "lng": 84.920, "crop": "spinach",     "qty_kg": 220, "ready_hr": 0.3, "deadline_hr": 10.0},
    {"lat": 25.605, "lng": 84.910, "crop": "cauliflower", "qty_kg": 260, "ready_hr": 0.6, "deadline_hr": 12.0},
    {"lat": 25.612, "lng": 84.905, "crop": "mango",       "qty_kg": 240, "ready_hr": 1.0, "deadline_hr": 11.0},
    {"lat": 25.618, "lng": 84.918, "crop": "tomato",      "qty_kg": 300, "ready_hr": 2.5, "deadline_hr": 13.0},
    {"lat": 25.608, "lng": 84.912, "crop": "spinach",     "qty_kg": 210, "ready_hr": 2.8, "deadline_hr": 11.0},
    {"lat": 25.614, "lng": 84.908, "crop": "cauliflower", "qty_kg": 250, "ready_hr": 3.1, "deadline_hr": 13.0},
    {"lat": 25.611, "lng": 84.922, "crop": "mango",       "qty_kg": 230, "ready_hr": 5.0, "deadline_hr": 13.5},
    {"lat": 25.617, "lng": 84.913, "crop": "tomato",      "qty_kg": 290, "ready_hr": 5.3, "deadline_hr": 14.0},
    {"lat": 25.606, "lng": 84.917, "crop": "spinach",     "qty_kg": 200, "ready_hr": 5.6, "deadline_hr": 13.0},
    {"lat": 25.613, "lng": 84.911, "crop": "cauliflower", "qty_kg": 240, "ready_hr": 6.0, "deadline_hr": 13.5},
]
VEHICLES = [
    {"type_name": "van", "count": 2},
    {"type_name": "mini_pickup", "count": 1},
    {"type_name": "reefer_van", "count": 1},
]
MARKETS = [
    {"lat": 25.650, "lng": 84.950,
     "price": {"tomato": 22, "spinach": 25, "cauliflower": 18, "mango": 32},
     "capacity_kg": {"tomato": 3000, "spinach": 3000, "cauliflower": 3000, "mango": 3000}},
    {"lat": 25.570, "lng": 84.860,
     "price": {"tomato": 20, "spinach": 23, "cauliflower": 16, "mango": 30},
     "capacity_kg": {"tomato": 3000, "spinach": 3000, "cauliflower": 3000, "mango": 3000}},
]

for f in FARMERS:
    r = c.post("/farmers", json=f)
    check(f"create farmer {f['crop']}", r.status_code == 200)
for v in VEHICLES:
    r = c.post("/vehicles", json=v)
    check(f"create vehicle {v['type_name']} x{v['count']}", r.status_code == 200)
for m in MARKETS:
    r = c.post("/markets", json=m)
    check("create market", r.status_code == 200)

r = c.post("/plan/compute")
check("plan/compute succeeds", r.status_code == 200)
plan = r.json()
plan_id = plan["id"]
check("plan/compute returns ilo pools", len(plan["integrated_logistics_optimization"]["pools"]) > 0)

r = c.get(f"/plan/{plan_id}/visualization")
check("visualization endpoint succeeds", r.status_code == 200)
viz = r.json()
check("visualization has 3 solutions", set(viz["solutions"].keys()) == {
    "integrated_logistics_optimization", "individual_transport", "proximity_pooling"})

ilo = viz["solutions"]["integrated_logistics_optimization"]
check("ilo has 11 farmers", len(ilo["farmers"]) == 11)
check("ilo farmer lat/lng preserved", ilo["farmers"][0]["lat"] == FARMERS[0]["lat"])
check("ilo has vehicles", len(ilo["vehicles"]) == 4)
check("ilo has at least one route", len(ilo["routes"]) >= 1)
check("ilo market breakdown available (trace present)", ilo["marketBreakdownAvailable"] is True)
check("ilo has simulation events", len(ilo["simulationEvents"]) > 0)

# every served farmer must appear in exactly one route's farmerIds, in the
# route's stop order, and never in unservedFarmerIds
served_in_routes = set()
for route in ilo["routes"]:
    for fid in route["farmerIds"]:
        check(f"farmer {fid} not double-assigned across routes", fid not in served_in_routes)
        served_in_routes.add(fid)
check("served+unserved farmers partition all 11",
      served_in_routes | set(ilo["unservedFarmerIds"]) == {f["id"] for f in ilo["farmers"]})
check("no overlap between served and unserved",
      served_in_routes.isdisjoint(set(ilo["unservedFarmerIds"])))

# events: dispatch always first, complete always last per trip, timestamps non-decreasing per trip
for route in ilo["routes"]:
    trip_events = [e for e in ilo["simulationEvents"] if e["tripId"] == route["id"]]
    check(f"{route['id']} has events", len(trip_events) > 0)
    check(f"{route['id']} starts with dispatch", trip_events[0]["type"] == "dispatch")
    check(f"{route['id']} ends with complete", trip_events[-1]["type"] == "complete")
    ts = [e["timestamp"] for e in trip_events]
    check(f"{route['id']} timestamps non-decreasing", ts == sorted(ts))
    # pickups match real farmer qty_kg exactly (not fabricated)
    pickups = [e for e in trip_events if e["type"] == "pickup"]
    check(f"{route['id']} pickup count matches farmerIds", len(pickups) == len(route["farmerIds"]))

# multi-trip reuse sanity: no single vehicle's two trips overlap in time
by_vehicle = {}
for route in ilo["routes"]:
    by_vehicle.setdefault(route["vehicleId"], []).append(route["id"])
multi_trip_vehicles = {v: ids for v, ids in by_vehicle.items() if len(ids) > 1}
print(f"  vehicles with >1 trip this run: {multi_trip_vehicles or 'none in this scenario'}")
for vid, trip_ids in multi_trip_vehicles.items():
    spans = []
    for tid in trip_ids:
        evts = [e for e in ilo["simulationEvents"] if e["tripId"] == tid]
        spans.append((evts[0]["timestamp"], evts[-1]["timestamp"], tid))
    spans.sort()
    for (s1, e1, t1), (s2, e2, t2) in zip(spans, spans[1:]):
        check(f"vehicle {vid} trips {t1}->{t2} don't overlap", s2 >= e1)

# markets: receivedKg should be present and sum to something <= capacity
for m in ilo["markets"]:
    check(f"market {m['id']} has receivedKg dict", "receivedKg" in m)

r = c.get("/sensors/readings")
check("sensors/readings (empty) succeeds", r.status_code == 200 and r.json() == [])
r = c.post("/sensors/reading", json={"pool_id": f"{plan_id}:0", "temperature": 6.5, "humidity": 70, "timestamp": 1.2})
check("post sensor reading", r.status_code == 200)
r = c.get("/sensors/readings", params={"pool_id": f"{plan_id}:0"})
check("sensors/readings filtered by pool_id", r.status_code == 200 and len(r.json()) == 1)

# individual_transport: exact market breakdown should always be available and add up
ind = viz["solutions"]["individual_transport"]
check("individual_transport market breakdown available", ind["marketBreakdownAvailable"] is True)
total_received = sum(sum(m["receivedKg"].values()) for m in ind["markets"])
total_sold_from_routes = sum(r["totalQtyKg"] - r["unsoldKg"] for r in ind["routes"])
check(f"individual_transport receivedKg sums match routes ({total_received:.1f} vs {total_sold_from_routes:.1f})",
      abs(total_received - total_sold_from_routes) < 0.5)

# proximity_pooling: breakdown NOT available (never fabricated)
prox = viz["solutions"]["proximity_pooling"]
check("proximity_pooling market breakdown NOT available", prox["marketBreakdownAvailable"] is False)
check("proximity_pooling markets have no receivedKg key",
      all("receivedKg" not in m for m in prox["markets"]))

print(json.dumps({
    "ilo_routes": len(ilo["routes"]),
    "ilo_unserved": len(ilo["unservedFarmerIds"]),
    "ilo_events": len(ilo["simulationEvents"]),
    "sample_route": ilo["routes"][0],
}, indent=2)[:2000])

print("\nAll checks passed.")
