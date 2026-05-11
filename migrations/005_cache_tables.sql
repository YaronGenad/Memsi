-- 005_cache_tables.sql
-- מעביר את כל ה-DDL שהיה ב-db_setup.py למסלול המיגרציות.
-- לאחר ריצת המיגרציה הזאת, db_setup.py יימחק.
--
-- כל הטבלאות כבר קיימות במערכות עובדות (נוצרו על-ידי setup_db ב-startup).
-- המיגרציה משתמשת ב-IF NOT EXISTS כדי שתעבור בשקט גם על DB שכבר אותחל.

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

-- Composite unique index — מונע כפילויות שקטות ב-refresh/backfill.
-- משתמש בכל השדות הזמינים כי ל-Priority אין logfile-row-id יחיד.
CREATE UNIQUE INDEX IF NOT EXISTS uq_logfile_row
    ON logfile (logdocno, partname, topartdes, tquant, ucost, curdate)
    WHERE logdocno IS NOT NULL;

CREATE TABLE IF NOT EXISTS cache_metadata (
    data_type    TEXT        NOT NULL,
    year_month   TEXT        NOT NULL,
    start_date   DATE,
    end_date     DATE,
    record_count INTEGER     DEFAULT 0,
    fetched_at   TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (data_type, year_month)
);

CREATE TABLE IF NOT EXISTS forecast_history (
    id           SERIAL PRIMARY KEY,
    branch       TEXT    NOT NULL,
    luggage_type TEXT    NOT NULL,
    year_month   TEXT    NOT NULL,
    quantity     INTEGER NOT NULL DEFAULT 0,
    updated_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (branch, luggage_type, year_month)
);

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
