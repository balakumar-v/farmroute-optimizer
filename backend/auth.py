"""
auth.py -- who may call what.

Three kinds of caller, kept apart on purpose:
  * admin   one shared secret, env ADMIN_TOKEN, sent as "Authorization: Bearer ...". Every route that is not
            under /farmer/ requires it (default-deny: a route added later is protected without anyone remembering).
  * farmer  farmer id + 6-digit PIN -> a signed 12-hour token that is only good for GET /farmer/me. The PIN is
            stored as a salted scrypt hash, five wrong guesses lock that farmer for 15 minutes, and issuing a
            new PIN cancels every token issued under the old one.
  * nobody  /docs and /openapi.json (served by FastAPI itself).

If ADMIN_TOKEN is NOT set the admin routes stay open (local development), and the farmer routes refuse to work
(503): farmers must never be reachable on a backend whose admin routes are open by accident. Running with open
admin routes AND the farmer portal is possible only on purpose, with ADMIN_AUTH=off (demos, early pilots). While
that is set, anyone who can reach the backend can read all data, reset it, and issue a PIN for any farmer, which
means logging in as that farmer. Turn it back on (remove ADMIN_AUTH, set ADMIN_TOKEN) before real farmers use it.

Known limits, deliberately not hidden: lockout is per farmer, so someone who knows an id can lock that farmer out
for 15 minutes (an admin re-issuing the PIN clears it); there is no per-IP limit because behind Render's proxy
every caller shares one address; tokens cannot be revoked one by one before they expire except by re-issuing
that farmer's PIN.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from fastapi import HTTPException, Request

from database import get_conn

TOKEN_TTL_S = 12 * 3600
MAX_FAILED = 5
LOCK_S = 15 * 60
PIN_DIGITS = 6
FARMER_PREFIX = "/farmer/"
_SCRYPT = dict(n=2 ** 14, r=8, p=1, dklen=32)

_process_secret = None


# ---------------------------------------------------------------- admin
def admin_configured() -> bool:
    return bool(os.environ.get("ADMIN_TOKEN", ""))


def admin_auth_off() -> bool:
    """ADMIN_AUTH=off: the operator chose open admin routes. The only way to combine them with the farmer portal."""
    return os.environ.get("ADMIN_AUTH", "on").strip().lower() == "off"


def _bearer(request: Request):
    h = request.headers.get("authorization", "")
    return h[7:].strip() if h.lower().startswith("bearer ") else None


def admin_guard(request: Request) -> None:
    """App-wide dependency: everything except the farmer routes needs the admin token (when one is set)."""
    if request.url.path.startswith(FARMER_PREFIX) or admin_auth_off():
        return
    expected = os.environ.get("ADMIN_TOKEN", "")
    if not expected:
        return
    got = _bearer(request)
    if not got or not hmac.compare_digest(got.encode(), expected.encode()):
        raise HTTPException(401, "Admin token required.", headers={"WWW-Authenticate": "Bearer"})


# ---------------------------------------------------------------- PINs
def generate_pin() -> str:
    return f"{secrets.randbelow(10 ** PIN_DIGITS):0{PIN_DIGITS}d}"


def hash_pin(pin: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(pin.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${dk.hex()}"


def verify_pin(pin: str, stored: str) -> bool:
    try:
        _, salt, dk = stored.split("$")
        got = hashlib.scrypt(pin.encode(), salt=bytes.fromhex(salt), **_SCRYPT)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, bytes.fromhex(dk))


_dummy_hash = None


def _dummy() -> str:
    """Hash checked when the farmer id is unknown, so 'no such farmer' and 'wrong PIN' take the same time."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_pin("000000")
    return _dummy_hash


def set_pin(conn, farmer_id: int) -> str:
    """Issues a fresh PIN (replacing any old one, clearing any lockout). Returns it once; only the hash is kept.
    The caller commits."""
    pin = generate_pin()
    conn.execute(
        "INSERT INTO farmer_credentials (farmer_id, pin_hash, failed_attempts, locked_until, created_at) "
        "VALUES (%s, %s, 0, 0, %s) ON CONFLICT (farmer_id) DO UPDATE SET pin_hash = EXCLUDED.pin_hash, "
        "failed_attempts = 0, locked_until = 0, created_at = EXCLUDED.created_at",
        (farmer_id, hash_pin(pin), time.time()))
    return pin


