"""
change_requests.py -- farmer change requests: what the LLM may say, how it is checked, and where requests live.

The flow (routes are in main.py):

  farmer message --LLM--> ChangeParse --resolve()--> absolute new values --> 'draft' row
      --farmer taps Confirm--> 'pending' --admin preview / approve / reject--> 'approved' | 'rejected'

Rules this module enforces:
  * The LLM only ever produces a ChangeParse (a field, a mode and a number, or a day word and a clock time, or
    cancel / rejoin). It never writes SQL and never sees an id. Everything that touches the database is a fixed,
    parameterised query below.
  * The LLM does no arithmetic. "100 kg less" arrives as shift -100; "tomorrow 6 AM" as day "tomorrow", clock
    "06:00". resolve() turns them into numbers against the farmer's current row and today's date, rounds, and
    bounds-checks the result. A hallucinated "99999 kg" dies in resolve(), not in the plan.
  * A request changes only the farmer's own qty_kg / ready_hr / deadline_hr / participation, and only once an admin
    approves. The farmers table is not touched by drafting, confirming, previewing or rejecting.
  * A farmer can have several requests waiting at once. Requests that touch different things can be approved
    together or one after another; two that touch the same thing cannot be approved together, and approving one
    marks the other superseded.
  * Hours are the plan clock: hour 0 is 00:00 of the plan day (see plan_day), so tomorrow 06:00 is hour 30.
"""
import datetime as dt
import json
import os
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import List, Literal, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator

FIELDS = ("qty_kg", "ready_hr", "deadline_hr")
COLUMNS = FIELDS + ("active", "trader_quote_per_kg")   # the farmers columns a request may write
LABEL = {"qty_kg": "Quantity", "ready_hr": "Ready time", "deadline_hr": "Deadline", "active": "Participation",
         "trader_quote_per_kg": "Trader's offer"}
