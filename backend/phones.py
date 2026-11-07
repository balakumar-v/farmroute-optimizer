"""
phones.py -- farmers' phone numbers and the SMS / WhatsApp updates sent to them (database side; the pure parts
are in notify.py).

How a number gets stored: a logged-in farmer types it (the browser cannot read the SIM number), we text a 6-digit
code, they type the code back, and only then is the number stored against their farmer id. Nothing here can set a
number for a farmer who has not proved they hold it. Codes expire in 10 minutes, allow 5 guesses, are stored only
as a keyed digest, and can be requested once a minute and five times an hour per farmer.

How updates go out: when an operator publishes a plan, every farmer with a number whose card CHANGED gets one SMS
and one WhatsApp message (everyone with a number, if there is no earlier published plan). A farmer who registers a
number after a plan is published gets that plan once, straight away. Failures are logged per message and never
block publishing.

The admin side can clear one farmer's number or every number (reset_all).
"""
import hmac
import json
import logging
import os
import re
import time

from fastapi import HTTPException

import auth
import notify
from database import get_conn

log = logging.getLogger("farmroute.phones")

RESEND_S = 60
MAX_SENDS_PER_HOUR = 5
MAX_GUESSES = 5


def status(farmer_id: int) -> dict:
    """What the farmer app may know about its own number: whether there is one, and it masked."""
    with get_conn() as conn:
        r = conn.execute("SELECT phone, lang FROM farmer_phones WHERE farmer_id = %s", (farmer_id,)).fetchone()
    return {"registered": r is not None, "masked": notify.mask_phone(r["phone"]) if r else None,
            "lang": r["lang"] if r else None}


def _log(conn, farmer_id, channel, kind, ok, detail, plan_id=None):
    conn.execute("INSERT INTO notification_log (farmer_id, channel, kind, ok, detail, plan_id, created_at) "
                 "VALUES (%s, %s, %s, %s, %s, %s, %s)", (farmer_id, channel, kind, ok, detail[:300], plan_id, time.time()))


def demo_show_otp() -> bool:
    return os.environ.get("NOTIFY_DEMO_SHOW_OTP", "off").strip().lower() == "on"


# ---------------------------------------------------------------- farmer: register, verify, remove
def start(farmer_id: int, raw_phone: str, lang: str) -> dict:
    try:
        phone = notify.normalize_phone(raw_phone)
    except ValueError as e:
        raise HTTPException(422, str(e))
    lang = lang if lang in notify.LANGS else "en"
    now = time.time()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM phone_otps WHERE farmer_id = %s FOR UPDATE", (farmer_id,)).fetchone()
        count, window = 1, now
        if row is not None:
            if now - row["sent_at"] < RESEND_S:
                wait = int(RESEND_S - (now - row["sent_at"])) + 1
                raise HTTPException(429, "Please wait a minute before asking for another code.", headers={"Retry-After": str(wait)})
            if now - row["window_start"] < 3600:
                count, window = row["send_count"] + 1, row["window_start"]
                if count > MAX_SENDS_PER_HOUR:
                    wait = int(3600 - (now - window)) + 1
                    raise HTTPException(429, "Too many codes requested. Try again later or ask your FPO.", headers={"Retry-After": str(wait)})
        code = notify.new_otp()
        conn.execute(
            "INSERT INTO phone_otps (farmer_id, phone, lang, digest, expires_at, attempts, sent_at, window_start, send_count) "
            "VALUES (%s, %s, %s, %s, %s, 0, %s, %s, %s) ON CONFLICT (farmer_id) DO UPDATE SET phone = EXCLUDED.phone, "
            "lang = EXCLUDED.lang, digest = EXCLUDED.digest, expires_at = EXCLUDED.expires_at, attempts = 0, "
            "sent_at = EXCLUDED.sent_at, window_start = EXCLUDED.window_start, send_count = EXCLUDED.send_count",
            (farmer_id, phone, lang, notify.otp_digest(farmer_id, phone, code, auth._key()), now + notify.OTP_TTL_S,
             now, window, count))
        conn.commit()

    channels = notify.otp_channels()
    any_ok = False
    all_live = True
    channel_details = {}

    for ch in channels:
        provider = notify.get_provider(ch)
        all_live = all_live and provider.live
        try:
            ok, detail = provider.send(phone, notify.compose_otp_message(code, lang), lang, "otp")
        except Exception as e:
            ok, detail = False, f"{type(e).__name__}: {e}"
        any_ok = any_ok or ok
        detail_str = f"[{provider.name}] {detail}" if not detail.startswith(f"[{provider.name}]") else detail
        channel_details[ch] = (ok, detail_str)
        try:
            with get_conn() as conn:
                _log(conn, farmer_id, provider.channel, "otp", ok, detail_str)
                conn.commit()
        except Exception:
            log.exception("could not write OTP notification log for channel %s", ch)

    if not any_ok:
        log.error("OTP send failed on all channels for farmer %s: %s", farmer_id, channel_details)
        raise HTTPException(502, "We could not send the code. Please try again later or ask your FPO.")

    out = {"sent": True, "to": notify.mask_phone(phone), "resend_after_s": RESEND_S, "expires_in_s": notify.OTP_TTL_S}
    if not all_live and demo_show_otp():
        out["demo_otp"] = code                     # only with NOTIFY_DEMO_SHOW_OTP=on AND non-live provider: demos, never real use
    return out


