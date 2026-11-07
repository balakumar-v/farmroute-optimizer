"""Phone numbers and SMS / WhatsApp updates: number parsing, codes, message text, providers (no network), who gets
messaged on publish, and the API (against a real Postgres, like test_auth.py)."""
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import notify
from logistics_lib_v2 import generate_scenario_v2

ADMIN = {"Authorization": "Bearer admin-secret"}


# ---------------------------------------------------------------- pure: numbers
@pytest.mark.parametrize("raw", ["98765 43210", "+91 98765-43210", "09876543210", "919876543210", "0091 98765 43210", "(98765) 43210"])
def test_indian_numbers_normalise_to_e164(raw):
    assert notify.normalize_phone(raw) == "+919876543210"


def test_international_numbers_are_kept_and_junk_is_refused():
    assert notify.normalize_phone("+1 415 555 0123") == "+14155550123"
    for bad in ["", "1234", "5876543210", "98765x3210", "+0123456789", "+12", "98765432101234"]:
        with pytest.raises(ValueError):
            notify.normalize_phone(bad)


def test_masking_never_shows_the_middle():
    m = notify.mask_phone("+919876543210")
    assert m == "+91******3210" and "98765" not in m


# ---------------------------------------------------------------- pure: codes
def test_otp_digest_is_bound_to_farmer_number_and_key():
    k = b"key"
    d = notify.otp_digest(1, "+919876543210", "123456", k)
    assert d == notify.otp_digest(1, "+919876543210", "123456", k)
    assert d != notify.otp_digest(2, "+919876543210", "123456", k)
    assert d != notify.otp_digest(1, "+919876543211", "123456", k)
    assert d != notify.otp_digest(1, "+919876543210", "123457", k)
    assert d != notify.otp_digest(1, "+919876543210", "123456", b"other")
    assert "123456" not in d
    codes = {notify.new_otp() for _ in range(200)}
    assert all(len(c) == 6 and c.isdigit() for c in codes) and len(codes) > 150


# ---------------------------------------------------------------- pure: message text
def _card(status="hauled", **kw):
    c = {"farmer_id": 7, "crop": "tomato", "qty_kg": 1250.0, "status": status, "changed": None,
         "trip": {"pickup_eta": "13:05", "mandis": [{"id": 3}]} if status == "hauled" else None,
         "payout": {"total_inr": 48231.4}, "doorstep_per_kg": 21.4}
    c.update(kw)
    return c


@pytest.mark.parametrize("lang", notify.LANGS)
@pytest.mark.parametrize("status", ["hauled", "farmgate", "unserved"])
@pytest.mark.parametrize("kind", ["update", "changed", "welcome"])
def test_every_language_status_and_kind_makes_one_clean_line(lang, status, kind):
    msg = notify.compose_plan_message(_card(status), lang, kind)
    assert msg.startswith("Farmroute: ")
    assert "{" not in msg and "}" not in msg and "\n" not in msg and "None" not in msg
    assert "48,230" in msg and len(msg) < 400
    if status == "hauled":
        assert "1:05 PM" in msg and "1250" in msg
    if kind != "update":                     # the extra sentence sits after the brand tag
        assert msg != notify.compose_plan_message(_card(status), lang, "update")


def test_message_uses_only_the_farmers_own_facts_and_the_right_language():
    msg = notify.compose_plan_message(_card(crop="onion"), "ta")
    assert "வெங்காயம்" in msg and "onion" not in msg
    assert notify.compose_plan_message(_card(), "xx") == notify.compose_plan_message(_card(), "en")     # unknown -> English
    assert "PIN" not in msg
    assert notify.compose_otp_message("654321", "hi").startswith("654321")


def test_rupees_are_rounded_like_the_app_reads_them_aloud_and_grouped_the_indian_way():
    assert notify._about(48231.4) == "48,230" and notify._about(412) == "410" and notify._about(87) == "87"
    assert notify._indian(1234567) == "12,34,567"


# ---------------------------------------------------------------- pure: providers (network replaced)
class _Fake:
    def __init__(self, status=200, body="ok"):
        self.calls, self.status, self.body = [], status, body

    def __call__(self, url, headers, data, timeout=10.0):
        self.calls.append((url, headers, data))
        return self.status, self.body


