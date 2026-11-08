"""Web Push: who is notified, the message, subscription validation, expired-subscription cleanup. No database, no network."""
import contextlib
import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import push


def _card(changed, status="hauled"):
    return {"changed": changed, "status": status, "qty_kg": 100, "crop": "tomato",
            "trip": {"pickup_eta": "07:30", "mandis": [{"id": 2}]}, "payout": {"total_inr": 4000}, "doorstep_per_kg": 12}


ROWS = [{"endpoint": f"https://push.example/{i}", "farmer_id": i, "p256dh": "k", "auth": "a", "lang": "en"} for i in (1, 2, 3)]
CARDS = {1: _card(True), 2: _card(False), "3": _card(True)}


def test_only_changed_farmers_after_a_replan():
    got = push.select_targets(CARDS, ROWS, only_changed=True)
    assert [t[0] for t in got] == [1, 3] and all(t[3] == "changed" for t in got)


def test_everyone_subscribed_on_first_publish():
    got = push.select_targets(CARDS, ROWS, only_changed=False)
    assert [t[0] for t in got] == [1, 2, 3] and got[1][3] == "update"


def test_farmer_without_card_is_skipped():
    assert push.select_targets({}, ROWS, only_changed=False) == []


def test_payload_is_the_farmers_own_message_in_their_language():
    body = json.loads(push.build_payload(_card(True), "ta", "changed", 9))
    assert body["tag"] == "farmroute-plan" and body["plan_id"] == 9 and body["body"].startswith("Farmroute")
    assert json.loads(push.build_payload(_card(True), "xx", "changed"))["body"]      # unknown language -> English


def test_disabled_without_keys(monkeypatch):
    monkeypatch.delenv("VAPID_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("VAPID_PRIVATE_KEY", raising=False)
    assert not push.enabled() and push.plan_targets(CARDS, True) == []
    with pytest.raises(HTTPException) as e:
        push.subscribe(1, {"endpoint": "https://x", "keys": {"p256dh": "a", "auth": "b"}}, "en")
    assert e.value.status_code == 503


@pytest.mark.parametrize("bad", [{}, {"endpoint": "http://insecure", "keys": {"p256dh": "a", "auth": "b"}},
                                 {"endpoint": "https://x", "keys": {"p256dh": "a"}}, {"endpoint": "https://x"}])
def test_bad_subscription_rejected(bad):
    with pytest.raises(HTTPException) as e:
        push._validate(bad)
    assert e.value.status_code == 422


def test_send_batch_counts_and_removes_gone_subscriptions(monkeypatch):
    sql = []

    class Conn:
        def execute(self, q, p=()):
            sql.append((q.split()[0], p))
        def commit(self):
            pass

    @contextlib.contextmanager
    def fake_conn():
        yield Conn()

    def fake_send(row, payload):
        return {1: (True, "sent", False), 2: (False, "HTTP 410", True), 3: (False, "HTTP 500", False)}[row["farmer_id"]]

    monkeypatch.setattr(push, "get_conn", fake_conn)
    monkeypatch.setattr(push, "_send_one", fake_send)
    targets = push.select_targets({1: _card(True), 2: _card(True), 3: _card(True)}, ROWS, only_changed=True)
    assert push.send_batch(targets, 5) == {"sent": 1, "failed": 2, "removed": 1}
    assert sum(1 for q, _ in sql if q == "DELETE") == 1 and sum(1 for q, _ in sql if q == "INSERT") == 3