def verify(farmer_id: int, code: str) -> dict:
    """Stores the number if the code is right. Returns status(); raises 400 (wrong/expired) or 429 (too many guesses)."""
    now = time.time()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM phone_otps WHERE farmer_id = %s FOR UPDATE", (farmer_id,)).fetchone()
        if row is None or row["expires_at"] < now:
            raise HTTPException(400, "That code has expired. Ask for a new one.")
        if row["attempts"] >= MAX_GUESSES:
            raise HTTPException(429, "Too many wrong codes. Ask for a new one.")
        good = hmac.compare_digest(notify.otp_digest(farmer_id, row["phone"], code, auth._key()), row["digest"])
        if not good:
            conn.execute("UPDATE phone_otps SET attempts = attempts + 1 WHERE farmer_id = %s", (farmer_id,))
            conn.commit()
            raise HTTPException(400, "That code is not right.")
        conn.execute(
            "INSERT INTO farmer_phones (farmer_id, phone, lang, verified_at) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (farmer_id) DO UPDATE SET phone = EXCLUDED.phone, lang = EXCLUDED.lang, verified_at = EXCLUDED.verified_at",
            (farmer_id, row["phone"], row["lang"], now))
        conn.execute("DELETE FROM phone_otps WHERE farmer_id = %s", (farmer_id,))
        conn.commit()
    return status(farmer_id)


def remove(farmer_id: int) -> int:
    """Clears one farmer's number (and any pending code). Used by the farmer ('stop messages') and by the admin."""
    with get_conn() as conn:
        n = conn.execute("DELETE FROM farmer_phones WHERE farmer_id = %s", (farmer_id,)).rowcount
        conn.execute("DELETE FROM phone_otps WHERE farmer_id = %s", (farmer_id,))
        conn.commit()
    return n


# ---------------------------------------------------------------- admin
def reset_all() -> int:
    """Clears every stored number and every pending code. Farmers are asked for their number again on next login."""
    with get_conn() as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM farmer_phones").fetchone()["n"]
        conn.execute("DELETE FROM farmer_phones")
        conn.execute("DELETE FROM phone_otps")
        conn.commit()
    return n


def summary(recent: int = 15) -> dict:
    """For the admin console: who has a number (masked), how many farmers there are, how sending is set up, and the
    last messages. Full numbers are never returned."""
    with get_conn() as conn:
        farmers = conn.execute("SELECT COUNT(*) AS n FROM farmers").fetchone()["n"]
        rows = conn.execute("SELECT farmer_id, phone, lang, verified_at FROM farmer_phones ORDER BY farmer_id").fetchall()
        log_rows = conn.execute("SELECT farmer_id, channel, kind, ok, detail, plan_id, created_at FROM notification_log "
                                "ORDER BY id DESC LIMIT %s", (recent,)).fetchall()
        phone_map = {r["farmer_id"]: notify.mask_phone(r["phone"]) for r in rows}
    enriched_recent = []
    for r in log_rows:
        item = dict(r)
        item["masked"] = phone_map.get(item["farmer_id"])
        m = re.match(r"^\[([a-zA-Z0-9_\-]+)\]\s*(.*)", item.get("detail", ""))
        item["provider"] = m.group(1) if m else item.get("channel")
        enriched_recent.append(item)
    return {"farmers": farmers, "registered": len(rows), "providers": notify.describe_providers(),
            "rows": [{"farmer_id": r["farmer_id"], "masked": notify.mask_phone(r["phone"]), "lang": r["lang"],
                      "verified_at": r["verified_at"]} for r in rows],
            "recent": enriched_recent}


