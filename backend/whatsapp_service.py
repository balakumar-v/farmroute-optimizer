"""
whatsapp_service.py
-------------------
Standalone Meta WhatsApp Cloud API Service for FarmRoute Optimizer.
Exclusively uses the Phone Number ID endpoint:
  POST https://graph.facebook.com/{GRAPH_API_VERSION}/{PHONE_NUMBER_ID}/messages

IMPORTANT ARCHITECTURE RULE:
  Does NOT require or use WHATSAPP_BUSINESS_ACCOUNT_ID.
  Messages are sent directly from the Phone Number ID.
  WHATSAPP_BUSINESS_ACCOUNT_ID is completely optional and never validated.
"""

import hashlib
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("farmroute.whatsapp")

# Default settings
DEFAULT_GRAPH_VERSION = "v20.0"
DEFAULT_OTP_TEMPLATE = "farmroute_otp"
DEFAULT_PLAN_TEMPLATE = "farmroute_plan_update"
DEFAULT_WEBHOOK_VERIFY_TOKEN = "farmroute-webhook-verify-token"

# In-memory deduplication cache: hash -> timestamp (expires after 30 seconds)
_recent_dispatches: Dict[str, float] = {}
DEDUP_WINDOW_SECONDS = 30.0

# In-memory webhook event store for fast status lookups & deduplication
_processed_webhook_events: Dict[str, Dict[str, Any]] = {}


