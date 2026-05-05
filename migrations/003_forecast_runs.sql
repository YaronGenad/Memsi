-- 003_forecast_runs.sql
-- שמירת כל ריצות התחזית כדי להשוות תחזית לבפועל בעתיד.
--
-- כל ריצה (run_id) שומרת:
--   - מטא-דאטה: מי הריץ, מתי, על איזה סלייס (branches+categories), אופק, context.
--   - תחזיות: שורה לכל (model, year_month) עם forecast/lower/upper.
--   - מטריקות אחרונות: train/test על הסדרה ההיסטורית, MAE/RMSE לכל מודל.
--
-- מאפשר: לזהות drift, להציג "אמינות מודל" מבוססת היסטוריה,
-- ולחבר תחזית מול actual כשהחודש מסתיים.

CREATE TABLE IF NOT EXISTS forecast_runs (
    run_id          SERIAL PRIMARY KEY,
    ran_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    ran_by          TEXT,
    branches        TEXT[]   NOT NULL,    -- ARRAY כדי להחזיק slice
    categories      TEXT[]   NOT NULL,
    horizon_months  SMALLINT NOT NULL,
    context_json    JSONB,                -- is_war / is_summer_peak / וכו'
    series_n        INTEGER,              -- כמה חודשי היסטוריה היו זמינים
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_forecast_runs_ran_at
    ON forecast_runs (ran_at DESC);


-- תחזיות עצמן - שורה לכל (run, model, year_month)
CREATE TABLE IF NOT EXISTS forecast_predictions (
    run_id          INTEGER NOT NULL REFERENCES forecast_runs(run_id) ON DELETE CASCADE,
    model           TEXT NOT NULL,        -- arima / prophet / xgboost / avg
    year_month      TEXT NOT NULL,        -- 2026-05 וכו'
    forecast        NUMERIC(12,2) NOT NULL,
    lower           NUMERIC(12,2),
    upper           NUMERIC(12,2),
    PRIMARY KEY (run_id, model, year_month)
);

CREATE INDEX IF NOT EXISTS idx_forecast_predictions_ym
    ON forecast_predictions (year_month);


-- מטריקות train/test לכל מודל בריצה
CREATE TABLE IF NOT EXISTS forecast_metrics (
    run_id          INTEGER NOT NULL REFERENCES forecast_runs(run_id) ON DELETE CASCADE,
    model           TEXT NOT NULL,
    test_n          INTEGER,              -- מספר נקודות בvalidation
    mae             NUMERIC(12,2),        -- mean absolute error
    rmse            NUMERIC(12,2),        -- root mean squared error
    mape            NUMERIC(8,2),         -- mean absolute percentage error (אם מוגדר)
    PRIMARY KEY (run_id, model)
);
