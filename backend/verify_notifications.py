"""
verify_notifications.py
-----------------------
Independent CLI verification script for FarmRoute Optimizer SMS & WhatsApp notifications.
Diagnoses each layer of the notification pipeline in order:
  Step 1: Environment configuration and provider detection
  Step 2: SMS provider test
  Step 3: WhatsApp Cloud API / Twilio WhatsApp test
  Step 4: OTP generation, dual-channel dispatch, and verification
  Step 5: Plan update notification dispatch
"""

import argparse
import json
import os
import sys
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(__file__))

import notify
import phones
import auth


def print_header(title):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def step1_check_environment():
    print_header("Step 1: Environment & Provider Configuration")
    channels = notify.otp_channels()
    providers = notify.describe_providers()
    otp_channel_env = os.environ.get("OTP_CHANNEL", "both")

    print(f"  OTP_CHANNEL env value: {otp_channel_env}")
    print(f"  Configured OTP Channels: {channels}")
    print(f"  SMS Provider: {providers['sms']['provider']} (live={providers['sms']['live']})")
    if providers["sms"]["problem"]:
        print(f"    WARNING: SMS misconfigured -> {providers['sms']['problem']}")
    print(f"  WhatsApp Provider: {providers['whatsapp']['provider']} (live={providers['whatsapp']['live']})")
    if providers["whatsapp"]["problem"]:
        print(f"    WARNING: WhatsApp misconfigured -> {providers['whatsapp']['problem']}")

    print(f"  Default Country Code: {notify.default_cc()}")
    print(f"  Demo Show OTP: {phones.demo_show_otp()}")

    both_ok = "sms" in channels and "whatsapp" in channels
    print(f"\n  [RESULT] Dual-channel OTP configuration: {'PASS' if both_ok else 'WARN (Single channel)'}")
    return providers


def step2_test_sms(recipient):
    print_header("Step 2: SMS Provider Independent Test")
    provider = notify.get_provider("sms")
    print(f"  Provider: {provider.name} (live={provider.live})")
    print(f"  Recipient: {notify.mask_phone(recipient)}")

    test_msg = "Farmroute test: SMS provider verification successful."
    try:
        ok, detail = provider.send(recipient, test_msg, "en", "update")
        print(f"  Send Result: {'SUCCESS' if ok else 'FAILED'}")
        print(f"  Provider Response: {detail}")
        return ok, detail
    except Exception as e:
        print(f"  Send Exception: {type(e).__name__}: {e}")
        return False, str(e)


def step3_test_whatsapp(recipient):
    print_header("Step 3: WhatsApp Provider Independent Test")
    provider = notify.get_provider("whatsapp")
    print(f"  Provider: {provider.name} (live={provider.live})")
    print(f"  Recipient: {notify.mask_phone(recipient)}")
    if provider.name == "meta":
        print(f"  Meta Phone ID: {getattr(provider, 'phone_id', 'N/A')}")
        print(f"  Meta Version: {getattr(provider, 'version', 'N/A')}")
        print(f"  Meta Template: {getattr(provider, 'template', 'N/A')}")
        print(f"  Meta OTP Template: {getattr(provider, 'otp_template', 'N/A')}")

    test_msg = "Farmroute test: WhatsApp provider verification successful."
    try:
        ok, detail = provider.send(recipient, test_msg, "en", "update")
        print(f"  Send Result: {'SUCCESS' if ok else 'FAILED'}")
        print(f"  Provider Response: {detail}")
        return ok, detail
    except Exception as e:
        print(f"  Send Exception: {type(e).__name__}: {e}")
        return False, str(e)


def step4_test_otp_flow(recipient):
    print_header("Step 4: Dual-Channel OTP Generation & Verification")
    norm_phone = notify.normalize_phone(recipient)
    code = notify.new_otp()
    key = b"test-key"
    digest = notify.otp_digest(999, norm_phone, code, key)

    print(f"  Normalized Recipient: {notify.mask_phone(norm_phone)}")
    print(f"  Generated OTP Code: {code}")
    print(f"  Keyed Digest: {digest[:16]}...")

    channels = notify.otp_channels()
    results = {}
    for ch in channels:
        p = notify.get_provider(ch)
        msg = notify.compose_otp_message(code, "en")
        try:
            ok, detail = p.send(norm_phone, msg, "en", "otp")
        except Exception as e:
            ok, detail = False, f"{type(e).__name__}: {e}"
        results[ch] = (ok, detail, p.name)
        print(f"  Channel [{ch.upper()}] via {p.name}: {'SUCCESS' if ok else 'FAILED'} -> {detail}")

    any_success = any(r[0] for r in results.values())
    both_success = len(results) == 2 and all(r[0] for r in results.values())
    print(f"\n  [RESULT] Dual-channel OTP dispatch: {'BOTH SUCCEEDED' if both_success else 'PARTIAL' if any_success else 'FAILED'}")

    # Test verification
    good = auth.verify_pin(code, auth.hash_pin(code))
    print(f"  OTP Verification algorithm: {'PASS' if good else 'FAIL'}")
    return results


def step5_test_plan_update(recipient):
    print_header("Step 5: Plan Update Notification on Both Channels")
    norm_phone = notify.normalize_phone(recipient)
    sample_card = {
        "farmer_id": 999, "crop": "tomato", "qty_kg": 500, "status": "hauled", "changed": ["pickup moved"],
        "trip": {"pickup_eta": "10:30", "mandis": [{"id": 1}]},
        "payout": {"total_inr": 15000.0}, "doorstep_per_kg": 25.0
    }
    for lang in ("en", "te", "hi", "ta"):
        text = notify.compose_plan_message(sample_card, lang, "changed")
        print(f"  Sample message [{lang}]: {text}")

    sms, wa = notify.get_provider("sms"), notify.get_provider("whatsapp")
    msg_en = notify.compose_plan_message(sample_card, "en", "changed")
    print("\n  Dispatching to SMS...")
    ok_sms, det_sms = sms.send(norm_phone, msg_en, "en", "changed")
    print(f"    SMS Result: {'SUCCESS' if ok_sms else 'FAILED'} -> {det_sms}")

    print("  Dispatching to WhatsApp...")
    ok_wa, det_wa = wa.send(norm_phone, msg_en, "en", "changed")
    print(f"    WhatsApp Result: {'SUCCESS' if ok_wa else 'FAILED'} -> {det_wa}")

    return ok_sms and ok_wa


def main():
    parser = argparse.ArgumentParser(description="FarmRoute Optimizer Notification Flow Verification")
    parser.add_argument("--phone", default="+919876543210", help="Recipient phone number for test (E.164)")
    args = parser.parse_args()

    print("\nStarting FarmRoute Optimizer Notification Verification Suite")
    step1_check_environment()
    step2_test_sms(args.phone)
    step3_test_whatsapp(args.phone)
    step4_test_otp_flow(args.phone)
    step5_test_plan_update(args.phone)
    print("\n" + "=" * 70)
    print("  Verification Suite Run Complete")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