# ---------------------------------------------------------------- Configuration
def get_config(env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Extracts WhatsApp Cloud API configuration from the environment.
    Note: WHATSAPP_BUSINESS_ACCOUNT_ID is intentionally NOT required."""
    env = os.environ if env is None else env

    token = (env.get("WHATSAPP_TOKEN") or "").strip()
    phone_id = (
        env.get("WHATSAPP_PHONE_NUMBER_ID") or env.get("WHATSAPP_PHONE_ID") or ""
    ).strip()
    version = (
        env.get("WHATSAPP_GRAPH_API_VERSION")
        or env.get("WHATSAPP_API_VERSION")
        or DEFAULT_GRAPH_VERSION
    ).strip()
    otp_template = (env.get("WHATSAPP_OTP_TEMPLATE") or DEFAULT_OTP_TEMPLATE).strip()
    plan_template = (env.get("WHATSAPP_TEMPLATE") or DEFAULT_PLAN_TEMPLATE).strip()
    otp_button = (env.get("WHATSAPP_OTP_BUTTON") or "copy_code").strip().lower()
    webhook_verify_token = (
        env.get("WHATSAPP_WEBHOOK_VERIFY_TOKEN") or DEFAULT_WEBHOOK_VERIFY_TOKEN
    ).strip()

    # Optional WABA ID (never required for message sending)
    waba_id = (env.get("WHATSAPP_BUSINESS_ACCOUNT_ID") or "").strip()

    return {
        "token": token,
        "phone_number_id": phone_id,
        "graph_api_version": version,
        "otp_template": otp_template,
        "plan_template": plan_template,
        "otp_button": otp_button,
        "webhook_verify_token": webhook_verify_token,
        "waba_id": waba_id or None,
        "waba_id_required_for_sending": False,
        "configured": bool(token and phone_id),
    }


def clean_phone(raw: str) -> str:
    """Strips '+', spaces, dashes, and returns digits for Meta Cloud API."""
    digits = re.sub(r"\D", "", str(raw or ""))
    return digits


# ---------------------------------------------------------------- Payload Builders
def build_hello_world_payload(to: str) -> dict:
    """Builds a dedicated hello_world template payload for sandbox connectivity testing.
    hello_world has no components and uses language en_US."""
    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": clean_phone(to),
        "type": "template",
        "template": {
            "name": "hello_world",
            "language": {"code": "en_US"},
        },
    }


def build_otp_payload(
    to: str,
    code: str,
    lang: str = "en",
    template_name: Optional[str] = None,
    button_type: str = "copy_code",
) -> dict:
    """Builds an Authentication template payload for OTP verification codes.
    The code parameter must be the pure numeric/alphanumeric code (e.g. '123456').
    If template_name is hello_world, delegates to build_hello_world_payload."""
    template_name = template_name or DEFAULT_OTP_TEMPLATE
    if template_name == "hello_world":
        return build_hello_world_payload(to)

    # Extract 6-digit code if a full sentence was passed
    code_match = re.search(r"\b\d{6}\b", str(code))
    otp_code = code_match.group(0) if code_match else str(code).strip()

    lang_code = lang if lang in ("en", "te", "hi", "ta") else "en"

    components = [
        {
            "type": "body",
            "parameters": [{"type": "text", "text": otp_code}],
        }
    ]

    # Authentication templates with Copy Code button require a button component
    if button_type not in ("off", "none", "false", "0"):
        components.append(
            {
                "type": "button",
                "sub_type": "url",
                "index": "0",
                "parameters": [{"type": "text", "text": otp_code}],
            }
        )

    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": clean_phone(to),
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": lang_code},
            "components": components,
        },
    }


def build_utility_payload(
    to: str,
    parameters: Any,
    lang: str = "en",
    template_name: Optional[str] = None,
) -> dict:
    """Builds a Utility template payload for plan updates, activations, renewals, etc.
    parameters can be a single string or a list of parameter values."""
    template_name = template_name or DEFAULT_PLAN_TEMPLATE
    if template_name == "hello_world":
        return build_hello_world_payload(to)

    lang_code = lang if lang in ("en", "te", "hi", "ta") else "en"

    if isinstance(parameters, (list, tuple)):
        param_list = [{"type": "text", "text": str(p)} for p in parameters]
    else:
        param_list = [{"type": "text", "text": str(parameters or "")}]

    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": clean_phone(to),
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": lang_code},
            "components": [
                {
                    "type": "body",
                    "parameters": param_list,
                }
            ],
        },
    }


# ---------------------------------------------------------------- Deduplication
def _dedup_key(to: str, template_name: str, payload: dict) -> str:
    content = json.dumps(payload.get("template", {}), sort_keys=True)
    return hashlib.sha256(f"{clean_phone(to)}|{template_name}|{content}".encode()).hexdigest()


def is_duplicate(to: str, template_name: str, payload: dict, now: Optional[float] = None) -> bool:
    now = time.time() if now is None else now
    key = _dedup_key(to, template_name, payload)
    # Purge old entries
    expired = [k for k, ts in _recent_dispatches.items() if now - ts > DEDUP_WINDOW_SECONDS]
    for k in expired:
        _recent_dispatches.pop(k, None)
    if key in _recent_dispatches and now - _recent_dispatches[key] < DEDUP_WINDOW_SECONDS:
        return True
    return False


def record_dispatch(to: str, template_name: str, payload: dict, now: Optional[float] = None) -> None:
    now = time.time() if now is None else now
    key = _dedup_key(to, template_name, payload)
    _recent_dispatches[key] = now


# ---------------------------------------------------------------- Core HTTP Sender
def _http_request(url: str, headers: dict, data: bytes, timeout: float = 10.0) -> Tuple[int, str]:
    """Sends HTTP POST request; returns (status_code, body_string).
    Never raises on HTTP 4xx/5xx errors, only on network failures."""
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def send_whatsapp_message(
    to: str,
    payload: dict,
    env: Optional[Dict[str, str]] = None,
    timeout: float = 10.0,
    check_dedup: bool = True,
) -> Tuple[bool, str, Optional[str]]:
    """Sends a WhatsApp message using Meta Cloud API.

    CRITICAL REQUIREMENTS VERIFIED:
    1. Uses the Phone Number ID endpoint:
       https://graph.facebook.com/{version}/{phone_number_id}/messages
    2. Validates ONLY WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID.
    3. WHATSAPP_BUSINESS_ACCOUNT_ID is NOT required and never validated.
    4. Never logs the access token.
    5. Returns (success: bool, detail: str, message_id: str | None).
    """
    cfg = get_config(env)
    token = cfg["token"]
    phone_id = cfg["phone_number_id"]
    version = cfg["graph_api_version"]

    if not token:
        return False, "meta not configured: missing WHATSAPP_TOKEN", None
    if not phone_id:
        return False, "meta not configured: missing WHATSAPP_PHONE_NUMBER_ID", None

    template_name = payload.get("template", {}).get("name", "unknown")

    if check_dedup and is_duplicate(to, template_name, payload):
        log.warning("Duplicate WhatsApp notification suppressed for recipient %s", to[:4] + "***")
        return True, "duplicate suppressed (already sent within 30s)", None

    url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body_bytes = json.dumps(payload).encode("utf-8")

    try:
        status, resp_text = _http_request(url, headers, body_bytes, timeout=timeout)
    except Exception as e:
        log.error("Network error communicating with Meta WhatsApp API: %s: %s", type(e).__name__, e)
        return False, f"network error: {type(e).__name__}: {e}", None

    if status < 300:
        message_id = None
        try:
            parsed = json.loads(resp_text)
            msgs = parsed.get("messages") or []
            if msgs and isinstance(msgs, list) and "id" in msgs[0]:
                message_id = msgs[0]["id"]
        except Exception:
            pass
        if check_dedup:
            record_dispatch(to, template_name, payload)
        detail = f"accepted (message id: {message_id})" if message_id else "sent"
        return True, detail, message_id

    # Parse error response from Meta
    err_detail = ""
    try:
        parsed = json.loads(resp_text)
        err = parsed.get("error", {})
        if isinstance(err, dict):
            err_code = err.get("code")
            err_subcode = err.get("error_subcode")
            err_msg = err.get("message")
            user_msg = err.get("error_user_msg") or (err.get("error_data") or {}).get("details")
            msg_str = user_msg or err_msg or resp_text[:160]
            parts = []
            if err_code is not None:
                parts.append(f"code {err_code}")
            if err_subcode is not None:
                parts.append(f"subcode {err_subcode}")
            code_str = f" [{', '.join(parts)}]" if parts else ""
            err_detail = f"meta {status}{code_str}: {msg_str}"
        elif isinstance(err, str):
            err_detail = f"meta {status}: {err}"
    except Exception:
        err_detail = f"meta {status}: {resp_text[:160]}"

    log.error("Meta WhatsApp Cloud API error: %s", err_detail)
    return False, err_detail, None


# ---------------------------------------------------------------- High-Level Notification Helpers
def send_otp(
    to: str,
    code: str,
    lang: str = "en",
    env: Optional[Dict[str, str]] = None,
) -> Tuple[bool, str, Optional[str]]:
    """Sends OTP verification code via Authentication template (no WABA ID required)."""
    cfg = get_config(env)
    payload = build_otp_payload(
        to=to,
        code=code,
        lang=lang,
        template_name=cfg["otp_template"],
        button_type=cfg["otp_button"],
    )
    return send_whatsapp_message(to, payload, env=env)


def send_plan_update(
    to: str,
    message: str,
    lang: str = "en",
    env: Optional[Dict[str, str]] = None,
) -> Tuple[bool, str, Optional[str]]:
    """Sends plan update message using the configured utility template."""
    cfg = get_config(env)
    payload = build_utility_payload(
        to=to,
        parameters=message,
        lang=lang,
        template_name=cfg["plan_template"],
    )
    return send_whatsapp_message(to, payload, env=env)


def send_plan_activation(
    to: str,
    customer_name: str,
    plan_name: str,
    valid_until: str,
    lang: str = "en",
    env: Optional[Dict[str, str]] = None,
) -> Tuple[bool, str, Optional[str]]:
    """Sends plan activation notification with multi-variable parameters:
    Hello {{1}}, Your FarmRoute plan has been successfully activated. Plan: {{2}}, Valid Until: {{3}}"""
    cfg = get_config(env)
    params = [customer_name, plan_name, valid_until]
    payload = build_utility_payload(to, params, lang=lang, template_name=cfg["plan_template"])
    return send_whatsapp_message(to, payload, env=env)


def send_subscription_renewal(
    to: str,
    customer_name: str,
    plan_name: str,
    valid_until: str,
    lang: str = "en",
    env: Optional[Dict[str, str]] = None,
) -> Tuple[bool, str, Optional[str]]:
    """Sends subscription renewal notification."""
    cfg = get_config(env)
    params = [customer_name, plan_name, valid_until]
    payload = build_utility_payload(to, params, lang=lang, template_name=cfg["plan_template"])
    return send_whatsapp_message(to, payload, env=env)


def send_payment_confirmation(
    to: str,
    customer_name: str,
    amount: str,
    plan_name: str,
    lang: str = "en",
    env: Optional[Dict[str, str]] = None,
) -> Tuple[bool, str, Optional[str]]:
    """Sends payment confirmation notification."""
    cfg = get_config(env)
    params = [customer_name, amount, plan_name]
    payload = build_utility_payload(to, params, lang=lang, template_name=cfg["plan_template"])
    return send_whatsapp_message(to, payload, env=env)


def send_subscription_update(
    to: str,
    customer_name: str,
    status: str,
    details: str,
    lang: str = "en",
    env: Optional[Dict[str, str]] = None,
) -> Tuple[bool, str, Optional[str]]:
    """Sends general subscription status update."""
    cfg = get_config(env)
    params = [customer_name, status, details]
    payload = build_utility_payload(to, params, lang=lang, template_name=cfg["plan_template"])
    return send_whatsapp_message(to, payload, env=env)


# ---------------------------------------------------------------- Webhook Handlers
def verify_webhook(
    mode: Optional[str],
    verify_token: Optional[str],
    challenge: Optional[str],
    env: Optional[Dict[str, str]] = None,
) -> Tuple[bool, str]:
    """Verifies incoming Meta WhatsApp webhook subscription."""
    cfg = get_config(env)
    expected_token = cfg["webhook_verify_token"]
    if mode == "subscribe" and verify_token == expected_token:
        return True, str(challenge or "")
    return False, "Verification token mismatch or invalid mode"


def process_webhook_event(data: dict) -> List[Dict[str, Any]]:
    """Processes incoming Meta WhatsApp webhook status updates.
    Handles 'sent', 'delivered', 'read', 'failed'.
    Filters out duplicate status notifications."""
    updates = []
    now = time.time()
    entries = data.get("entry") or []
    for entry in entries:
        changes = entry.get("changes") or []
        for change in changes:
            value = change.get("value") or {}
            statuses = value.get("statuses") or []
            for st in statuses:
                msg_id = st.get("id")
                status_name = st.get("status")
                recipient = st.get("recipient_id")
                ts = float(st.get("timestamp") or now)

                if not msg_id or not status_name:
                    continue

                event_key = f"{msg_id}:{status_name}"
                # Duplicate prevention: ignore if already processed
                if event_key in _processed_webhook_events:
                    continue

                error_info = None
                errors = st.get("errors") or []
                if errors and isinstance(errors, list):
                    err = errors[0]
                    error_info = {
                        "code": err.get("code"),
                        "title": err.get("title"),
                        "details": err.get("error_data", {}).get("details"),
                    }

                event_record = {
                    "message_id": msg_id,
                    "status": status_name,
                    "recipient_id": recipient,
                    "timestamp": ts,
                    "error": error_info,
                    "processed_at": now,
                }
                _processed_webhook_events[event_key] = event_record
                updates.append(event_record)
                log.info("WhatsApp status updated: %s -> %s (recipient %s)", msg_id, status_name, recipient)

    return updates


def get_stored_statuses(limit: int = 25) -> List[Dict[str, Any]]:
    """Returns recently received webhook delivery statuses."""
    items = list(_processed_webhook_events.values())
    items.sort(key=lambda x: x["processed_at"], reverse=True)
    return items[:limit]


# ---------------------------------------------------------------- Health Check
def get_health_status(env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Returns safe configuration info without exposing credentials."""
    cfg = get_config(env)
    return {
        "configured": cfg["configured"],
        "phoneNumberIdConfigured": bool(cfg["phone_number_id"]),
        "tokenConfigured": bool(cfg["token"]),
        "otpTemplateConfigured": bool(cfg["otp_template"]),
        "planTemplateConfigured": bool(cfg["plan_template"]),
        "wabaIdRequiredForSending": False,
        "graphApiVersion": cfg["graph_api_version"],
        "phoneNumberId": cfg["phone_number_id"] or None,
        "provider": "meta",
        "live": bool(cfg["configured"]),
    }
