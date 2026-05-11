-- 007_flight_traffic_and_regimes.sql
-- תשתית ל-scenario engine: נתוני טיסות BG + סיווג regime של conversion.
--
-- רקע: גילינו ש-correlation בין מספר-נחיתות לבין כמות-תיקונים-בחנויות
-- אינו ישיר. הקפיצה של קיץ-2024 (~165 תיקונים/100K נחיתות) לעומת קיץ-2023
-- (~50) מסבירה למה ה-correlation נראה שלילי. כלומר conversion-rate משתנה
-- לפי regime, לא רק לפי volume.
--
-- ה-scenario engine ייצור תחזיות מ-2 משתנים:
--   1. flights forecast (תרחיש: status_quo / escalation / gradual / open_skies)
--   2. conversion regime (low ~50 / medium ~80 / high ~150)
-- ואז: expected_demand = flights × conversion_rate_for_regime.

-- ============================================================
--  flight_traffic - נתוני BG חודשיים מ-IAA monthly reports
-- ============================================================
CREATE TABLE IF NOT EXISTS flight_traffic (
    year_month          TEXT PRIMARY KEY,        -- 'YYYY-MM'
    total_passengers    BIGINT,                  -- סה"כ נוסעים (כניסות + יציאות)
    arriving_passengers BIGINT,                  -- נוסעים נכנסים — הסיגנל הרלוונטי
    total_flights       INTEGER,                 -- סה"כ תנועות אוויר
    arriving_flights    INTEGER,                 -- רק נחיתות
    source_url          TEXT,                    -- ל-traceability
    notes               TEXT,                    -- "ok" או הסבר על ערך חריג/חסר
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_flight_traffic_ym ON flight_traffic (year_month);

-- ============================================================
--  conversion_regime ב-forecast_events
-- ============================================================
-- שלוש רמות אקסקלוסיביות. NULL = לא-מסומן (יחושב כדיפולט בחיזוי).
-- LOW    ~50 תיקונים/100K נחיתות (pre-war, post-trauma)
-- MEDIUM ~80 (late-war recovery, ceasefire רגיל)
-- HIGH   ~150 (backlog-burning בשגרת-מלחמה)
ALTER TABLE forecast_events
    ADD COLUMN IF NOT EXISTS conversion_regime TEXT
    CHECK (conversion_regime IS NULL OR conversion_regime IN ('LOW','MEDIUM','HIGH'));

CREATE INDEX IF NOT EXISTS idx_forecast_events_regime
    ON forecast_events (conversion_regime)
    WHERE conversion_regime IS NOT NULL;
