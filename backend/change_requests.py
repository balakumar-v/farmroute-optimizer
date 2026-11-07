"""
change_requests.py -- farmer change requests: what the LLM may say, how it is checked, and where requests live.

The flow (routes are in main.py):

  farmer message --LLM--> ChangeParse --resolve()--> absolute new values --> 'draft' row
      --farmer taps Confirm--> 'pending' --admin preview / approve / reject--> 'approved' | 'rejected'

Rules this module enforces:
  * The LLM only ever produces a ChangeParse (a field, a mode and a number). It never writes SQL and never sees an
    id. Everything that touches the database is a fixed, parameterised query below.
  * The LLM does no arithmetic. "100 kg less" arrives as shift -100; resolve() adds it to the farmer's current
    value, rounds, and bounds-checks the result. A hallucinated "99999 kg" dies in resolve(), not in the plan.
  * A request changes only the farmer's own qty_kg / ready_hr / deadline_hr, and only once an admin approves.
  * The farmers table is not touched by drafting, confirming, previewing or rejecting.
"""
import json
import os
import time
from collections import defaultdict, deque
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from advisor import _hhmm

FIELDS = ("qty_kg", "ready_hr", "deadline_hr")
LABEL = {"qty_kg": "Quantity", "ready_hr": "Ready time", "deadline_hr": "Deadline"}
# How different two values must be to count as a change (a farmer typing 342.7 for 342.7384 changed nothing).
_TOL = {"qty_kg": 0.05, "ready_hr": 0.005, "deadline_hr": 0.005}
REASONS = ("too_late", "not_possible", "capacity", "other")
STATUSES = ("draft", "pending", "approved", "rejected", "superseded", "expired", "withdrawn")
DRAFT_TTL_S = 3600


# ---------------------------------------------------------------- settings (env, read at call time)
def max_qty_kg() -> float:
    return float(os.environ.get("CHANGE_MAX_QTY_KG", "5000"))        # the biggest vehicle in the fleet carries 5000


def max_hour() -> float:
    return float(os.environ.get("CHANGE_MAX_HOUR", "72"))            # planning clock: hours from the start of day


def pending_ttl_s() -> float:
    return float(os.environ.get("CHANGE_REQUEST_TTL_H", "24")) * 3600


def rate_limit_per_hour() -> int:
    return int(os.environ.get("CHAT_RATE_PER_HOUR", "20"))