# ---------------------------------------------------------------- tokens
def _key() -> bytes:
    global _process_secret
    env = os.environ.get("FARMROUTE_SECRET", "")
    if env:
        return env.encode()
    if _process_secret is None:       # tokens then stop working on restart, and across several workers
        _process_secret = secrets.token_bytes(32)
    return _process_secret


def fingerprint(pin_hash: str) -> str:
    return hashlib.sha256(pin_hash.encode()).hexdigest()[:12]


def make_token(farmer_id: int, pin_hash: str, ttl_s: int = TOKEN_TTL_S, now=None) -> str:
    body = base64.urlsafe_b64encode(json.dumps(
        {"f": farmer_id, "e": int((now or time.time()) + ttl_s), "k": fingerprint(pin_hash)}).encode()).decode()
    sig = hmac.new(_key(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def parse_token(token: str):
    """The payload if the signature is valid and the token has not expired, else None."""
    try:
        body, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(sig, hmac.new(_key(), body.encode(), hashlib.sha256).hexdigest()):
            return None
        payload = json.loads(base64.urlsafe_b64decode(body.encode()))
        return payload if payload["e"] > time.time() and isinstance(payload["f"], int) else None
    except (ValueError, KeyError, TypeError):
        return None


# ---------------------------------------------------------------- farmer login and identity
def _require_configured():
    if not (admin_configured() or admin_auth_off()):
        raise HTTPException(503, "Farmer access is disabled until ADMIN_TOKEN is set on the backend.")


def login(farmer_id: int, pin: str) -> str:
    _require_configured()
    now = time.time()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM farmer_credentials WHERE farmer_id = %s FOR UPDATE",
                           (farmer_id,)).fetchone()
        if row is None:
            verify_pin(pin, _dummy())
            raise HTTPException(401, "Wrong farmer ID or PIN.")
        if row["locked_until"] > now:
            raise HTTPException(429, "Too many wrong PINs. Try again later or ask your FPO for a new PIN.",
                                headers={"Retry-After": str(int(row["locked_until"] - now) + 1)})
        if verify_pin(pin, row["pin_hash"]):
            conn.execute("UPDATE farmer_credentials SET failed_attempts = 0, locked_until = 0 WHERE farmer_id = %s",
                         (farmer_id,))
            conn.commit()
            return make_token(farmer_id, row["pin_hash"])
        failed = row["failed_attempts"] + 1
        lock = failed >= MAX_FAILED
        conn.execute("UPDATE farmer_credentials SET failed_attempts = %s, locked_until = %s WHERE farmer_id = %s",
                     (0 if lock else failed, now + LOCK_S if lock else 0, farmer_id))
        conn.commit()
    if lock:
        raise HTTPException(429, "Too many wrong PINs. Try again later or ask your FPO for a new PIN.",
                            headers={"Retry-After": str(LOCK_S)})
    raise HTTPException(401, "Wrong farmer ID or PIN.")


def current_farmer(request: Request) -> int:
    """Dependency for farmer routes: the id inside a valid, still-current farmer token. Nothing else in the
    request (query, path, body) can choose which farmer's data comes back."""
    _require_configured()
    tok = _bearer(request)
    payload = parse_token(tok) if tok else None
    if payload is None:
        raise HTTPException(401, "Please log in again.", headers={"WWW-Authenticate": "Bearer"})
    with get_conn() as conn:
        row = conn.execute("SELECT pin_hash FROM farmer_credentials WHERE farmer_id = %s",
                           (payload["f"],)).fetchone()
    if row is None or not hmac.compare_digest(fingerprint(row["pin_hash"]), payload["k"]):
        raise HTTPException(401, "Please log in again.", headers={"WWW-Authenticate": "Bearer"})
    return payload["f"]
