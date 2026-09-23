"""
database.py
------------
Plain sqlite3, no ORM -- this is a local course demo, not a deployed
service. One file (fpo.db) created next to this module.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent / "fpo.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS farmers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    crop TEXT NOT NULL,
    qty_kg REAL NOT NULL,
    ready_hr REAL NOT NULL,
    deadline_hr REAL NOT NULL,
    needs_refrigeration INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS vehicles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type_name TEXT NOT NULL,
    capacity_kg REAL NOT NULL,
    refrigerated INTEGER NOT NULL,
    fixed_cost REAL NOT NULL,
    per_km_cost REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS markets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    price TEXT NOT NULL,        -- JSON: {crop: inr_per_kg}
    capacity_kg TEXT NOT NULL   -- JSON: {crop: kg_absorbable}
);

-- available_at_hr is deliberately NOT stored here: it's per-run mutable
-- state for the algorithm, not a stored fact about a vehicle. Fresh
-- Vehicle objects (available_at_hr=0.0) are built from these rows on
-- every /plan/compute call.

CREATE TABLE IF NOT EXISTS plan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    input_snapshot TEXT NOT NULL,              -- JSON
    result_our_system TEXT NOT NULL,           -- JSON {pools, summary}
    result_individual_transport TEXT NOT NULL, -- JSON {pools, summary}
    result_proximity_pooling TEXT NOT NULL     -- JSON {pools, summary}
);

CREATE TABLE IF NOT EXISTS sensor_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pool_id TEXT NOT NULL,
    temperature REAL NOT NULL,
    humidity REAL NOT NULL,
    timestamp REAL NOT NULL
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        conn.commit()
