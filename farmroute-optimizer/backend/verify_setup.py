"""
verify_setup.py
----------------
Sanity-checks the running setup by exercising every endpoint with a
FastAPI TestClient (no server needs to be running separately).

Exercises CRUD for farmers/vehicles/markets, sensor readings,
/plan/compute (checked for real, summaries printed), /plan/{id}, and
/reset.

Usage:  python3 verify_setup.py
"""

from fastapi.testclient import TestClient

from main import app

c = TestClient(app)
c.__enter__()  # trigger the startup event (init_db)


def check(label, condition):
    print(f"{'OK  ' if condition else 'FAIL'}  {label}")
    assert condition, label


# --- farmers ---
r = c.post("/farmers", json={
    "lat": 25.6, "lng": 84.9, "crop": "tomato", "qty_kg": 300,
    "ready_hr": 1.0, "deadline_hr": 8.0,
})
check("create farmer", r.status_code == 200)

r = c.post("/farmers", json={
    "lat": 25.61, "lng": 84.91, "crop": "potato", "qty_kg": 500,
    "ready_hr": 0.5, "deadline_hr": 10.0,
})
check("create farmer 2", r.status_code == 200)

r = c.get("/farmers")
check("list farmers", r.status_code == 200 and len(r.json()) >= 2)

# --- vehicles ---
r = c.post("/vehicles", json={"type_name": "reefer_2t", "count": 2})
check("create vehicles", r.status_code == 200 and len(r.json()) == 2)

r = c.get("/vehicles")
check("list vehicles", r.status_code == 200 and len(r.json()) >= 2)

# --- markets ---
r = c.post("/markets", json={
    "lat": 25.7, "lng": 85.0,
    "price": {"tomato": 20.0, "potato": 10.0},
    "capacity_kg": {"tomato": 5000, "potato": 5000},
})
check("create market", r.status_code == 200)

r = c.get("/markets")
check("list markets", r.status_code == 200 and len(r.json()) >= 1)

# --- sensors ---
r = c.post("/sensors/reading", json={
    "pool_id": "demo-pool-1", "temperature": 6.5, "humidity": 80.0, "timestamp": 1.25,
})
check("post sensor reading", r.status_code == 200)

# --- plan/compute ---
r = c.post("/plan/compute")
check("plan/compute succeeds", r.status_code == 200)
if r.status_code == 200:
    data = r.json()
    check("plan/compute returns all three algorithms",
          set(["integrated_logistics_optimization", "individual_transport", "proximity_pooling"]) <= set(data))
    for key in ("integrated_logistics_optimization", "individual_transport", "proximity_pooling"):
        s = data[key]["summary"]
        check(f"{key} summary has pct_qty_served", "pct_qty_served" in s)
        print(f"  {key}: net_return={s.get('net_return')}, pct_qty_served={s.get('pct_qty_served')}")

    r2 = c.get(f"/plan/{data['id']}")
    check("fetch stored plan run", r2.status_code == 200)
else:
    print("  detail:", r.json().get("detail"))

# --- reset ---
r = c.post("/reset")
check("reset succeeds", r.status_code == 200)
check("reset clears farmers", r.status_code == 200 and r.json()["cleared"]["farmers"] >= 2)
r = c.get("/farmers")
check("farmers empty after reset", r.status_code == 200 and r.json() == [])

print("\nAll checks passed.")
