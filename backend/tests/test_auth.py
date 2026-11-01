"""Roles and farmer isolation: admin token, farmer PIN login, publishing, and 'a farmer can only ever see their own card'."""
import os
import sys
import time
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import advisor
import auth
from test_advisor import _plan, _solution
from logistics_lib_v2 import generate_scenario_v2

ADMIN = {"Authorization": "Bearer admin-secret"}


# ---------------------------------------------------------------- pure: hashing and tokens (no database)
def test_pin_hash_is_salted_and_verifies():
    h1, h2 = auth.hash_pin("123456"), auth.hash_pin("123456")
    assert h1 != h2 and "123456" not in h1
    assert auth.verify_pin("123456", h1) and not auth.verify_pin("123457", h1)
    assert not auth.verify_pin("123456", "garbage")


def test_generated_pins_are_six_digits():
    pins = {auth.generate_pin() for _ in range(200)}
    assert all(len(p) == 6 and p.isdigit() for p in pins) and len(pins) > 150


def test_token_roundtrip_tamper_and_expiry():
    h = auth.hash_pin("111111")
    tok = auth.make_token(7, h)
    assert auth.parse_token(tok)["f"] == 7
    body, sig = tok.rsplit(".", 1)
    assert auth.parse_token(body + "." + "0" * len(sig)) is None                       # bad signature
    other = auth.make_token(8, h).split(".")[0]
    assert auth.parse_token(other + "." + sig) is None                                  # body swapped, same sig
    assert auth.parse_token(auth.make_token(7, h, ttl_s=-1)) is None                    # expired
    assert auth.parse_token("not a token") is None


def test_farmer_cards_hold_only_the_farmers_own_facts():
    plan = _plan()
    sol = _solution(plan)
    cards = advisor.farmer_cards(plan, sol, "now")
    assert set(cards) == {f["id"] for f in plan["input_snapshot"]["farmers"]}
    for fid, c in cards.items():
        assert c["farmer_id"] == fid
        assert "per_farmer_net" not in str(c) and "farmer_ids" not in str(c)
        assert (c["trip"] is not None) == (c["status"] == "hauled")
        assert (c["break_even_per_kg"] is not None) == (c["status"] == "hauled") and c["doorstep_per_kg"] > 0
        if c["status"] == "hauled":
            assert c["break_even_per_kg"] >= c["doorstep_per_kg"] - 1e-6
        if c["trip"]:
            assert set(c["trip"]) >= {"pickup_eta", "vehicle_type", "mandis", "farmers_on_trip"}
            assert "revenue" not in str(c["trip"]) and "cost" not in str(c["trip"])


def test_cards_say_what_changed_after_a_replan():
    before = _plan()
    busiest = max((p for p in before["integrated_logistics_optimization"]["pools"] if p["vehicle_id"] is not None),
                  key=lambda p: p["total_qty_kg"])
    after = _plan(drop_vehicle=busiest["vehicle_id"])
    cards = advisor.farmer_cards(after, _solution(after), "now", previous_plan=before)
    told = {fid for fid, c in cards.items() if c["changed"]}
    assert set(busiest["farmer_ids"]) <= told
    assert all(c["changed"] is None for c in advisor.farmer_cards(after, _solution(after), "now").values())


# ---------------------------------------------------------------- API, against a real Postgres
pytestmark_db = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs DATABASE_URL (a Postgres)")


@pytest.fixture(scope="module")
def api():
    from fastapi.testclient import TestClient
    import main
    os.environ["ADMIN_TOKEN"] = "admin-secret"
    os.environ["FARMROUTE_SECRET"] = "test-signing-secret"
    farmers, fleet, markets = generate_scenario_v2(n_farmers=24, n_markets=3, seed=5)
    with TestClient(main.app) as c:
        c.headers.update(ADMIN)
        c.post("/reset")
        for f in farmers:
            c.post("/farmers", json={k: getattr(f, k) for k in ("lat", "lng", "crop", "qty_kg", "ready_hr", "deadline_hr")})
        for t, n in Counter(v.type_name for v in fleet).items():
            c.post("/vehicles", json={"type_name": t, "count": n})
        for m in markets:
            c.post("/markets", json={"lat": m.lat, "lng": m.lng, "price": m.price, "capacity_kg": m.capacity_kg})
        c.plan_id = c.post("/plan/compute?road_distances=false").json()["id"]
        yield c
    os.environ.pop("ADMIN_TOKEN", None)
    os.environ.pop("FARMROUTE_SECRET", None)


def _anon(api):
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app)


def _login(api, fid, pin):
    return _anon(api).post("/farmer/login", json={"farmer_id": fid, "pin": pin})