def test_default_providers_are_dry_and_never_touch_the_network(monkeypatch):
    fake = _Fake()
    monkeypatch.setattr(notify, "_http", fake)
    for ch in ("sms", "whatsapp"):
        p = notify.get_provider(ch, {})
        assert p.name == "dry" and not p.live
        assert p.send("+919876543210", "hi")[0] is True
    assert fake.calls == []
    assert notify.describe_providers({}) == {"sms": {"provider": "dry", "live": False, "problem": None},
                                              "whatsapp": {"provider": "dry", "live": False, "problem": None}}


def test_missing_credentials_or_unknown_provider_fail_clearly_not_at_startup():
    p = notify.get_provider("sms", {"SMS_PROVIDER": "twilio", "TWILIO_ACCOUNT_SID": "AC1"})
    ok, why = p.send("+919876543210", "x")
    assert not ok and "TWILIO_AUTH_TOKEN" in why and "TWILIO_SMS_FROM" in why
    ok, why = notify.get_provider("whatsapp", {"WHATSAPP_PROVIDER": "carrier-pigeon"}).send("+919876543210", "x")
    assert not ok and "unknown provider" in why and "meta" in why


def test_twilio_sms_and_whatsapp_requests(monkeypatch):
    fake = _Fake()
    monkeypatch.setattr(notify, "_http", fake)
    env = {"SMS_PROVIDER": "twilio", "WHATSAPP_PROVIDER": "twilio", "TWILIO_ACCOUNT_SID": "ACx", "TWILIO_AUTH_TOKEN": "tok",
           "TWILIO_SMS_FROM": "+15005550006", "TWILIO_WHATSAPP_FROM": "+14155238886"}
    assert notify.get_provider("sms", env).send("+919876543210", "hello")[0]
    assert notify.get_provider("whatsapp", env).send("+919876543210", "hello")[0]
    (u1, h1, d1), (u2, h2, d2) = fake.calls
    assert u1 == u2 == "https://api.twilio.com/2010-04-01/Accounts/ACx/Messages.json"
    assert h1["Authorization"].startswith("Basic ")
    assert "To=%2B919876543210" in d1.decode() and "From=%2B15005550006" in d1.decode()
    assert "To=whatsapp%3A%2B919876543210" in d2.decode() and "From=whatsapp%3A%2B14155238886" in d2.decode()


def test_meta_whatsapp_uses_a_template_in_the_farmers_language(monkeypatch):
    fake = _Fake()
    monkeypatch.setattr(notify, "_http", fake)
    p = notify.get_provider("whatsapp", {"WHATSAPP_PROVIDER": "meta", "WHATSAPP_TOKEN": "t", "WHATSAPP_PHONE_ID": "123"})
    assert p.send("+919876543210", "line one", "ta")[0]
    url, headers, data = fake.calls[0]
    body = json.loads(data)
    assert url == "https://graph.facebook.com/v20.0/123/messages" and headers["Authorization"] == "Bearer t"
    assert body["to"] == "919876543210" and body["type"] == "template"
    assert body["template"]["language"]["code"] == "ta"
    assert body["template"]["components"][0]["parameters"][0]["text"] == "line one"


def test_msg91_picks_the_otp_or_update_template(monkeypatch):
    fake = _Fake()
    monkeypatch.setattr(notify, "_http", fake)
    p = notify.get_provider("sms", {"SMS_PROVIDER": "msg91", "MSG91_AUTH_KEY": "k", "MSG91_OTP_TEMPLATE_ID": "otp1",
                                    "MSG91_UPDATE_TEMPLATE_ID": "upd1"})
    p.send("+919876543210", "code", "en", "otp")
    p.send("+919876543210", "plan", "en", "changed")
    assert [json.loads(c[2])["template_id"] for c in fake.calls] == ["otp1", "upd1"]
    assert json.loads(fake.calls[0][2])["recipients"][0] == {"mobiles": "919876543210", "VAR1": "code"}


def test_provider_errors_come_back_as_a_reason_not_an_exception(monkeypatch):
    monkeypatch.setattr(notify, "_http", _Fake(401, '{"error":{"code":190,"message":"bad token"}}'))
    p = notify.get_provider("whatsapp", {"WHATSAPP_PROVIDER": "meta", "WHATSAPP_TOKEN": "t", "WHATSAPP_PHONE_ID": "1"})
    ok, why = p.send("+919876543210", "x")
    assert not ok and "meta 401" in why and "bad token" in why