# How different two values must be to count as a change (a farmer typing 342.7 for 342.7384 changed nothing).
_TOL = {"qty_kg": 0.05, "ready_hr": 0.005, "deadline_hr": 0.005}
REASONS = ("too_late", "not_possible", "capacity", "other")
STATUSES = ("draft", "pending", "approved", "rejected", "superseded", "expired", "withdrawn")
DRAFT_TTL_S = 3600
CTX_TTL_S = 600                             # a chat is remembered for ten minutes
CTX_MAX_TURNS = 6
DAY_WORDS = ("today", "tomorrow", "day_after_tomorrow",
             "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_CLOCK = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------- settings (env, read at call time)
def max_qty_kg() -> float:
    return float(os.environ.get("CHANGE_MAX_QTY_KG", "5000"))        # the biggest vehicle in the fleet carries 5000


def max_hour() -> float:
    return float(os.environ.get("CHANGE_MAX_HOUR", "72"))            # planning clock: hours from the start of day


def pending_ttl_s() -> float:
    return float(os.environ.get("CHANGE_REQUEST_TTL_H", "24")) * 3600


def rate_limit_per_hour() -> int:
    return int(os.environ.get("CHAT_RATE_PER_HOUR", "20"))


def max_quote_per_kg() -> float:
    return float(os.environ.get("CHANGE_MAX_QUOTE_PER_KG", "500"))    # Rs/kg; above this it is a typo, not a quote


def max_pending() -> int:
    return int(os.environ.get("CHANGE_MAX_PENDING", "5"))             # waiting requests per farmer


# ---------------------------------------------------------------- calendar: today, and what hour 0 means
@dataclass(frozen=True)
class Clock:
    today: dt.date          # the farmer's today (FARMROUTE_TZ)
    plan_day: dt.date       # the calendar date of hour 0 of the plan


def _tz():
    name = os.environ.get("FARMROUTE_TZ", "Asia/Kolkata")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        # a slim server image may have no tz database; India has no daylight saving, so a fixed offset is exact
        return dt.timezone(dt.timedelta(hours=5, minutes=30)) if name == "Asia/Kolkata" else dt.timezone.utc


def local_today(now: Optional[dt.datetime] = None) -> dt.date:
    return (now or dt.datetime.now(dt.timezone.utc)).astimezone(_tz()).date()


def _valid_iso(s: str) -> bool:
    if not _ISO.match(s):
        return False
    try:
        dt.date.fromisoformat(s)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------- what the LLM (or the form) may send
class Change(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: Literal["qty_kg", "ready_hr", "deadline_hr"]
    # set: "make it 400" | shift: "2 hours later", "100 kg less" | scale: "half" | at: "tomorrow at 6 AM"
    mode: Literal["set", "shift", "scale", "at"]
    value: float = Field(default=0.0, allow_inf_nan=False)
    day: Optional[str] = None        # at only: a day word, an ISO date, or None (= the plan day)
    clock: Optional[str] = None      # at only: 24-hour "HH:MM"

    @model_validator(mode="after")
    def _shape(self):
        if self.mode == "at":
            if self.field == "qty_kg":
                raise ValueError("'at' is only for ready_hr and deadline_hr")
            if not self.clock or not _CLOCK.match(self.clock):
                raise ValueError("'at' needs clock as HH:MM")
            if self.day is not None and self.day not in DAY_WORDS and not _valid_iso(self.day):
                raise ValueError(f"day must be one of {DAY_WORDS} or YYYY-MM-DD")
            return self
        if "value" not in self.model_fields_set:
            raise ValueError("value is required")
        if self.day is not None or self.clock is not None:
            raise ValueError("day and clock are only for 'at'")
        if self.mode == "scale" and (self.field != "qty_kg" or self.value <= 0):
            raise ValueError("scale is only for qty_kg and must be positive")
        return self


class PoolJoin(BaseModel):
    """\"My trader pays less than expected, put me in the pooling.\" The only number is what the farmer's own trader
    offers per kg, copied from the message."""
    model_config = ConfigDict(extra="forbid")
    quote_per_kg: float = Field(gt=0, allow_inf_nan=False)


class ChangeParse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    changes: List[Change] = Field(default_factory=list, max_length=3)
    participation: Optional[Literal["cancel", "rejoin"]] = None   # "I will not sell this time" / "I want to sell again"
    pool_join: Optional[PoolJoin] = None                          # "my trader pays less, I want to join the pool"
    clarify: Optional[str] = Field(default=None, max_length=200)  # a question for the farmer when info is missing

    @model_validator(mode="after")
    def _exclusive(self):
        if self.participation and self.changes:
            raise ValueError("participation cannot be combined with changes")
        if self.pool_join and (self.changes or self.participation):
            raise ValueError("pool_join cannot be combined with changes or participation")
        return self


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
    """PUT /change-window: send is_open, plan_day, or both. plan_day null clears it (back to the publish date)."""
    is_open: Optional[bool] = None
    plan_day: Optional[str] = None

    @model_validator(mode="after")
    def _something(self):
        if not self.model_fields_set & {"is_open", "plan_day"}:
            raise ValueError("send is_open and/or plan_day")
        if self.plan_day is not None and not _valid_iso(self.plan_day):
            raise ValueError("plan_day must be YYYY-MM-DD or null")
        if "is_open" in self.model_fields_set and self.is_open is None:
            raise ValueError("is_open must be true or false")
        return self


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
    """The request is not in a state that allows this, or the world moved since it was made. `code` is for apps."""

    def __init__(self, message: str, code: str = "conflict"):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------- resolving a parse against the farmer's row
def _split_hr(v: float):
    """Plan hours -> ("HH:MM" on the clock, whole days after the plan day). 30.5 -> ("06:30", 1)."""
    m = round(v * 60)
    return f"{(m % 1440) // 60:02d}:{m % 60:02d}", m // 1440


def fmt_value(field: str, v: float) -> str:
    return f"{round(v, 1):g} kg" if field == "qty_kg" else _split_hr(v)[0]


def _target_date(day: str, today: dt.date) -> dt.date:
    if day == "today":
        return today
    if day == "tomorrow":
        return today + dt.timedelta(days=1)
    if day == "day_after_tomorrow":
        return today + dt.timedelta(days=2)
    if day in DAY_WORDS:                                   # a weekday: the next one, today counting
        want = DAY_WORDS.index(day) - 3                    # monday = 0
        return today + dt.timedelta(days=(want - today.weekday()) % 7)
    return dt.date.fromisoformat(day)


def _at_hours(c: Change, clock: Optional[Clock]) -> float:
    h, m = (int(x) for x in c.clock.split(":"))
    base = h + m / 60
    if c.day is None:                                      # only a time was given: it is on the plan day
        return base
    if clock is None:
        raise ChangeError("I cannot work out that day right now. Please say the time without a day.", "no_clock")
    days = (_target_date(c.day, clock.today) - clock.plan_day).days
    if days < 0:
        raise ChangeError("That day is before the plan starts.", "date_past")
    return days * 24 + base


def _check_final(final: dict) -> None:
    """The values a farmer row would have: raise ChangeError if they are not a sensible plan input."""
    if not 0 < final["qty_kg"] <= max_qty_kg():
        raise ChangeError(f"Quantity must be more than 0 and at most {max_qty_kg():g} kg.", "qty_range", max=max_qty_kg())
    if final["ready_hr"] < 0:
        raise ChangeError("The ready time cannot be before the start of the day (00:00).", "ready_neg")
    if final["deadline_hr"] > max_hour():
        raise ChangeError(f"The deadline must be within {max_hour():g} hours of the start of the day.", "deadline_max",
                          max=max_hour())
    if final["ready_hr"] >= final["deadline_hr"]:
        raise ChangeError("The ready time must be earlier than the deadline.", "order")


def _resolve_pool_join(join: PoolJoin, current: dict, active: bool) -> dict:
    """A farmer whose own trader pays less than the plan assumed asks to be pooled. `current` carries `pool_status`
    (the farmer's published card: hauled / farmgate / unserved) and `expected_per_kg` (the doorstep price the plan
    assumed for them), added by with_card(). The quote is saved for THIS farmer only, once an admin approves."""
    if not active:
        raise ChangeError("You are not in this plan right now. Ask to join again first.", "inactive")
    status, expected = current.get("pool_status"), current.get("expected_per_kg")
    if status is None:
        raise ChangeError("I cannot see your trip right now. Please try again later.", "no_card")
    if status == "hauled":
        raise ChangeError("A truck is already planned for your produce. Use 'Check a trader's offer' to compare.",
                          "already_hauled")
    if status == "unserved":
        raise ChangeError("You are already waiting for a truck, and your FPO knows. A lower offer will not change that.",
                          "waiting_truck")
    q = round(join.quote_per_kg, 2)
    if q > max_quote_per_kg():
        raise ChangeError(f"That price looks too high for one kilo (more than {max_quote_per_kg():g} rupees).",
                          "quote_range", max=max_quote_per_kg())
    if expected is not None and q >= float(expected):
        raise ChangeError(f"Your trader's offer is not below the expected price (about {float(expected):g} rupees a "
                          "kilo), so selling at your door is fine.", "not_lower", quote=q, expected=float(expected))
    prev = current.get("trader_quote_per_kg")
    if prev is not None and abs(float(prev) - q) < 0.005:
        raise ChangeError("That is the same as the offer you already gave.", "same")
    return {"trader_quote_per_kg": q}


def resolve(parse: ChangeParse, current: dict, clock: Optional[Clock] = None) -> dict:
    """ChangeParse + the farmer's current values -> {column: new value} for what changes. Raises ChangeError
    (farmer-safe text) if the result is not a sensible plan input."""
    active = bool(current.get("active", True))
    if parse.pool_join is not None:
        return _resolve_pool_join(parse.pool_join, current, active)
    if parse.participation == "cancel":
        if not active:
            raise ChangeError("You are already out of this plan.", "already_out")
        return {"active": False}
    if parse.participation == "rejoin":
        if active:
            raise ChangeError("You are already in this plan.", "already_in")
        return {"active": True}
    if not active:
        raise ChangeError("You are not in this plan right now. Ask to join again first.", "inactive")
    if not parse.changes:
        raise ChangeError("Tell me what to change: how many kg you have, or when the produce is ready or must leave.",
                          "empty")
    new, seen = {k: float(current[k]) for k in FIELDS}, set()
    for c in parse.changes:
        if c.field in seen:
            raise ChangeError(f"You gave {LABEL[c.field].lower()} twice. Please send one value for it.", "twice")
        seen.add(c.field)
        base = new[c.field]
        new[c.field] = (_at_hours(c, clock) if c.mode == "at" else c.value if c.mode == "set"
                        else base + c.value if c.mode == "shift" else base * c.value)
    changed = {}
    for k in FIELDS:
        v = round(new[k], 1 if k == "qty_kg" else 2)
        if abs(v - float(current[k])) >= _TOL[k]:
            changed[k] = v
    _check_final({k: changed.get(k, float(current[k])) for k in FIELDS})
    if not changed:
        raise ChangeError("That is the same as your current plan, so nothing would change.", "same")
    return changed


def change_lines(current: dict, proposed: dict) -> list:
    """The confirm card, built by code from resolved numbers (the LLM's words are never shown as a result).
    Times are "HH:MM" on the clock plus from_day / to_day (whole days after the plan day) for a next-day time."""
    if "trader_quote_per_kg" in proposed:
        exp = current.get("expected_per_kg")
        return [{"field": "trader_quote_per_kg", "label": LABEL["trader_quote_per_kg"],
                 "from": "" if exp is None else f"{round(float(exp), 2):g}",
                 "to": f"{round(float(proposed['trader_quote_per_kg']), 2):g}", "from_day": 0, "to_day": 0}]
    if "active" in proposed:
        was = "in" if current.get("active", True) else "out"
        return [{"field": "active", "label": LABEL["active"], "from": was, "to": "in" if proposed["active"] else "out",
                 "from_day": 0, "to_day": 0}]
    out = []
    for k in FIELDS:
        if k not in proposed:
            continue
        if k == "qty_kg":
            out.append({"field": k, "label": LABEL[k], "from": fmt_value(k, current[k]), "to": fmt_value(k, proposed[k]),
                        "from_day": 0, "to_day": 0})
        else:
            (f, fd), (t, td) = _split_hr(current[k]), _split_hr(proposed[k])
            out.append({"field": k, "label": LABEL[k], "from": f, "to": t, "from_day": fd, "to_day": td})
    return out


def summary(current: dict, proposed: dict) -> str:
    day = lambda d: f" (+{d} day{'s' if d > 1 else ''})" if d else ""
    return "; ".join(f"{c['label']}: {c['from']}{day(c['from_day'])} -> {c['to']}{day(c['to_day'])}"
                     for c in change_lines(current, proposed))


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
    r = conn.execute("SELECT qty_kg, ready_hr, deadline_hr, active, trader_quote_per_kg FROM farmers WHERE id = %s",
                     (farmer_id,)).fetchone()
    if r is None:
        return None
    q = r["trader_quote_per_kg"]
    return {**{k: float(r[k]) for k in FIELDS}, "active": bool(r["active"]),
            "trader_quote_per_kg": None if q is None else float(q)}


def published_card(conn, farmer_id: int) -> Optional[dict]:
    """This farmer's own card from the published plan (None if there is none). Fixed query; the id is the token's."""
    r = conn.execute("SELECT cards FROM published_plan WHERE id = 1").fetchone()
    return None if r is None else json.loads(r["cards"]).get(str(farmer_id))


def with_card(current: Optional[dict], card: Optional[dict]) -> Optional[dict]:
    """`current` plus what the farmer's card says about their trip, for pool-join checks and the confirm card. The
    extra keys are never written to the farmers table (COLUMNS decides that)."""
    if current is None:
        return None
    out = dict(current)
    if card:
        out["pool_status"] = card.get("status")
        if card.get("doorstep_per_kg") is not None:
            out["expected_per_kg"] = float(card["doorstep_per_kg"])
    return out


def get_window(conn):
    """(is_open, stored plan_day or None). No row means open and no stored plan day."""
    r = conn.execute("SELECT is_open, plan_day FROM change_window WHERE id = 1").fetchone()
    return (True, None) if r is None else (bool(r["is_open"]), r["plan_day"])


def window_open(conn) -> bool:
    return get_window(conn)[0]


_UNSET = object()


def set_window(conn, is_open=None, plan_day=_UNSET) -> None:
    """Change what was given and keep the rest. plan_day=None clears the stored plan day."""
    cur_open, cur_day = get_window(conn)
    conn.execute("INSERT INTO change_window (id, is_open, plan_day) VALUES (1, %s, %s) "
                 "ON CONFLICT (id) DO UPDATE SET is_open = EXCLUDED.is_open, plan_day = EXCLUDED.plan_day",
                 (cur_open if is_open is None else is_open, cur_day if plan_day is _UNSET else plan_day))


def published_plan_id(conn) -> Optional[int]:
    r = conn.execute("SELECT plan_id FROM published_plan WHERE id = 1").fetchone()
    return None if r is None else r["plan_id"]


def effective_plan_day(conn, now: Optional[dt.datetime] = None) -> dt.date:
    """The date hour 0 means: the admin's choice, else the day the plan was published, else today."""
    stored = get_window(conn)[1]
    if stored and _valid_iso(stored):
        return dt.date.fromisoformat(stored)
    r = conn.execute("SELECT published_at FROM published_plan WHERE id = 1").fetchone()
    if r is not None:
        try:
            return dt.datetime.fromisoformat(r["published_at"]).astimezone(_tz()).date()
        except (ValueError, TypeError):
            pass
    return local_today(now)


def get_clock(conn, now: Optional[dt.datetime] = None) -> Clock:
    return Clock(today=local_today(now), plan_day=effective_plan_day(conn, now))


def expire_stale(conn, now: Optional[float] = None) -> None:
    now = time.time() if now is None else now
    conn.execute("DELETE FROM change_requests WHERE status = 'draft' AND created_at < %s", (now - DRAFT_TTL_S,))
    conn.execute("UPDATE change_requests SET status = 'expired', decided_at = %s "
                 "WHERE status = 'pending' AND created_at < %s", (now, now - pending_ttl_s()))


def create_draft(conn, farmer_id: int, raw_text: str, parse: ChangeParse, current: dict, proposed: dict) -> int:
    """Stores what was understood. A farmer has at most one live draft (the one on their confirm card): an older
    draft is discarded. Other requests they already confirmed are untouched."""
    conn.execute("DELETE FROM change_requests WHERE farmer_id = %s AND status = 'draft'", (farmer_id,))
    return conn.execute(
        "INSERT INTO change_requests (farmer_id, raw_text, parsed, current, proposed, status, created_at) "
        "VALUES (%s, %s, %s, %s, %s, 'draft', %s) RETURNING id",
        (farmer_id, raw_text, parse.model_dump_json(), json.dumps(current), json.dumps(proposed), time.time()),
    ).fetchone()["id"]


def _own_row(conn, farmer_id: int, request_id: int):
    """Lock one request, only if it belongs to this farmer. Someone else's id looks exactly like a missing one."""
    row = conn.execute("SELECT * FROM change_requests WHERE id = %s AND farmer_id = %s FOR UPDATE",
                       (request_id, farmer_id)).fetchone()
    if row is None:
        raise RequestNotFound(request_id)
    return row


def _stale(snapshot: dict, now: dict, touched) -> bool:
    """Was the request made against details that have since changed? Only what it changes matters, so approving a
    quantity request does not spoil a waiting time request. Leaving or rejoining the plan spoils everything."""
    if bool(snapshot.get("active", True)) != bool(now.get("active", True)):
        return True
    return any(abs(float(snapshot[k]) - float(now[k])) >= _TOL[k] for k in touched if k in FIELDS)


def confirm(conn, farmer_id: int, request_id: int) -> dict:
    """draft -> pending. A farmer may have several pending requests (up to max_pending), but not the same one twice,
    and not one made against numbers that have since changed. The chat memory ends here: the conversation is done."""
    expire_stale(conn)
    row = _own_row(conn, farmer_id, request_id)
    if row["status"] != "draft":
        raise RequestConflict(f"This request is already {row['status']}.", "not_draft")
    proposed = json.loads(row["proposed"])
    now_cur = fetch_current(conn, farmer_id)
    if now_cur is None or _stale(json.loads(row["current"]), now_cur, set(proposed)):
        raise RequestConflict("Your plan details changed since you asked. Please send your request again.", "stale")
    waiting = conn.execute("SELECT proposed FROM change_requests WHERE farmer_id = %s AND status = 'pending'",
                           (farmer_id,)).fetchall()
    if len(waiting) >= max_pending():
        raise RequestConflict(f"You already have {len(waiting)} requests waiting. Cancel one first.", "max_pending")
    if any(json.loads(w["proposed"]) == proposed for w in waiting):
        raise RequestConflict("You already asked for exactly this.", "duplicate")
    conn.execute("UPDATE change_requests SET status = 'pending' WHERE id = %s", (request_id,))
    clear_context(conn, farmer_id)
    return farmer_view({**row, "status": "pending"})


def withdraw(conn, farmer_id: int, request_id: int) -> dict:
    row = _own_row(conn, farmer_id, request_id)
    if row["status"] not in ("draft", "pending"):
        raise RequestConflict(f"This request is already {row['status']}.", "not_open")
    if row["status"] == "draft":
        conn.execute("DELETE FROM change_requests WHERE id = %s", (request_id,))      # an unsent draft leaves no trace
    else:
        conn.execute("UPDATE change_requests SET status = 'withdrawn', decided_at = %s WHERE id = %s",
                     (time.time(), request_id))
    return farmer_view({**row, "status": "withdrawn"})


def list_for_farmer(conn, farmer_id: int, limit: int = 20) -> list:
    expire_stale(conn)
    rows = conn.execute("SELECT * FROM change_requests WHERE farmer_id = %s ORDER BY id DESC LIMIT %s",
                        (farmer_id, limit)).fetchall()
    return [farmer_view(r) for r in rows]


def list_by_status(conn, status: str) -> list:
    expire_stale(conn)
    rows = conn.execute("SELECT r.*, f.crop FROM change_requests r LEFT JOIN farmers f ON f.id = r.farmer_id "
                        "WHERE r.status = %s ORDER BY r.id", (status,)).fetchall()
    out = [admin_view(r) for r in rows]
    if status == "pending":                  # tell the admin which of a farmer's waiting requests clash
        touched = {r["id"]: set(json.loads(r["proposed"])) for r in rows}
        for v in out:
            v["overlaps"] = [o["id"] for o in rows if o["id"] != v["id"] and o["farmer_id"] == v["farmer_id"]
                             and _clash(touched[v["id"]], touched[o["id"]])]
    return out


def _clash(a: set, b: set) -> bool:
    """Two requests of one farmer that cannot both be approved: they change the same thing, or one of them is
    about leaving or rejoining the plan."""
    return bool(a & b) or "active" in a or "active" in b


def load_pending(conn, ids: List[int]) -> list:
    """Lock the named requests; every one must exist, still be pending, be consistent with the farmer's details as
    they are now, and not clash with another selected request of the same farmer."""
    ids = sorted(set(ids))
    rows = conn.execute("SELECT * FROM change_requests WHERE id = ANY(%s) ORDER BY id FOR UPDATE", (ids,)).fetchall()
    missing = sorted(set(ids) - {r["id"] for r in rows})
    if missing:
        raise RequestNotFound(f"No change request(s) {missing}.")
    not_pending = [r["id"] for r in rows if r["status"] != "pending"]
    if not_pending:
        raise RequestConflict(f"Request(s) {not_pending} are no longer pending.", "not_pending")
    now = {fid: fetch_current(conn, fid) for fid in {r["farmer_id"] for r in rows}}
    stale = [r["id"] for r in rows if now[r["farmer_id"]] is None
             or _stale(json.loads(r["current"]), now[r["farmer_id"]], set(json.loads(r["proposed"])))]
    if stale:
        raise RequestConflict(f"Request(s) {stale} were made against farmer details that have since changed. "
                              "Reject them and ask the farmer to send again.", "stale")
    by_farmer = defaultdict(list)
    for r in rows:
        by_farmer[r["farmer_id"]].append(r)
    for fid, rs in by_farmer.items():
        sets = [set(json.loads(r["proposed"])) for r in rs]
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)):
                if _clash(sets[i], sets[j]):
                    raise RequestConflict(
                        f"Farmer {fid} has requests {rs[i]['id']} and {rs[j]['id']} that change the same thing "
                        "(or one leaves the plan). Select only one of them.", "same_field")
        merged = {}
        for r in rs:
            merged.update(json.loads(r["proposed"]))
        final = {**now[fid], **merged}
        if final["active"] and set(merged) & set(FIELDS):
            try:
                _check_final(final)
            except ChangeError as e:
                raise RequestConflict(f"Farmer {fid}: these cannot be applied to the farmer's details as they are "
                                      f"now. {e}", "cannot_combine") from e
    return rows


