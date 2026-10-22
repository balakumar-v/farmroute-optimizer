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