def test_otp_channels_configuration():
    assert notify.otp_channels({}) == ["sms", "whatsapp"]
    assert notify.otp_channels({"OTP_CHANNEL": "both"}) == ["sms", "whatsapp"]
    assert notify.otp_channels({"OTP_CHANNEL": "sms"}) == ["sms"]
    assert notify.otp_channels({"OTP_CHANNEL": "whatsapp"}) == ["whatsapp"]
    assert notify.otp_channels({"OTP_CHANNEL": "wa"}) == ["whatsapp"]


def test_meta_whatsapp_otp_authentication_template_and_copy_code_button(monkeypatch):
    fake = _Fake()
    monkeypatch.setattr(notify, "_http", fake)
    env = {
        "WHATSAPP_PROVIDER": "meta",
        "WHATSAPP_TOKEN": "meta-tok",
        "WHATSAPP_PHONE_ID": "98765",
        "WHATSAPP_OTP_TEMPLATE": "farmroute_otp",
        "WHATSAPP_OTP_BUTTON": "copy_code",
    }
    p = notify.get_provider("whatsapp", env)
    otp_msg = notify.compose_otp_message("123456", "en")
    ok, detail = p.send("+919876543210", otp_msg, "en", "otp")
    assert ok
    url, headers, data = fake.calls[0]
    assert url == "https://graph.facebook.com/v20.0/98765/messages"
    body = json.loads(data)
    assert body["template"]["name"] == "farmroute_otp"
    assert body["template"]["language"]["code"] == "en"
    # Parameter is the 6-digit code, not the full message sentence
    assert body["template"]["components"][0]["parameters"][0]["text"] == "123456"
    # Copy code button parameter is also the 6-digit code
    assert body["template"]["components"][1]["parameters"][0]["text"] == "123456"
    assert body["template"]["components"][1]["sub_type"] == "url"

    # Button turned off
    fake.calls.clear()
    env["WHATSAPP_OTP_BUTTON"] = "off"
    p2 = notify.get_provider("whatsapp", env)
    p2.send("+919876543210", otp_msg, "en", "otp")
    body2 = json.loads(fake.calls[0][2])
    assert len(body2["template"]["components"]) == 1
    assert body2["template"]["components"][0]["type"] == "body"

    # hello_world template for connectivity test
    fake.calls.clear()
    env_hw = {"WHATSAPP_PROVIDER": "meta", "WHATSAPP_TOKEN": "meta-tok", "WHATSAPP_PHONE_ID": "98765",
              "WHATSAPP_TEMPLATE": "hello_world"}
    p_hw = notify.get_provider("whatsapp", env_hw)
    p_hw.send("+919876543210", "hello", "ta", "update")
    body_hw = json.loads(fake.calls[0][2])
    assert body_hw["template"]["name"] == "hello_world"
    assert body_hw["template"]["language"]["code"] == "en_US"
    assert "components" not in body_hw["template"]


def test_meta_whatsapp_detailed_error_and_accepted_id(monkeypatch):
    # Success response with message ID
    monkeypatch.setattr(notify, "_http", _Fake(200, json.dumps({
        "messaging_product": "whatsapp",
        "contacts": [{"input": "919876543210", "wa_id": "919876543210"}],
        "messages": [{"id": "wamid.HBgLMTIzNDU2"}]
    })))
    p = notify.get_provider("whatsapp", {"WHATSAPP_PROVIDER": "meta", "WHATSAPP_TOKEN": "t", "WHATSAPP_PHONE_ID": "1"})
    ok, detail = p.send("+919876543210", "update text", "en", "update")
    assert ok and "accepted (message id: wamid.HBgLMTIzNDU2)" in detail

    # Meta OAuth expired error
    monkeypatch.setattr(notify, "_http", _Fake(401, json.dumps({
        "error": {"code": 190, "message": "Invalid OAuth access token - Cannot parse access token"}
    })))
    ok, detail = p.send("+919876543210", "update text", "en", "update")
    assert not ok and "meta 401 [code 190]" in detail and "Invalid OAuth" in detail

    # Meta template not found error
    monkeypatch.setattr(notify, "_http", _Fake(400, json.dumps({
        "error": {"code": 132000, "message": "Template does not exist"}
    })))
    ok, detail = p.send("+919876543210", "update text", "en", "update")
    assert not ok and "meta 400 [code 132000]" in detail and "Template does not exist" in detail


