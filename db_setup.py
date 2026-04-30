# -*- coding: utf-8 -*-
"""
db_setup.py — bootstrap schema for all PostgreSQL tables.

Run once on a fresh installation, or re-run safely at any time
(all statements use CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS).

Usage:
    python db_setup.py
"""
import sys
import psycopg2
from db_config import DB_CONFIG
from logger import logger

# ── Cache tables (cache_manager.py) ──────────────────────────────────────────

_CREATE_DOCUMENTS = """
CREATE TABLE IF NOT EXISTS documents (
    docno         TEXT PRIMARY KEY,
    curdate       DATE,
    custname      TEXT,
    custdes       TEXT,
    cdes          TEXT,
    details       TEXT,
    statdes       TEXT,
    ownerlogin    TEXT,
    branchname    TEXT,
    retl_details1 TEXT
);
"""

_CREATE_LOGFILE = """
CREATE TABLE IF NOT EXISTS logfile (
    id          SERIAL PRIMARY KEY,
    logdocno    TEXT,
    curdate     DATE,
    partname    TEXT,
    topartdes   TEXT,
    tquant      NUMERIC,
    ucost       NUMERIC,
    custname    TEXT
);
"""

# Composite unique index — prevents silent duplicates on refresh/backfill.
# Uses all available fields because Priority has no single logfile row ID.
_CREATE_LOGFILE_UNIQUE_IDX = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_logfile_row
    ON logfile (logdocno, partname, topartdes, tquant, ucost, curdate)
    WHERE logdocno IS NOT NULL;
"""

_CREATE_CACHE_METADATA = """
CREATE TABLE IF NOT EXISTS cache_metadata (
    data_type    TEXT        NOT NULL,
    year_month   TEXT        NOT NULL,
    start_date   DATE,
    end_date     DATE,
    record_count INTEGER     DEFAULT 0,
    fetched_at   TIMESTAMP   DEFAULT NOW(),
    PRIMARY KEY (data_type, year_month)
);
"""

# ── Forecast tables (forecast_db.py) ─────────────────────────────────────────

_CREATE_FORECAST_HISTORY = """
CREATE TABLE IF NOT EXISTS forecast_history (
    id           SERIAL PRIMARY KEY,
    branch       TEXT    NOT NULL,
    luggage_type TEXT    NOT NULL,
    year_month   TEXT    NOT NULL,
    quantity     INTEGER NOT NULL DEFAULT 0,
    updated_at   TIMESTAMP DEFAULT NOW(),
    UNIQUE (branch, luggage_type, year_month)
);
"""

_CREATE_FORECAST_EVENTS = """
CREATE TABLE IF NOT EXISTS forecast_events (
    year_month     TEXT PRIMARY KEY,
    is_war         SMALLINT DEFAULT 0,
    is_military_op SMALLINT DEFAULT 0,
    is_ceasefire   SMALLINT DEFAULT 0,
    jewish_holiday SMALLINT DEFAULT 0,
    season         SMALLINT DEFAULT 0,
    is_summer_peak SMALLINT DEFAULT 0,
    travel_impact  TEXT DEFAULT 'normal',
    notes          TEXT DEFAULT ''
);
"""

_ALL_STATEMENTS = [
    ("documents",        _CREATE_DOCUMENTS),
    ("logfile",          _CREATE_LOGFILE),
    ("logfile_uq_index", _CREATE_LOGFILE_UNIQUE_IDX),
    ("cache_metadata",   _CREATE_CACHE_METADATA),
    ("forecast_history", _CREATE_FORECAST_HISTORY),
    ("forecast_events",  _CREATE_FORECAST_EVENTS),
]


def setup_db(verbose: bool = True) -> bool:
    """
    יוצר את כל הטבלאות והאינדקסים אם לא קיימים.
    מחזיר True אם הצליח, False אם נכשל.
    """
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        with conn.cursor() as cur:
            for name, sql in _ALL_STATEMENTS:
                cur.execute(sql)
                if verbose:
                    print(f"  ✓ {name}")
        conn.commit()
        conn.close()
        logger.info("db_setup: all tables and indexes verified OK")
        if verbose:
            print("\nמסד הנתונים מוכן.")
        return True
    except Exception as e:
        logger.error("db_setup failed: %s", e)
        if verbose:
            print(f"\n✗ שגיאה: {e}", file=sys.stderr)
        return False


if __name__ == '__main__':
    print("מגדיר סכמה...")
    ok = setup_db()
    sys.exit(0 if ok else 1)
