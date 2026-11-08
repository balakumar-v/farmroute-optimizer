"""
push.py -- Web Push (phone notifications from the farmer PWA) when a published plan changes for a farmer.

How it works: a logged-in farmer taps "Notify me when my plan changes" in the app; the browser creates a push
subscription and the app sends it to POST /farmer/push/subscribe. When an operator publishes a plan (that includes
approving a change request, which re-plans and publishes), every subscribed farmer whose card CHANGED gets one
notification in their language (everyone subscribed, if there was no earlier published plan). The text is the same
one-line message the SMS / WhatsApp path uses (notify.compose_plan_message), so it holds only the farmer's own facts.

Setup (once): `python generate_vapid.py`, then set VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY and VAPID_SUBJECT
(mailto:you@example.com) on the backend. Without keys the feature is off: /farmer/push/key says so, the app hides
the button, and nothing is sent. Sending uses the `pywebpush` package, imported only when a push is actually sent.

Failures are logged per message and never block publishing. A subscription the push service says is gone
(HTTP 404 / 410) is deleted.
"""
import json
import logging
import os
import time

from fastapi import HTTPException

import notify
from database import get_conn

log = logging.getLogger("farmroute.push")

LANGS = notify.LANGS
TITLE = {"en": "Farmroute", "te": "Farmroute", "hi": "Farmroute", "ta": "Farmroute"}


def public_key() -> str:
    return (os.environ.get("VAPID_PUBLIC_KEY") or "").strip()


def enabled() -> bool:
    return bool(public_key() and (os.environ.get("VAPID_PRIVATE_KEY") or "").strip())


def _validate(sub: dict) -> tuple:
    try:
        endpoint = str(sub["endpoint"])
        keys = sub["keys"]
        p256dh, auth_key = str(keys["p256dh"]), str(keys["auth"])
    except (KeyError, TypeError):
        raise HTTPException(422, "Not a valid push subscription.")
    if not endpoint.startswith("https://") or len(endpoint) > 2048 or not p256dh or not auth_key:
        raise HTTPException(422, "Not a valid push subscription.")
    return endpoint, p256dh, auth_key


def subscribe(farmer_id: int, sub: dict, lang: str) -> dict:
    if not enabled():
        raise HTTPException(503, "Push notifications are not switched on at the server yet.")
    endpoint, p256dh, auth_key = _validate(sub)
    lang = lang if lang in LANGS else "en"
    with get_conn() as conn:
        # One row per browser (endpoint). A shared phone logging in as someone else takes the row over.
        conn.execute(
            "INSERT INTO push_subscriptions (endpoint, farmer_id, p256dh, auth, lang, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (endpoint) DO UPDATE SET farmer_id = EXCLUDED.farmer_id, "
            "p256dh = EXCLUDED.p256dh, auth = EXCLUDED.auth, lang = EXCLUDED.lang, created_at = EXCLUDED.created_at",
            (endpoint, farmer_id, p256dh, auth_key, lang, time.time()))
        conn.commit()
    return status(farmer_id)


def unsubscribe(farmer_id: int, endpoint: str = None) -> dict:
    """Removes this browser's subscription when `endpoint` is given, else all of the farmer's."""
    with get_conn() as conn:
        if endpoint:
            conn.execute("DELETE FROM push_subscriptions WHERE farmer_id = %s AND endpoint = %s", (farmer_id, endpoint))
        else:
            conn.execute("DELETE FROM push_subscriptions WHERE farmer_id = %s", (farmer_id,))
        conn.commit()
    return status(farmer_id)


def status(farmer_id: int) -> dict:
    with get_conn() as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM push_subscriptions WHERE farmer_id = %s", (farmer_id,)).fetchone()["n"]
    return {"enabled": enabled(), "subscribed": n > 0, "devices": n}


def select_targets(cards: dict, rows: list, only_changed: bool) -> list:
    """Pure. [(farmer_id, subscription_row, card, kind)] for this published plan. Same rule as the SMS path."""
    out = []
    for r in rows:
        card = cards.get(r["farmer_id"]) or cards.get(str(r["farmer_id"]))
        if card is None:
            continue
        changed = bool(card.get("changed"))
        if only_changed and not changed:
            continue
        out.append((r["farmer_id"], r, card, "changed" if changed else "update"))
    return out


def plan_targets(cards: dict, only_changed: bool) -> list:
    if not enabled():
        return []
    with get_conn() as conn:
        rows = conn.execute("SELECT endpoint, farmer_id, p256dh, auth, lang FROM push_subscriptions "
                            "ORDER BY farmer_id").fetchall()
    return select_targets(cards, rows, only_changed)


def build_payload(card: dict, lang: str, kind: str, plan_id=None) -> str:
    lang = lang if lang in LANGS else "en"
    return json.dumps({"title": TITLE[lang], "body": notify.compose_plan_message(card, lang, kind),
                       "tag": "farmroute-plan", "plan_id": plan_id, "url": "./"}, ensure_ascii=False)


def _send_one(row: dict, payload: str):
    """Returns (ok, detail, gone). Isolated so tests can replace it."""
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        return False, "pywebpush is not installed (pip install pywebpush)", False
    try:
        webpush(subscription_info={"endpoint": row["endpoint"], "keys": {"p256dh": row["p256dh"], "auth": row["auth"]}},
                data=payload, vapid_private_key=os.environ["VAPID_PRIVATE_KEY"].strip(),
                vapid_claims={"sub": os.environ.get("VAPID_SUBJECT", "mailto:admin@example.com")}, ttl=12 * 3600)
        return True, "sent", False
    except WebPushException as e:
        code = getattr(getattr(e, "response", None), "status_code", None)
        return False, f"HTTP {code}: {str(e)[:120]}", code in (404, 410)
    except Exception as e:                                           # pragma: no cover
        return False, f"{type(e).__name__}: {str(e)[:120]}", False


def send_batch(targets: list, plan_id=None) -> dict:
    """Runs after the publish response has gone out (FastAPI background task)."""
    sent = failed = removed = 0
    for farmer_id, row, card, kind in targets:
        try:
            payload = build_payload(card, row["lang"], kind, plan_id)
        except Exception:
            log.exception("could not compose push for farmer %s", farmer_id)
            continue
        ok, detail, gone = _send_one(row, payload)
        sent, failed = sent + int(ok), failed + int(not ok)
        try:
            with get_conn() as conn:
                if gone:
                    conn.execute("DELETE FROM push_subscriptions WHERE endpoint = %s", (row["endpoint"],))
                    removed += 1
                conn.execute("INSERT INTO notification_log (farmer_id, channel, kind, ok, detail, plan_id, created_at) "
                             "VALUES (%s, 'push', %s, %s, %s, %s, %s)",
                             (farmer_id, kind, ok, f"[push] {detail}"[:300], plan_id, time.time()))
                conn.commit()
        except Exception:
            log.exception("could not write push log")
    log.info("plan %s push: %s sent, %s failed, %s expired subscriptions removed", plan_id, sent, failed, removed)
    return {"sent": sent, "failed": failed, "removed": removed}
