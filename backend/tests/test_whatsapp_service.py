"""
test_whatsapp_service.py
========================
Automated test suite for FarmRoute's Meta WhatsApp Cloud API integration:
- Confirms messages are sent WITHOUT requiring WHATSAPP_BUSINESS_ACCOUNT_ID (WABA ID).
- Checks dedicated hello_world payload builder.
- Checks Authentication template (body code + copy-code button).
- Checks Utility template (single & multi-variable parameters).
- Checks deduplication cache (30-second window).
- Checks Meta API error handling (401 token expired, missing credentials, etc.).
- Checks webhook verification and status event parsing.
- Checks health check endpoint reporting WABA ID not required.
- Checks FastAPI endpoints.
"""

import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import whatsapp_service as ws


# ------------------------------------------------------------------------------
# 1. Configuration & WABA ID Non-Requirement Tests
# ------------------------------------------------------------------------------

def test_waba_id_strictly_optional_and_not_required(monkeypatch):
    """
    Ensure the WhatsApp service operates using ONLY:
      - WHATSAPP_TOKEN
      - WHATSAPP_PHONE_NUMBER_ID
      - WHATSAPP_GRAPH_API_VERSION
    and explicitly succeeds when WHATSAPP_BUSINESS_ACCOUNT_ID is unset or None.
    """
    monkeypatch.setenv("WHATSAPP_TOKEN", "mock_valid_token_123")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "123456789012345")
    monkeypatch.setenv("WHATSAPP_GRAPH_API_VERSION", "v20.0")
    monkeypatch.delenv("WHATSAPP_BUSINESS_ACCOUNT_ID", raising=False)

    cfg = ws.get_config()
    assert cfg["token"] == "mock_valid_token_123"
    assert cfg["phone_number_id"] == "123456789012345"
    assert cfg["graph_api_version"] == "v20.0"
    assert cfg["waba_id"] is None
    assert cfg["waba_id_required_for_sending"] is False

    mock_resp_json = {
        "messaging_product": "whatsapp",
        "contacts": [{"input": "919876543210", "wa_id": "919876543210"}],
        "messages": [{"id": "wamid.HBgNNzk4NzY1NDMyMTA="}]
    }

    payload = ws.build_hello_world_payload("+919876543210")

    with patch("whatsapp_service._http_request") as mock_http:
        mock_http.return_value = (200, json.dumps(mock_resp_json))

        ok, detail, msg_id = ws.send_whatsapp_message(
            to="+919876543210",
            payload=payload,
            check_dedup=False
        )

        assert ok is True
        assert msg_id == "wamid.HBgNNzk4NzY1NDMyMTA="
        assert "accepted" in detail

        # Verify the called URL used the phone_number_id directly
        called_url = mock_http.call_args[0][0]
        assert called_url == "https://graph.facebook.com/v20.0/123456789012345/messages"
        called_headers = mock_http.call_args[0][1]
        assert called_headers["Authorization"] == "Bearer mock_valid_token_123"
        assert called_headers["Content-Type"] == "application/json"


def test_missing_credentials_fails_gracefully(monkeypatch):
    """Missing token or phone number id must return a graceful failure tuple (False, detail, None)."""
    monkeypatch.delenv("WHATSAPP_TOKEN", raising=False)
    monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID", raising=False)
    monkeypatch.delenv("WHATSAPP_PHONE_ID", raising=False)

    payload = ws.build_hello_world_payload("+919876543210")
    ok, detail, msg_id = ws.send_whatsapp_message(to="+919876543210", payload=payload, check_dedup=False)
    assert ok is False
    assert "missing WHATSAPP_TOKEN" in detail
    assert msg_id is None


# ------------------------------------------------------------------------------
# 2. Template Payload Builders Tests
# ------------------------------------------------------------------------------

def test_build_hello_world_payload():
    """hello_world must NOT include components or parameters; language must be en_US."""
    payload = ws.build_hello_world_payload("919876543210")
    assert payload["messaging_product"] == "whatsapp"
    assert payload["to"] == "919876543210"
    assert payload["type"] == "template"
    assert payload["template"]["name"] == "hello_world"
    assert payload["template"]["language"]["code"] == "en_US"
    assert "components" not in payload["template"]