def test_twilio_response_parsing_and_error(monkeypatch):
    # Twilio 201 accepted
    monkeypatch.setattr(notify, "_http", _Fake(201, json.dumps({
        "sid": "SMabcdef123456", "status": "queued"
    })))
    env = {"SMS_PROVIDER": "twilio", "TWILIO_ACCOUNT_SID": "AC1", "TWILIO_AUTH_TOKEN": "tok", "TWILIO_SMS_FROM": "+1234"}
    p = notify.get_provider("sms", env)
    ok, detail = p.send("+919876543210", "msg")
    assert ok and "accepted (queued, sid: SMabcdef123456)" in detail

    # Twilio 400 error
    monkeypatch.setattr(notify, "_http", _Fake(400, json.dumps({
        "code": 21211, "message": "The 'To' number is not a valid phone number."
    })))
    ok, detail = p.send("+919876543210", "msg")
    assert not ok and "twilio 400 [code 21211]" in detail and "not a valid phone number" in detail


def test_msg91_response_parsing_success_and_error_types(monkeypatch):
    env = {"SMS_PROVIDER": "msg91", "MSG91_AUTH_KEY": "k", "MSG91_OTP_TEMPLATE_ID": "t1", "MSG91_UPDATE_TEMPLATE_ID": "t2"}
    p = notify.get_provider("sms", env)

    # MSG91 HTTP 200 but error type
    monkeypatch.setattr(notify, "_http", _Fake(200, json.dumps({
        "type": "error", "message": "Invalid mobile number"
    })))
    ok, detail = p.send("+919876543210", "msg")
    assert not ok and "msg91 error: Invalid mobile number" in detail

    # MSG91 success with request_id
    monkeypatch.setattr(notify, "_http", _Fake(200, json.dumps({
        "type": "success", "request_id": "req_998877"
    })))
    ok, detail = p.send("+919876543210", "msg")
    assert ok and "accepted (msg91 request_id: req_998877)" in detail


def test_send_batch_both_channels_recorded_independently(monkeypatch):
    import phones
    logged = []

    def fake_log(conn, farmer_id, channel, kind, ok, detail, plan_id=None):
        logged.append({"farmer_id": farmer_id, "channel": channel, "kind": kind, "ok": ok, "detail": detail})

    class FakeConn:
        def execute(self, *a, **k): return self
        def commit(self): pass
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass

    monkeypatch.setattr(phones, "get_conn", lambda: FakeConn())
    monkeypatch.setattr(phones, "_log", fake_log)

    # Scenario 1: Both SMS and WhatsApp succeed
    monkeypatch.setattr(notify, "get_provider", lambda ch, env=None: (
        notify.DryRun("sms") if ch == "sms" else notify.DryRun("whatsapp")
    ))
    res = phones.send_batch([(1, "+919876543210", "en", _card(), "update")], plan_id=10)
    assert res == {"sent": 2, "failed": 0}
    assert len(logged) == 2
    assert {l["channel"] for l in logged} == {"sms", "whatsapp"}
    assert all(l["ok"] for l in logged)

    # Scenario 2: SMS succeeds, WhatsApp fails
    logged.clear()
    class FailingProvider:
        def __init__(self, channel, name, err): self.channel, self.name, self.live, self.err = channel, name, True, err
        def send(self, *a, **k): return False, self.err

    monkeypatch.setattr(notify, "get_provider", lambda ch, env=None: (
        notify.DryRun("sms") if ch == "sms" else FailingProvider("whatsapp", "meta", "meta 401 [code 190]: bad token")
    ))
    res = phones.send_batch([(2, "+919876543211", "en", _card(), "update")], plan_id=10)
    assert res == {"sent": 1, "failed": 1}
    sms_log = next(l for l in logged if l["channel"] == "sms")
    wa_log = next(l for l in logged if l["channel"] == "whatsapp")
    assert sms_log["ok"] is True
    assert wa_log["ok"] is False and "bad token" in wa_log["detail"] and "[meta]" in wa_log["detail"]

    # Scenario 3: WhatsApp succeeds, SMS fails
    logged.clear()
    monkeypatch.setattr(notify, "get_provider", lambda ch, env=None: (
        FailingProvider("sms", "twilio", "twilio 400 [code 21211]: bad number") if ch == "sms" else notify.DryRun("whatsapp")
    ))
    res = phones.send_batch([(3, "+919876543212", "en", _card(), "update")], plan_id=10)
    assert res == {"sent": 1, "failed": 1}
    sms_log = next(l for l in logged if l["channel"] == "sms")
    wa_log = next(l for l in logged if l["channel"] == "whatsapp")
    assert sms_log["ok"] is False and "bad number" in sms_log["detail"]
    assert wa_log["ok"] is True