# ---------------------------------------------------------------- what the LLM (or the form) may send
class Change(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: Literal["qty_kg", "ready_hr", "deadline_hr"]
    mode: Literal["set", "shift", "scale"]      # "make it 400" | "2 hours later" / "100 kg less" | "half"
    value: float = Field(allow_inf_nan=False)

    @model_validator(mode="after")
    def _mode_fits_field(self):
        if self.mode == "scale" and (self.field != "qty_kg" or self.value <= 0):
            raise ValueError("scale is only for qty_kg and must be positive")
        return self


class ChangeParse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    changes: List[Change] = Field(default_factory=list, max_length=3)
    clarify: Optional[str] = Field(default=None, max_length=200)    # a question for the farmer when info is missing


class ChatIn(BaseModel):
    """Farmer app: free text for the LLM, or an already-structured change from the form fallback."""
    message: Optional[str] = Field(default=None, min_length=1, max_length=300)
    structured: Optional[ChangeParse] = None

    @model_validator(mode="after")
    def _exactly_one(self):
        if (self.message is None) == (self.structured is None):
            raise ValueError("send either message or structured")
        if self.message is not None:
            self.message = self.message.strip()
            if not self.message:
                raise ValueError("message is empty")
        return self


class IdsIn(BaseModel):
    ids: List[int] = Field(min_length=1, max_length=50)


class ApproveIn(IdsIn):
    base_plan_id: int       # the published plan the admin previewed against


class RejectIn(BaseModel):
    reason_code: Literal["too_late", "not_possible", "capacity", "other"]


class WindowIn(BaseModel):
    is_open: bool


# ---------------------------------------------------------------- errors (main.py maps them to HTTP)
class ChangeError(ValueError):
    """The request cannot be turned into a valid change. The message is safe to show the farmer. `code` and `params`
    let the farmer app show it in the farmer's own language instead of this English text."""

    def __init__(self, message: str, code: str = "invalid", **params):
        super().__init__(message)
        self.code, self.params = code, params


class RequestNotFound(LookupError):
    """No such request for this farmer (also what someone else's request id looks like)."""


class RequestConflict(Exception):
    """The request is not in a state that allows this, or the world moved since it was made."""


# ---------------------------------------------------------------- resolving a parse against the farmer's row
def fmt_value(field: str, v: float) -> str:
    return f"{round(v, 1):g} kg" if field == "qty_kg" else _hhmm(v)      # 482.954 kg reads as 483 kg


def resolve(parse: ChangeParse, current: dict) -> dict:
    """ChangeParse + the farmer's current values -> {field: new absolute value} for the fields that change.
    Raises ChangeError (farmer-safe text) if the result is not a sensible plan input."""
    if not parse.changes:
        raise ChangeError("Tell me what to change: how many kg you have, or when the produce is ready or must leave.",
                          "empty")
    new, seen = {k: float(current[k]) for k in FIELDS}, set()
    for c in parse.changes:
        if c.field in seen:
            raise ChangeError(f"You gave {LABEL[c.field].lower()} twice. Please send one value for it.", "twice")
        seen.add(c.field)
        base = new[c.field]
        new[c.field] = c.value if c.mode == "set" else base + c.value if c.mode == "shift" else base * c.value
    changed = {}
    for k in FIELDS:
        v = round(new[k], 1 if k == "qty_kg" else 2)
        if abs(v - float(current[k])) >= _TOL[k]:
            changed[k] = v
    final = {k: changed.get(k, float(current[k])) for k in FIELDS}
    if not 0 < final["qty_kg"] <= max_qty_kg():
        raise ChangeError(f"Quantity must be more than 0 and at most {max_qty_kg():g} kg.", "qty_range", max=max_qty_kg())
    if final["ready_hr"] < 0:
        raise ChangeError("The ready time cannot be before the start of the day (00:00).", "ready_neg")
    if final["deadline_hr"] > max_hour():
        raise ChangeError(f"The deadline must be within {max_hour():g} hours of the start of the day.", "deadline_max",
                          max=max_hour())
    if final["ready_hr"] >= final["deadline_hr"]:
        raise ChangeError("The ready time must be earlier than the deadline.", "order")
    if not changed:
        raise ChangeError("That is the same as your current plan, so nothing would change.", "same")
    return changed


def change_lines(current: dict, proposed: dict) -> list:
    """The confirm card, built by code from resolved numbers (the LLM's words are never shown as a result)."""
    return [{"field": k, "label": LABEL[k], "from": fmt_value(k, current[k]), "to": fmt_value(k, proposed[k])}
            for k in FIELDS if k in proposed]


def summary(current: dict, proposed: dict) -> str:
    return "; ".join(f"{c['label']}: {c['from']} -> {c['to']}" for c in change_lines(current, proposed))


# ---------------------------------------------------------------- per-farmer chat rate limit (per process)
_hits = defaultdict(deque)


def rate_limit_ok(farmer_id: int, now: Optional[float] = None) -> bool:
    """True and records the hit if this farmer is under the hourly limit. In memory, so it resets on restart and is
    per process: enough to stop a runaway client from spending the LLM budget, not a security boundary."""
    now = time.time() if now is None else now
    q = _hits[farmer_id]
    while q and q[0] <= now - 3600:
        q.popleft()
    if len(q) >= rate_limit_per_hour():
        return False
    q.append(now)
    return True


# ---------------------------------------------------------------- database (conn = database.get_conn(), dict rows)
def fetch_current(conn, farmer_id: int) -> Optional[dict]:
    """The one fixed query that tells the LLM (and resolve) what this farmer has now. The id comes from the token."""
    r = conn.execute("SELECT qty_kg, ready_hr, deadline_hr FROM farmers WHERE id = %s", (farmer_id,)).fetchone()
    return None if r is None else {k: float(r[k]) for k in FIELDS}


def window_open(conn) -> bool:
    r = conn.execute("SELECT is_open FROM change_window WHERE id = 1").fetchone()
    return True if r is None else bool(r["is_open"])


def set_window(conn, is_open: bool) -> None:
    conn.execute("INSERT INTO change_window (id, is_open) VALUES (1, %s) "
                 "ON CONFLICT (id) DO UPDATE SET is_open = EXCLUDED.is_open", (is_open,))


def published_plan_id(conn) -> Optional[int]:
    r = conn.execute("SELECT plan_id FROM published_plan WHERE id = 1").fetchone()
    return None if r is None else r["plan_id"]


def expire_stale(conn, now: Optional[float] = None) -> None:
    now = time.time() if now is None else now
    conn.execute("UPDATE change_requests SET status = 'expired', decided_at = %s "
                 "WHERE status = 'draft' AND created_at < %s", (now, now - DRAFT_TTL_S))
    conn.execute("UPDATE change_requests SET status = 'expired', decided_at = %s "
                 "WHERE status = 'pending' AND created_at < %s", (now, now - pending_ttl_s()))


def create_draft(conn, farmer_id: int, raw_text: str, parse: ChangeParse, current: dict, proposed: dict) -> int:
    """Stores what was understood. A farmer has at most one live draft: an older one is superseded."""
    now = time.time()
    conn.execute("UPDATE change_requests SET status = 'superseded', decided_at = %s "
                 "WHERE farmer_id = %s AND status = 'draft'", (now, farmer_id))
    return conn.execute(
        "INSERT INTO change_requests (farmer_id, raw_text, parsed, current, proposed, status, created_at) "
        "VALUES (%s, %s, %s, %s, %s, 'draft', %s) RETURNING id",
        (farmer_id, raw_text, parse.model_dump_json(), json.dumps(current), json.dumps(proposed), now),
    ).fetchone()["id"]


def _own_row(conn, farmer_id: int, request_id: int):
    """Lock one request, only if it belongs to this farmer. Someone else's id looks exactly like a missing one."""
    row = conn.execute("SELECT * FROM change_requests WHERE id = %s AND farmer_id = %s FOR UPDATE",
                       (request_id, farmer_id)).fetchone()
    if row is None:
        raise RequestNotFound(request_id)
    return row


def confirm(conn, farmer_id: int, request_id: int) -> dict:
    """draft -> pending. Any older pending request of this farmer is superseded. Refused if the farmer's own
    numbers changed since the draft (the confirm card would no longer be true)."""
    expire_stale(conn)
    row = _own_row(conn, farmer_id, request_id)
    if row["status"] != "draft":
        raise RequestConflict(f"This request is already {row['status']}.")
    now_cur = fetch_current(conn, farmer_id)
    if now_cur is None or _differs(json.loads(row["current"]), now_cur):
        raise RequestConflict("Your plan details changed since you asked. Please send your request again.")
    now = time.time()
    conn.execute("UPDATE change_requests SET status = 'superseded', decided_at = %s "
                 "WHERE farmer_id = %s AND status = 'pending'", (now, farmer_id))
    conn.execute("UPDATE change_requests SET status = 'pending' WHERE id = %s", (request_id,))
    return farmer_view({**row, "status": "pending"})


def withdraw(conn, farmer_id: int, request_id: int) -> dict:
    row = _own_row(conn, farmer_id, request_id)
    if row["status"] not in ("draft", "pending"):
        raise RequestConflict(f"This request is already {row['status']}.")
    conn.execute("UPDATE change_requests SET status = 'withdrawn', decided_at = %s WHERE id = %s",
                 (time.time(), request_id))
    return farmer_view({**row, "status": "withdrawn"})


def list_for_farmer(conn, farmer_id: int, limit: int = 10) -> list:
    expire_stale(conn)
    rows = conn.execute("SELECT * FROM change_requests WHERE farmer_id = %s AND status <> 'superseded' "
                        "ORDER BY id DESC LIMIT %s", (farmer_id, limit)).fetchall()
    return [farmer_view(r) for r in rows]


def list_by_status(conn, status: str) -> list:
    expire_stale(conn)
    rows = conn.execute("SELECT r.*, f.crop FROM change_requests r LEFT JOIN farmers f ON f.id = r.farmer_id "
                        "WHERE r.status = %s ORDER BY r.id", (status,)).fetchall()
    return [admin_view(r) for r in rows]


def load_pending(conn, ids: List[int]) -> list:
    """Lock the named requests; every one must exist and still be pending."""
    ids = sorted(set(ids))
    rows = conn.execute("SELECT * FROM change_requests WHERE id = ANY(%s) ORDER BY id FOR UPDATE", (ids,)).fetchall()
    missing = sorted(set(ids) - {r["id"] for r in rows})
    if missing:
        raise RequestNotFound(f"No change request(s) {missing}.")
    not_pending = [r["id"] for r in rows if r["status"] != "pending"]
    if not_pending:
        raise RequestConflict(f"Request(s) {not_pending} are no longer pending.")
    stale = [r["id"] for r in rows if (now := fetch_current(conn, r["farmer_id"])) is None
             or _differs(json.loads(r["current"]), now)]
    if stale:
        raise RequestConflict(f"Request(s) {stale} were made against farmer details that have since changed. "
                              "Reject them and ask the farmer to send again.")
    return rows


def overrides_of(rows: list) -> dict:
    """{farmer_id: {field: new value}} for compute_plan's farmer_overrides."""
    return {r["farmer_id"]: json.loads(r["proposed"]) for r in rows}


def apply_approved(conn, rows: list, plan_id: int, base_plan_id: int) -> None:
    """In the caller's transaction: mark the requests approved and write their values into farmers. Refuses if the
    published plan is no longer the one the admin previewed against."""
    cur = conn.execute("SELECT plan_id FROM published_plan WHERE id = 1 FOR UPDATE").fetchone()
    if cur is None or cur["plan_id"] != base_plan_id:
        raise RequestConflict("The published plan changed since you previewed. Preview again before approving.")
    ids = [r["id"] for r in rows]
    done = conn.execute("UPDATE change_requests SET status = 'approved', decided_at = %s, decided_by = 'admin', "
                        "applied_plan_id = %s WHERE id = ANY(%s) AND status = 'pending' RETURNING id",
                        (time.time(), plan_id, ids)).fetchall()
    if len(done) != len(ids):
        raise RequestConflict("Some of these requests were decided by someone else a moment ago.")
    for farmer_id, proposed in overrides_of(rows).items():
        cols = [k for k in FIELDS if k in proposed]                  # column names come from FIELDS only
        conn.execute(f"UPDATE farmers SET {', '.join(c + ' = %s' for c in cols)} WHERE id = %s",
                     [proposed[c] for c in cols] + [farmer_id])


def reject(conn, request_id: int, reason_code: str) -> None:
    r = conn.execute("SELECT status FROM change_requests WHERE id = %s FOR UPDATE", (request_id,)).fetchone()
    if r is None:
        raise RequestNotFound(request_id)
    if r["status"] != "pending":
        raise RequestConflict(f"This request is already {r['status']}.")
    conn.execute("UPDATE change_requests SET status = 'rejected', reason_code = %s, decided_at = %s, "
                 "decided_by = 'admin' WHERE id = %s", (reason_code, time.time(), request_id))


def _differs(a: dict, b: dict) -> bool:
    return any(abs(float(a[k]) - float(b[k])) >= _TOL[k] for k in FIELDS)


# ---------------------------------------------------------------- what each side may see
def farmer_view(r) -> dict:
    cur, prop = json.loads(r["current"]), json.loads(r["proposed"])
    return {"id": r["id"], "status": r["status"], "changes": change_lines(cur, prop), "reason_code": r["reason_code"],
            "created_at": r["created_at"], "decided_at": r["decided_at"]}


def admin_view(r) -> dict:
    """Raw text beside what it was parsed to, so a misparse is obvious. raw_text is untrusted: show as plain text."""
    cur, prop = json.loads(r["current"]), json.loads(r["proposed"])
    return {"id": r["id"], "farmer_id": r["farmer_id"], "crop": r.get("crop"), "status": r["status"],
            "raw_text": r["raw_text"], "parsed": json.loads(r["parsed"]), "current": cur, "proposed": prop,
            "changes": change_lines(cur, prop), "reason_code": r["reason_code"], "applied_plan_id": r["applied_plan_id"],
            "created_at": r["created_at"], "decided_at": r["decided_at"]}