def test_build_authentication_otp_payload():
    """Authentication OTP template must supply body parameter and copy_code button parameter."""
    payload = ws.build_otp_payload(
        to="919876543210",
        code="482910",
        lang="en",
        template_name="farmroute_otp",
        button_type="copy_code"
    )

    template = payload["template"]
    assert template["name"] == "farmroute_otp"
    assert template["language"]["code"] == "en"

    components = template["components"]
    body_comp = next((c for c in components if c["type"] == "body"), None)
    assert body_comp is not None
    assert body_comp["parameters"] == [{"type": "text", "text": "482910"}]

    btn_comp = next((c for c in components if c["type"] == "button"), None)
    assert btn_comp is not None
    assert btn_comp["sub_type"] == "url"
    assert btn_comp["index"] == "0"
    assert btn_comp["parameters"] == [{"type": "text", "text": "482910"}]


def test_build_utility_plan_update_payload_single_parameter():
    """Single body variable utility plan update."""
    payload = ws.build_utility_payload(
        to="919876543210",
        parameters="Your tomato pickup is confirmed for tomorrow 7:00 AM.",
        lang="en",
        template_name="farmroute_plan_update"
    )
    template = payload["template"]
    assert template["name"] == "farmroute_plan_update"
    body_comp = template["components"][0]
    assert body_comp["type"] == "body"
    assert body_comp["parameters"][0]["text"] == "Your tomato pickup is confirmed for tomorrow 7:00 AM."


def test_build_utility_plan_update_payload_multi_variables():
    """Multi-variable utility template: Hello {{1}}, Plan {{2}}, Valid Until {{3}}."""
    payload = ws.build_utility_payload(
        to="919876543210",
        parameters=["Ramesh Kumar", "Kharif Premium Route", "31-Dec-2026"],
        lang="en",
        template_name="farmroute_plan_update"
    )
    template = payload["template"]
    body_comp = template["components"][0]
    assert len(body_comp["parameters"]) == 3
    assert body_comp["parameters"][0]["text"] == "Ramesh Kumar"
    assert body_comp["parameters"][1]["text"] == "Kharif Premium Route"
    assert body_comp["parameters"][2]["text"] == "31-Dec-2026"


# ------------------------------------------------------------------------------
# 3. Deduplication Cache Tests
# ------------------------------------------------------------------------------

def test_deduplication_cache(monkeypatch):
    """Identical recipient and message within 30s must be suppressed."""
    ws._recent_dispatches.clear()
    monkeypatch.setenv("WHATSAPP_TOKEN", "mock_token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "123456789012345")

    with patch("whatsapp_service._http_request") as mock_http:
        mock_http.return_value = (200, json.dumps({"messages": [{"id": "wamid.123"}]}))

        # First send -> success
        ok1, detail1, id1 = ws.send_otp(to="+919876543210", code="123456")
        assert ok1 is True
        assert id1 == "wamid.123"
        assert mock_http.call_count == 1

        # Second send immediately with same phone & OTP -> duplicate suppressed
        ok2, detail2, id2 = ws.send_otp(to="+919876543210", code="123456")
        assert ok2 is True
        assert "duplicate suppressed" in detail2
        # Network request should not have been called again
        assert mock_http.call_count == 1

        # Third send with different OTP -> sent
        ok3, detail3, id3 = ws.send_otp(to="+919876543210", code="654321")
        assert ok3 is True
        assert "duplicate" not in detail3
        assert mock_http.call_count == 2


# ------------------------------------------------------------------------------
# 4. Meta Error Parsing Tests
# ------------------------------------------------------------------------------

def test_meta_http_error_parsing(monkeypatch):
    """Meta Graph API errors like 401 Authentication Error must parse code, subcode, and message."""
    monkeypatch.setenv("WHATSAPP_TOKEN", "expired_token_xyz")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "123456789012345")

    error_body = json.dumps({
        "error": {
            "message": "Error validating access token: Session has expired",
            "type": "OAuthException",
            "code": 190,
            "error_subcode": 463,
            "fbtrace_id": "ABcDeFgHiJk"
        }
    })

    with patch("whatsapp_service._http_request") as mock_http:
        mock_http.return_value = (401, error_body)

        payload = ws.build_hello_world_payload("+919876543210")
        ok, detail, msg_id = ws.send_whatsapp_message(to="+919876543210", payload=payload, check_dedup=False)

        assert ok is False
        assert msg_id is None
        assert "meta 401" in detail
        assert "code 190" in detail
        assert "subcode 463" in detail
        assert "Session has expired" in detail
        # Ensure raw token is never leaked in detail string
        assert "expired_token_xyz" not in detail