def test_phones_start_dual_channel_behavior(monkeypatch):
    import phones
    logged = []

    class FakeConn:
        def execute(self, *a, **k): return self
        def fetchone(self): return None
        def commit(self): pass
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass

    monkeypatch.setattr(phones, "get_conn", lambda: FakeConn())
    monkeypatch.setattr(phones, "_log", lambda conn, fid, ch, kind, ok, det: logged.append((ch, ok, det)))

    class FakeProv:
        def __init__(self, ch, ok=True, det="ok"): self.channel, self.name, self.live, self.ok, self.det = ch, "mock", True, ok, det
        def send(self, *a, **k): return self.ok, self.det

    # Both succeed
    monkeypatch.setattr(notify, "get_provider", lambda ch, env=None: FakeProv(ch, True, "delivered"))
    logged.clear()
    r = phones.start(10, "+919876543210", "en")
    assert r["sent"] is True
    assert {l[0] for l in logged} == {"sms", "whatsapp"}
    assert all(l[1] is True for l in logged)

    # SMS succeeds, WhatsApp fails -> start still returns sent=True, both logged
    logged.clear()
    monkeypatch.setattr(notify, "get_provider", lambda ch, env=None: FakeProv(ch, ch == "sms", "err" if ch == "whatsapp" else "ok"))
    r2 = phones.start(11, "+919876543211", "en")
    assert r2["sent"] is True
    assert len(logged) == 2
    assert next(l for l in logged if l[0] == "sms")[1] is True
    assert next(l for l in logged if l[0] == "whatsapp")[1] is False

    # WhatsApp succeeds, SMS fails -> start still returns sent=True, both logged
    logged.clear()
    monkeypatch.setattr(notify, "get_provider", lambda ch, env=None: FakeProv(ch, ch == "whatsapp", "err" if ch == "sms" else "ok"))
    r3 = phones.start(12, "+919876543212", "en")
    assert r3["sent"] is True
    assert len(logged) == 2
    assert next(l for l in logged if l[0] == "whatsapp")[1] is True
    assert next(l for l in logged if l[0] == "sms")[1] is False

    # Both fail -> raises 502
    logged.clear()
    monkeypatch.setattr(notify, "get_provider", lambda ch, env=None: FakeProv(ch, False, "failure"))
    with pytest.raises(phones.HTTPException) as exc:
        phones.start(13, "+919876543213", "en")
    assert exc.value.status_code == 502


# ---------------------------------------------------------------- pure: who gets messaged on publish
def test_first_publish_messages_everyone_with_a_number_later_ones_only_changed_farmers():
    import phones
    rows = [{"farmer_id": 1, "phone": "+911", "lang": "en"}, {"farmer_id": 2, "phone": "+912", "lang": "ta"},
            {"farmer_id": 9, "phone": "+919", "lang": "en"}]                                   # 9 has no card: skipped
    cards = {1: _card(changed=None), 2: _card(changed=["pickup moved"]), 3: _card(changed=["x"])}   # 3 has no number
    first = phones.select_targets(cards, rows, only_changed=False)
    assert [(t[0], t[4]) for t in first] == [(1, "update"), (2, "changed")]
    later = phones.select_targets(cards, rows, only_changed=True)
    assert [(t[0], t[2], t[4]) for t in later] == [(2, "ta", "changed")]
    assert phones.select_targets({str(k): v for k, v in cards.items()}, rows, False) == first     # JSON-style keys too


# ---------------------------------------------------------------- API, against a real Postgres
pytestmark_db = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs DATABASE_URL (a Postgres)")


@pytest.fixture(scope="module")
def api():
    from fastapi.testclient import TestClient
    import main
    os.environ.update(ADMIN_TOKEN="admin-secret", FARMROUTE_SECRET="test-signing-secret", NOTIFY_DEMO_SHOW_OTP="on")
    os.environ.pop("SMS_PROVIDER", None)
    os.environ.pop("WHATSAPP_PROVIDER", None)
    farmers, fleet, markets = generate_scenario_v2(n_farmers=12, n_markets=3, seed=5)
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
        c.pins = {p["farmer_id"]: p["pin"] for p in c.post("/farmers/pins").json()["pins"]}
        yield c
    for k in ("ADMIN_TOKEN", "FARMROUTE_SECRET", "NOTIFY_DEMO_SHOW_OTP"):
        os.environ.pop(k, None)