# ---------------------------------------------------------------- sending plan updates
def select_targets(cards: dict, phone_rows: list, only_changed: bool) -> list:
    """Pure. Who gets a message for this published plan: [(farmer_id, phone, lang, card, kind)].
    only_changed=True (there was an earlier published plan): just farmers whose card says something changed.
    only_changed=False (first publish): every farmer who has a number and a card."""
    out = []
    for r in phone_rows:
        card = cards.get(r["farmer_id"]) or cards.get(str(r["farmer_id"]))
        if card is None:
            continue
        changed = bool(card.get("changed"))
        if only_changed and not changed:
            continue
        out.append((r["farmer_id"], r["phone"], r["lang"], card, "changed" if changed else "update"))
    return out


def plan_targets(cards: dict, only_changed: bool) -> list:
    with get_conn() as conn:
        rows = conn.execute("SELECT farmer_id, phone, lang FROM farmer_phones ORDER BY farmer_id").fetchall()
    return select_targets(cards, rows, only_changed)


def send_batch(targets: list, plan_id=None) -> dict:
    """Sends each target one SMS and one WhatsApp message, logging every attempt. Runs after the publish response
    has gone out (FastAPI background task), so a slow or failing provider cannot hold up or break publishing."""
    sms, wa = notify.get_provider("sms"), notify.get_provider("whatsapp")
    sent = failed = 0
    for farmer_id, phone, lang, card, kind in targets:
        try:
            text = notify.compose_plan_message(card, lang, kind)
        except Exception:
            log.exception("could not compose message for farmer %s", farmer_id)
            continue
        for provider in (sms, wa):
            try:
                ok, detail = provider.send(phone, text, lang, kind)
            except Exception as e:
                ok, detail = False, f"{type(e).__name__}: {e}"
            sent, failed = sent + int(ok), failed + int(not ok)
            detail_str = f"[{provider.name}] {detail}" if not detail.startswith(f"[{provider.name}]") else detail
            try:
                with get_conn() as conn:
                    _log(conn, farmer_id, provider.channel, kind, ok, detail_str, plan_id)
                    conn.commit()
            except Exception:
                log.exception("could not write notification log")
    log.info("plan %s updates: %s sent, %s failed", plan_id, sent, failed)
    return {"sent": sent, "failed": failed}


def send_welcome(farmer_id: int) -> None:
    """Right after a farmer verifies a number: the plan that is published now, once. If none is published, sends a
    welcome message to both SMS and WhatsApp."""
    with get_conn() as conn:
        pub = conn.execute("SELECT plan_id, cards FROM published_plan WHERE id = 1").fetchone()
        ph = conn.execute("SELECT farmer_id, phone, lang FROM farmer_phones WHERE farmer_id = %s", (farmer_id,)).fetchone()
    if ph is None:
        return
    if pub is not None:
        card = json.loads(pub["cards"]).get(str(farmer_id))
        if card is not None:
            send_batch([(farmer_id, ph["phone"], ph["lang"], card, "welcome")], pub["plan_id"])
            return
    # Standalone welcome message when no plan is published yet
    sms, wa = notify.get_provider("sms"), notify.get_provider("whatsapp")
    welcome_text = "Farmroute: " + notify._MSG.get(ph["lang"], notify._MSG["en"])["welcome"].strip()
    for provider in (sms, wa):
        try:
            ok, detail = provider.send(ph["phone"], welcome_text, ph["lang"], "welcome")
        except Exception as e:
            ok, detail = False, f"{type(e).__name__}: {e}"
        detail_str = f"[{provider.name}] {detail}" if not detail.startswith(f"[{provider.name}]") else detail
        try:
            with get_conn() as conn:
                _log(conn, farmer_id, provider.channel, "welcome", ok, detail_str)
                conn.commit()
        except Exception:
            log.exception("could not write welcome notification log")
