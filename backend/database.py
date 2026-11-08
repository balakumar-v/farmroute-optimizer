"""
database.py
------------
Plain psycopg (v3), no ORM. Postgres (Neon in deployment). The connection
string comes from the DATABASE_URL environment variable -- see .env.example.
"""

import os
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

SCHEMA = """
CREATE TABLE IF NOT EXISTS farmers (
    id SERIAL PRIMARY KEY,
    lat DOUBLE PRECISION NOT NULL,
    lng DOUBLE PRECISION NOT NULL,
    crop TEXT NOT NULL,
    qty_kg DOUBLE PRECISION NOT NULL,
    ready_hr DOUBLE PRECISION NOT NULL,
    deadline_hr DOUBLE PRECISION NOT NULL,
    needs_refrigeration INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS vehicles (
    id SERIAL PRIMARY KEY,
    type_name TEXT NOT NULL,
    capacity_kg DOUBLE PRECISION NOT NULL,
    refrigerated INTEGER NOT NULL,
    fixed_cost DOUBLE PRECISION NOT NULL,
    per_km_cost DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS markets (
    id SERIAL PRIMARY KEY,
    lat DOUBLE PRECISION NOT NULL,
    lng DOUBLE PRECISION NOT NULL,
    price TEXT NOT NULL,        -- JSON: {crop: inr_per_kg}
    capacity_kg TEXT NOT NULL   -- JSON: {crop: kg_absorbable}
);

-- available_at_hr is deliberately NOT stored here: it's per-run mutable
-- state for the algorithm, not a stored fact about a vehicle. Fresh
-- Vehicle objects (available_at_hr=0.0) are built from these rows on
-- every /plan/compute call.

CREATE TABLE IF NOT EXISTS plan_runs (
    id SERIAL PRIMARY KEY,
    created_at TEXT NOT NULL,
    input_snapshot TEXT NOT NULL,              -- JSON
    result_integrated_logistics_optimization TEXT NOT NULL, -- JSON {pools, summary}
    result_individual_transport TEXT NOT NULL, -- JSON {pools, summary}
    result_proximity_pooling TEXT NOT NULL,    -- JSON {pools, summary}
    result_ilo_trace TEXT,                     -- JSON {pool_id: {crop_allocations}} or NULL;
                                               -- run_ilo_v2(..., return_trace=True)'s per-crop
                                               -- market-allocation edges. Used by
                                               -- visualization_adapter.py for exact per-market
                                               -- kg breakdowns.
    result_realistic_baselines TEXT            -- JSON from baselines_v3.py (farm-gate / self-haul /
                                               -- neighbour pooling + farm-gate-valued summaries).
);

CREATE TABLE IF NOT EXISTS sensor_readings (
    id SERIAL PRIMARY KEY,
    pool_id TEXT NOT NULL,
    temperature DOUBLE PRECISION NOT NULL,
    humidity DOUBLE PRECISION NOT NULL,
    timestamp DOUBLE PRECISION NOT NULL
);

-- Road-km matrix between every farmer/market of a scenario (see roads.py plan_distance_model).
CREATE TABLE IF NOT EXISTS road_matrices (
    key TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    profile TEXT NOT NULL,
    points TEXT NOT NULL,      -- JSON [[lat, lng], ...] (rounded, sorted): row/column order of dist
    dist TEXT NOT NULL,        -- JSON square matrix of road km (null = no route)
    ratio DOUBLE PRECISION NOT NULL,
    created_at TEXT NOT NULL
);

-- Real-road geometry cache (see roads.py). Deliberately NOT cleared by /reset:
-- it is keyed by stop coordinates, so it stays valid across plans and scenarios.
CREATE TABLE IF NOT EXISTS road_routes (
    key TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    profile TEXT NOT NULL,
    legs TEXT NOT NULL,        -- JSON [{coordinates, distanceKm, offRoadKm}, ...]
    created_at TEXT NOT NULL
);

-- Farmer portal. PINs are stored only as salted hashes. One row per farmer id.
CREATE TABLE IF NOT EXISTS farmer_credentials (
    farmer_id INTEGER PRIMARY KEY,
    pin_hash TEXT NOT NULL,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until DOUBLE PRECISION NOT NULL DEFAULT 0,   -- unix seconds; 0 = not locked
    created_at DOUBLE PRECISION NOT NULL
);

-- The one plan farmers can see, as ready-made per-farmer cards (so a farmer's request reads one card and never
-- touches the plan itself). A single row (id = 1).
CREATE TABLE IF NOT EXISTS published_plan (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    plan_id INTEGER NOT NULL,
    previous_plan_id INTEGER,
    published_at TEXT NOT NULL,
    cards TEXT NOT NULL      -- JSON: {farmer_id: card}
);

-- Farmer phone numbers for SMS / WhatsApp updates. A number is stored only after the farmer typed back a code sent to it.
CREATE TABLE IF NOT EXISTS farmer_phones (
    farmer_id INTEGER PRIMARY KEY,
    phone TEXT NOT NULL,                  -- E.164, e.g. +919876543210
    lang TEXT NOT NULL DEFAULT 'en',      -- language of the messages (en, te, hi, ta)
    verified_at DOUBLE PRECISION NOT NULL
);

-- One pending code per farmer. Only a keyed digest of the code is kept.
CREATE TABLE IF NOT EXISTS phone_otps (
    farmer_id INTEGER PRIMARY KEY,
    phone TEXT NOT NULL,
    lang TEXT NOT NULL DEFAULT 'en',
    digest TEXT NOT NULL,
    expires_at DOUBLE PRECISION NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    sent_at DOUBLE PRECISION NOT NULL,
    window_start DOUBLE PRECISION NOT NULL,   -- start of the current hour for the send limit
    send_count INTEGER NOT NULL DEFAULT 1
);

-- Every SMS / WhatsApp attempt (no phone numbers and no message text are stored here).
CREATE TABLE IF NOT EXISTS notification_log (
    id BIGSERIAL PRIMARY KEY,
    farmer_id INTEGER NOT NULL,
    channel TEXT NOT NULL,                -- sms | whatsapp
    kind TEXT NOT NULL,                   -- otp | update | changed | welcome
    ok BOOLEAN NOT NULL,
    detail TEXT NOT NULL,
    plan_id INTEGER,
    created_at DOUBLE PRECISION NOT NULL
);

-- Web Push subscriptions (push.py): one row per browser/phone. endpoint is the push service URL, unique per browser.
CREATE TABLE IF NOT EXISTS push_subscriptions (
    endpoint TEXT PRIMARY KEY,
    farmer_id INTEGER NOT NULL,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    lang TEXT NOT NULL DEFAULT 'en',
    created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS push_subscriptions_farmer ON push_subscriptions (farmer_id);

-- WhatsApp Cloud API webhook status events (sent, delivered, read, failed).
CREATE TABLE IF NOT EXISTS whatsapp_delivery_statuses (
    id BIGSERIAL PRIMARY KEY,
    message_id TEXT NOT NULL,
    status TEXT NOT NULL,
    recipient_id TEXT,
    error_code INTEGER,
    error_message TEXT,
    timestamp DOUBLE PRECISION NOT NULL,
    created_at DOUBLE PRECISION NOT NULL,
    CONSTRAINT uniq_wa_msg_status UNIQUE (message_id, status)
);

-- Farmer change requests (see change_requests.py). A farmer's chat message becomes a 'draft'; the farmer's tap on
-- Confirm makes it 'pending'; the admin then approves or rejects it. Nothing here touches the farmers table until
-- the admin approves. JSON columns follow the rest of this file (TEXT holding JSON).
CREATE TABLE IF NOT EXISTS change_requests (
    id BIGSERIAL PRIMARY KEY,
    farmer_id INTEGER NOT NULL,
    raw_text TEXT NOT NULL,        -- what the farmer typed ('[form]' when they used the form instead)
    parsed TEXT NOT NULL,          -- JSON: the validated ChangeParse (what the LLM / form said)
    current TEXT NOT NULL,         -- JSON: the farmer's qty_kg / ready_hr / deadline_hr when the request was made
    proposed TEXT NOT NULL,        -- JSON: the new absolute values, only the fields that change
    status TEXT NOT NULL,          -- draft | pending | approved | rejected | superseded | expired | withdrawn
    reason_code TEXT,              -- set when rejected
    applied_plan_id INTEGER,       -- the plan that applied it, when approved
    created_at DOUBLE PRECISION NOT NULL,
    decided_at DOUBLE PRECISION,
    decided_by TEXT
);
-- One live draft and one pending request per farmer: a newer one replaces the older.
CREATE UNIQUE INDEX IF NOT EXISTS change_requests_one_pending ON change_requests (farmer_id) WHERE status = 'pending';
CREATE UNIQUE INDEX IF NOT EXISTS change_requests_one_draft ON change_requests (farmer_id) WHERE status = 'draft';

-- Whether farmers may send change requests right now (the admin closes it when dispatch starts). A single row
-- (id = 1); no row means open.
CREATE TABLE IF NOT EXISTS change_window (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    is_open BOOLEAN NOT NULL
);
"""


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Put your Neon connection string in "
            "backend/.env (see .env.example) and start uvicorn with --env-file .env."
        )
    return url


@contextmanager
def get_conn():
    # dict_row: rows are dicts, so r["id"] works exactly like sqlite3.Row did.
    # No autocommit: callers commit explicitly; closing without commit rolls back.
    # prepare_threshold=None: no server-side prepared statements, which is the
    # safe setting behind Neon's pooled (PgBouncer) endpoint.
    conn = psycopg.connect(
        _database_url(), row_factory=dict_row, connect_timeout=15, prepare_threshold=None
    )
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute(SCHEMA)
        conn.commit()