def _farmer(api, fid):
    """A client logged in as farmer `fid` (no admin header)."""
    from fastapi.testclient import TestClient
    import main
    c = TestClient(main.app)
    tok = c.post("/farmer/login", json={"farmer_id": fid, "pin": api.pins[fid]}).json()["token"]
    c.headers.update({"Authorization": f"Bearer {tok}"})
    return c


def _clear_otp_throttle(fid):
    from database import get_conn
    with get_conn() as conn:
        conn.execute("UPDATE phone_otps SET sent_at = sent_at - 120 WHERE farmer_id = %s", (fid,))
        conn.commit()


@pytestmark_db
def test_phone_routes_need_the_right_token(api):
    from fastapi.testclient import TestClient
    import main
    anon = TestClient(main.app)
    assert anon.get("/farmer/phone").status_code == 401
    assert anon.post("/farmer/phone/start", json={"phone": "9876543210"}).status_code == 401
    assert anon.get("/farmers/phones").status_code == 401                                   # admin only
    assert anon.delete("/farmers/phones?confirm=true").status_code == 401
    f = _farmer(api, 1)
    assert f.get("/farmers/phones").status_code == 401                                      # a farmer token is not admin
    assert f.delete("/farmers/phones?confirm=true").status_code == 401
    assert f.delete("/farmers/2/phone").status_code == 401