def overrides_of(rows: list) -> dict:
    """{farmer_id: {column: new value}} for compute_plan's farmer_overrides (a farmer's requests merged)."""
    out = defaultdict(dict)
    for r in rows:
        out[r["farmer_id"]].update(json.loads(r["proposed"]))
    return dict(out)


def apply_approved(conn, rows: list, plan_id: int, base_plan_id: int) -> None:
    """In the caller's transaction: mark the requests approved and write their values into farmers. Refuses if the
    published plan is no longer the one the admin previewed against. A farmer's other waiting requests that touch
    what was just changed (or all of them, if the farmer left the plan) become superseded."""
    cur = conn.execute("SELECT plan_id FROM published_plan WHERE id = 1 FOR UPDATE").fetchone()
    if cur is None or cur["plan_id"] != base_plan_id:
        raise RequestConflict("The published plan changed since you previewed. Preview again before approving.",
                              "plan_moved")
    ids = [r["id"] for r in rows]
    now = time.time()
    done = conn.execute("UPDATE change_requests SET status = 'approved', decided_at = %s, decided_by = 'admin', "
                        "applied_plan_id = %s WHERE id = ANY(%s) AND status = 'pending' RETURNING id",
                        (now, plan_id, ids)).fetchall()
    if len(done) != len(ids):
        raise RequestConflict("Some of these requests were decided by someone else a moment ago.", "decided")
    merged = overrides_of(rows)
    for farmer_id, proposed in merged.items():
        cols = [k for k in COLUMNS if k in proposed]                  # column names come from COLUMNS only
        conn.execute(f"UPDATE farmers SET {', '.join(c + ' = %s' for c in cols)} WHERE id = %s",
                     [proposed[c] for c in cols] + [farmer_id])
    others = conn.execute("SELECT id, farmer_id, proposed FROM change_requests WHERE status = 'pending' "
                          "AND farmer_id = ANY(%s) AND NOT (id = ANY(%s))", (list(merged), ids)).fetchall()
    gone = [o["id"] for o in others if _clash(set(merged[o["farmer_id"]]), set(json.loads(o["proposed"])))
            or "active" in merged[o["farmer_id"]]]
    if gone:
        conn.execute("UPDATE change_requests SET status = 'superseded', decided_at = %s, decided_by = 'admin' "
                     "WHERE id = ANY(%s)", (now, gone))