def _bearer(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytestmark_db
def test_admin_routes_need_the_admin_token_but_farmer_routes_and_docs_do_not(api):
    anon = _anon(api)
    assert anon.get("/farmers").status_code == 401
    assert anon.post("/reset").status_code == 401
    assert anon.get("/plan/1", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert anon.get("/farmers", headers=ADMIN).status_code == 200
    assert anon.get("/openapi.json").status_code == 200
    assert anon.post("/farmer/login", json={"farmer_id": 1, "pin": "123456"}).status_code == 401   # reachable


@pytestmark_db
def test_login_publish_and_each_farmer_sees_only_their_own_card(api):
    issued = api.post("/farmers/pins").json()
    assert issued["issued"] == 24
    pins = {p["farmer_id"]: p["pin"] for p in issued["pins"]}
    assert api.post("/farmers/pins").json()["issued"] == 0                                   # only missing by default

    anon = _anon(api)
    a, b = sorted(pins)[:2]
    ta = _login(api, a, pins[a]).json()["token"]
    tb = _login(api, b, pins[b]).json()["token"]
    assert anon.get("/farmer/me", headers=_bearer(ta)).status_code == 404                    # nothing published yet

    pub = api.post(f"/plan/{api.plan_id}/publish").json()
    assert pub["farmers"] == 24 and pub["farmers_without_pin"] == [] and pub["previous_plan_id"] is None

    ca = anon.get("/farmer/me", headers=_bearer(ta)).json()
    cb = anon.get("/farmer/me", headers=_bearer(tb)).json()
    assert ca["farmer_id"] == a and cb["farmer_id"] == b and ca != cb
    assert str(b) not in {str(k) for k in ca} and "farmer_ids" not in str(ca)
    # no way to ask for someone else's card: an id in the query string or path is ignored / unknown
    assert anon.get(f"/farmer/me?farmer_id={b}", headers=_bearer(ta)).json()["farmer_id"] == a
    assert anon.get(f"/farmer/{b}", headers=_bearer(ta)).status_code in (404, 405)
    # a farmer's token opens nothing on the admin side
    for path in ("/farmers", f"/plan/{api.plan_id}", f"/plan/{api.plan_id}/payout", "/published"):
        assert anon.get(path, headers=_bearer(ta)).status_code == 401, path
    assert anon.post("/reset", headers=_bearer(ta)).status_code == 401
    # and the admin token is not a farmer token
    assert anon.get("/farmer/me", headers=ADMIN).status_code == 401


@pytestmark_db
def test_forged_and_expired_tokens_are_rejected(api):
    pin = api.post("/farmers/1/pin").json()["pin"]
    anon = _anon(api)
    good = _login(api, 1, pin).json()["token"]
    assert anon.get("/farmer/me", headers=_bearer(good)).status_code in (200, 404)
    body, sig = good.rsplit(".", 1)
    forged = auth.make_token(2, "x" * 20)                                                    # right key, wrong pin fingerprint
    assert anon.get("/farmer/me", headers=_bearer(forged)).status_code == 401
    assert anon.get("/farmer/me", headers=_bearer(body + ".00")).status_code == 401
    assert anon.get("/farmer/me").status_code == 401
    from database import get_conn
    with get_conn() as conn:
        h = conn.execute("SELECT pin_hash FROM farmer_credentials WHERE farmer_id = 1").fetchone()["pin_hash"]
    assert anon.get("/farmer/me", headers=_bearer(auth.make_token(1, h, ttl_s=-5))).status_code == 401


@pytestmark_db
def test_five_wrong_pins_lock_the_farmer_and_a_new_pin_unlocks_and_logs_out_old_sessions(api):
    pin = api.post("/farmers/3/pin").json()["pin"]
    old = _login(api, 3, pin).json()["token"]
    wrong = "000000" if pin != "000000" else "111111"
    codes = [_login(api, 3, wrong).status_code for _ in range(5)]
    assert codes == [401, 401, 401, 401, 429]
    locked = _login(api, 3, pin)                                                             # even the right PIN waits
    assert locked.status_code == 429 and int(locked.headers["Retry-After"]) > 0
    new = api.post("/farmers/3/pin").json()["pin"]
    assert _login(api, 3, new).status_code == 200
    assert _anon(api).get("/farmer/me", headers=_bearer(old)).status_code == 401           # old session is dead


@pytestmark_db
def test_bad_logins_look_alike_and_pins_are_not_stored_in_clear(api):
    pin = api.post("/farmers/4/pin").json()["pin"]
    unknown = _login(api, 99999, "123456")
    wrong = _login(api, 4, "000000" if pin != "000000" else "111111")
    assert unknown.status_code == wrong.status_code == 401 and unknown.json() == wrong.json()
    assert _login(api, 4, "12ab56").status_code == 422
    from database import get_conn
    with get_conn() as conn:
        stored = conn.execute("SELECT pin_hash FROM farmer_credentials WHERE farmer_id = 4").fetchone()["pin_hash"]
    assert pin not in stored and stored.startswith("scrypt$")
    r = api.post("/farmers/4/pin")
    assert r.headers["Cache-Control"] == "no-store"
    assert api.post("/farmers/99999/pin").status_code == 404


@pytestmark_db
def test_unpublish_hides_everything_and_republish_records_the_previous_plan(api):
    pin = api.post("/farmers/5/pin").json()["pin"]
    tok = _login(api, 5, pin).json()["token"]
    api.post(f"/plan/{api.plan_id}/publish")
    assert api.get("/published").json()["published"] is True
    assert api.delete("/published").json() == {"published": False}
    assert _anon(api).get("/farmer/me", headers=_bearer(tok)).status_code == 404
    second = api.post("/plan/compute?road_distances=false").json()["id"]
    api.post(f"/plan/{api.plan_id}/publish")
    out = api.post(f"/plan/{second}/publish").json()
    assert out["previous_plan_id"] == api.plan_id


def test_farmer_routes_refuse_to_work_when_admin_routes_are_open(monkeypatch):
    from fastapi.testclient import TestClient
    import main
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    c = TestClient(main.app)
    assert c.post("/farmer/login", json={"farmer_id": 1, "pin": "123456"}).status_code == 503
    assert c.get("/farmer/me").status_code == 503