@pytestmark_db
def test_number_is_stored_only_after_the_right_code_and_then_shows_masked(api):
    f = _farmer(api, 1)
    assert f.get("/farmer/phone").json()["registered"] is False
    assert f.post("/farmer/phone/start", json={"phone": "12ab"}).status_code == 422
    r = f.post("/farmer/phone/start", json={"phone": "98765 43210", "lang": "ta"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["to"] == "+91******3210" and len(body["demo_otp"]) == 6
    assert f.get("/farmer/phone").json()["registered"] is False                             # asking for a code stores nothing
    bad = "000000" if body["demo_otp"] != "000000" else "111111"
    assert f.post("/farmer/phone/verify", json={"code": bad}).status_code == 400
    assert f.post("/farmer/phone/verify", json={"code": "12ab56"}).status_code == 422
    ok = f.post("/farmer/phone/verify", json={"code": body["demo_otp"]})
    assert ok.status_code == 200 and ok.json() == {"registered": True, "masked": "+91******3210", "lang": "ta"}
    assert f.post("/farmer/phone/verify", json={"code": body["demo_otp"]}).status_code == 400     # code is single-use


@pytestmark_db
def test_code_limits_resend_wait_and_five_guesses(api):
    f = _farmer(api, 2)
    code = f.post("/farmer/phone/start", json={"phone": "9876543211"}).json()["demo_otp"]
    again = f.post("/farmer/phone/start", json={"phone": "9876543211"})
    assert again.status_code == 429 and int(again.headers["Retry-After"]) > 0
    wrong = "000000" if code != "000000" else "111111"
    assert [f.post("/farmer/phone/verify", json={"code": wrong}).status_code for _ in range(5)] == [400] * 5
    assert f.post("/farmer/phone/verify", json={"code": code}).status_code == 429            # burned even for the right code
    _clear_otp_throttle(2)
    fresh = f.post("/farmer/phone/start", json={"phone": "9876543211"}).json()["demo_otp"]
    assert f.post("/farmer/phone/verify", json={"code": fresh}).json()["registered"] is True


@pytestmark_db
def test_expired_code_is_refused_and_a_code_cannot_move_to_another_farmer(api):
    from database import get_conn
    a, b = _farmer(api, 3), _farmer(api, 4)
    code = a.post("/farmer/phone/start", json={"phone": "9876543212"}).json()["demo_otp"]
    assert b.post("/farmer/phone/verify", json={"code": code}).status_code == 400            # b never asked for a code
    with get_conn() as conn:
        conn.execute("UPDATE phone_otps SET expires_at = %s WHERE farmer_id = 3", (time.time() - 1,))
        conn.commit()
    assert a.post("/farmer/phone/verify", json={"code": code}).status_code == 400
    assert a.get("/farmer/phone").json()["registered"] is False


@pytestmark_db
def test_card_tells_the_app_whether_a_number_is_stored_and_farmer_can_remove_it(api):
    api.post(f"/plan/{api.plan_id}/publish")
    f = _farmer(api, 1)                                                                      # registered in the test above
    assert f.get("/farmer/me").json()["phone"]["registered"] is True
    assert f.delete("/farmer/phone").json()["registered"] is False
    assert f.get("/farmer/me").json()["phone"] == {"registered": False, "masked": None, "lang": None}


@pytestmark_db
def test_publish_reports_who_will_be_messaged_and_logs_dry_run_sends(api):
    f = _farmer(api, 5)
    f.post("/farmer/phone/start", json={"phone": "9876543215"})
    code = f.post("/farmer/phone/start", json={"phone": "9876543215"})                       # throttled: use the first code
    assert code.status_code == 429
    _clear_otp_throttle(5)
    code = f.post("/farmer/phone/start", json={"phone": "9876543215", "lang": "hi"}).json()["demo_otp"]
    assert f.post("/farmer/phone/verify", json={"code": code}).json()["registered"] is True
    pub = api.post(f"/plan/{api.plan_id}/publish").json()
    assert pub["phone_updates"]["dry_run"] is True and pub["phone_updates"]["sms"] == "dry"
    assert pub["phone_updates"]["farmers_messaged"] == 0                                     # same plan again: nothing changed
    s = api.get("/farmers/phones").json()
    assert s["registered"] >= 1 and s["providers"]["sms"]["provider"] == "dry"
    assert any(r["farmer_id"] == 5 and r["masked"] == "+91******3215" for r in s["rows"])
    assert all("9876543215" not in json.dumps(r) for r in s["rows"] + s["recent"])           # no full numbers, no texts
    kinds = {(r["channel"], r["kind"]) for r in s["recent"]}
    assert ("sms", "otp") in kinds and ("sms", "welcome") in kinds and ("whatsapp", "welcome") in kinds


@pytestmark_db
def test_admin_reset_clears_every_number_needs_confirm_and_farmers_are_asked_again(api):
    f6 = _farmer(api, 6)
    code = f6.post("/farmer/phone/start", json={"phone": "9876543216"}).json()["demo_otp"]
    f6.post("/farmer/phone/verify", json={"code": code})
    assert api.get("/farmers/phones").json()["registered"] >= 1
    assert api.delete("/farmers/phones").status_code == 400                                  # no confirm: refused
    assert api.get("/farmers/phones").json()["registered"] >= 1
    n = api.delete("/farmers/phones?confirm=true").json()["cleared"]
    assert n >= 1
    after = api.get("/farmers/phones").json()
    assert after["registered"] == 0 and after["rows"] == [] and after["farmers"] == 12
    assert f6.get("/farmer/phone").json()["registered"] is False
    f7 = _farmer(api, 7)                                                                      # clearing one farmer only
    c7 = f7.post("/farmer/phone/start", json={"phone": "9876543217"}).json()["demo_otp"]
    f7.post("/farmer/phone/verify", json={"code": c7})
    _clear_otp_throttle(6)
    c6 = f6.post("/farmer/phone/start", json={"phone": "9876543216"}).json()["demo_otp"]
    f6.post("/farmer/phone/verify", json={"code": c6})
    assert api.delete("/farmers/7/phone").json() == {"cleared": 1}
    assert [r["farmer_id"] for r in api.get("/farmers/phones").json()["rows"]] == [6]
    assert api.delete("/farmers/7/phone").json() == {"cleared": 0}


@pytestmark_db
def test_a_pending_code_does_not_survive_an_admin_reset(api):
    f8 = _farmer(api, 8)
    code = f8.post("/farmer/phone/start", json={"phone": "9876543218"}).json()["demo_otp"]
    api.delete("/farmers/phones?confirm=true")
    assert f8.post("/farmer/phone/verify", json={"code": code}).status_code == 400


@pytestmark_db
def test_demo_otp_is_never_returned_unless_the_flag_is_on(api, monkeypatch):
    monkeypatch.setenv("NOTIFY_DEMO_SHOW_OTP", "off")
    f = _farmer(api, 9)
    r = f.post("/farmer/phone/start", json={"phone": "9876543219"})
    assert r.status_code == 200 and "demo_otp" not in r.json()