def reject(conn, request_id: int, reason_code: str) -> None:
    r = conn.execute("SELECT status FROM change_requests WHERE id = %s FOR UPDATE", (request_id,)).fetchone()
    if r is None:
        raise RequestNotFound(request_id)
    if r["status"] != "pending":
        raise RequestConflict(f"This request is already {r['status']}.", "not_pending")
    conn.execute("UPDATE change_requests SET status = 'rejected', reason_code = %s, decided_at = %s, "
                 "decided_by = 'admin' WHERE id = %s", (reason_code, time.time(), request_id))


# ---------------------------------------------------------------- the chat remembers a few turns, briefly
def load_context(conn, farmer_id: int, now: Optional[float] = None) -> list:
    """The farmer's last few chat turns (user message / the app's answer), if the chat is recent. Each turn is
    {"role": "user" | "assistant", "content": str}."""
    now = time.time() if now is None else now
    r = conn.execute("SELECT turns, updated_at FROM chat_context WHERE farmer_id = %s", (farmer_id,)).fetchone()
    if r is None or now - r["updated_at"] > CTX_TTL_S:
        return []
    try:
        turns = json.loads(r["turns"])
    except ValueError:
        return []
    return _tidy([t for t in turns if isinstance(t, dict) and t.get("role") in ("user", "assistant")
                  and isinstance(t.get("content"), str)])


def _tidy(turns: list) -> list:
    turns = turns[-CTX_MAX_TURNS:]
    while turns and turns[0]["role"] != "user":                       # a chat starts with the farmer speaking
        turns = turns[1:]
    return turns


def save_context(conn, farmer_id: int, turns: list, now: Optional[float] = None) -> None:
    now = time.time() if now is None else now
    conn.execute("DELETE FROM chat_context WHERE updated_at < %s", (now - CTX_TTL_S,))
    conn.execute("INSERT INTO chat_context (farmer_id, turns, updated_at) VALUES (%s, %s, %s) "
                 "ON CONFLICT (farmer_id) DO UPDATE SET turns = EXCLUDED.turns, updated_at = EXCLUDED.updated_at",
                 (farmer_id, json.dumps(_tidy(turns)), now))


def clear_context(conn, farmer_id: int) -> None:
    conn.execute("DELETE FROM chat_context WHERE farmer_id = %s", (farmer_id,))


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
            "created_at": r["created_at"], "decided_at": r["decided_at"], "overlaps": []}