# ------------------------------------------------------------------------------
# 5. Webhook Verification & Event Processing Tests
# ------------------------------------------------------------------------------

def test_verify_webhook_handshake(monkeypatch):
    """Hub verification handshake for Meta Webhook setup."""
    monkeypatch.setenv("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "secret_verify_token_123")

    # Correct mode and token
    is_valid, challenge = ws.verify_webhook(
        mode="subscribe",
        verify_token="secret_verify_token_123",
        challenge="1158201444"
    )
    assert is_valid is True
    assert challenge == "1158201444"

    # Wrong token
    is_valid_wrong, err_msg = ws.verify_webhook(
        mode="subscribe",
        verify_token="wrong_token",
        challenge="1158201444"
    )
    assert is_valid_wrong is False

    # Wrong mode
    is_valid_mode, err_msg2 = ws.verify_webhook(
        mode="publish",
        verify_token="secret_verify_token_123",
        challenge="1158201444"
    )
    assert is_valid_mode is False


def test_process_webhook_status_events():
    """Webhook event parsing for sent, delivered, read, and failed statuses."""
    ws._processed_webhook_events.clear()

    event_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "100000000000",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15551234567",
                                "phone_number_id": "123456789012345"
                            },
                            "statuses": [
                                {
                                    "id": "wamid.HBgNNzk4NzY1NDMyMTA=",
                                    "status": "delivered",
                                    "timestamp": "1731050000",
                                    "recipient_id": "919876543210"
                                },
                                {
                                    "id": "wamid.HBgNNzk4NzY1NDMyMTB=",
                                    "status": "failed",
                                    "timestamp": "1731050010",
                                    "recipient_id": "919876543211",
                                    "errors": [
                                        {
                                            "code": 131030,
                                            "title": "Recipient phone number not in allowed list"
                                        }
                                    ]
                                }
                            ]
                        },
                        "field": "messages"
                    }
                ]
            }
        ]
    }

    statuses = ws.process_webhook_event(event_payload)
    assert len(statuses) == 2

    assert statuses[0]["message_id"] == "wamid.HBgNNzk4NzY1NDMyMTA="
    assert statuses[0]["status"] == "delivered"
    assert statuses[0]["recipient_id"] == "919876543210"

    assert statuses[1]["message_id"] == "wamid.HBgNNzk4NzY1NDMyMTB="
    assert statuses[1]["status"] == "failed"
    assert statuses[1]["error"]["code"] == 131030
    assert "Recipient phone number not in allowed list" in statuses[1]["error"]["title"]


def test_health_status_reports_waba_not_required(monkeypatch):
    """Health check explicitly states WABA ID is not required for sending messages."""
    monkeypatch.setenv("WHATSAPP_TOKEN", "dummy_token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "123456789012345")

    status = ws.get_health_status()
    assert status["configured"] is True
    assert status["wabaIdRequiredForSending"] is False
    assert status["phoneNumberId"] == "123456789012345"


# ------------------------------------------------------------------------------
# 6. FastAPI Webhook & Health Endpoints Tests
# ------------------------------------------------------------------------------

def test_fastapi_endpoints(monkeypatch):
    """Verify FastAPI public webhook verification and health endpoints without admin auth."""
    from fastapi.testclient import TestClient
    import main as main_module

    client = TestClient(main_module.app)

    # 1. Health endpoint (public)
    resp = client.get("/api/whatsapp/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["wabaIdRequiredForSending"] is False

    # 2. Webhook verification GET challenge
    monkeypatch.setenv("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "verify_secret_456")
    verify_resp = client.get(
        "/api/whatsapp/webhook?hub.mode=subscribe&hub.challenge=test_challenge_num_789&hub.verify_token=verify_secret_456"
    )
    assert verify_resp.status_code == 200
    assert verify_resp.text == "test_challenge_num_789"

    # 3. Webhook verification with invalid token -> 403
    bad_verify = client.get(
        "/api/whatsapp/webhook?hub.mode=subscribe&hub.challenge=test_challenge_num_789&hub.verify_token=wrong_secret"
    )
    assert bad_verify.status_code == 403
