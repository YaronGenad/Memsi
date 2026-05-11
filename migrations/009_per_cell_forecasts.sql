-- 009_per_cell_forecasts.sql
-- Sprint C2: תחזיות פר-(branch, cell) במקום פר-אגרגט.
-- מרחיב את forecast_metrics ו-forecast_predictions לתמוך בעמודות branch/cell.
-- שומר תאימות עם השורות הקיימות (אגרגט) על-ידי השארת branch/cell כ-NULL.

ALTER TABLE forecast_predictions
    ADD COLUMN IF NOT EXISTS branch TEXT,
    ADD COLUMN IF NOT EXISTS cell   TEXT;

ALTER TABLE forecast_metrics
    ADD COLUMN IF NOT EXISTS branch TEXT,
    ADD COLUMN IF NOT EXISTS cell   TEXT,
    ADD COLUMN IF NOT EXISTS n_obs  INTEGER,           -- כמה חודשים היו ב-training
    ADD COLUMN IF NOT EXISTS fallback_level TEXT;      -- 'cell' / 'branch' / 'category' / 'global'

-- ה-PK הישן (run_id, model, year_month) ו-(run_id, model) לא ייחודיים יותר
-- כשיש שורות פר-(branch, cell). מסירים את ה-PK הישן ויוצרים unique-index
-- שמתייחס ל-NULLs כשווים (NULLS NOT DISTINCT ב-PG 15+).
ALTER TABLE forecast_predictions DROP CONSTRAINT IF EXISTS forecast_predictions_pkey;
ALTER TABLE forecast_metrics     DROP CONSTRAINT IF EXISTS forecast_metrics_pkey;

CREATE UNIQUE INDEX IF NOT EXISTS uq_forecast_predictions_full
    ON forecast_predictions (run_id, model, year_month, branch, cell)
    NULLS NOT DISTINCT;

CREATE UNIQUE INDEX IF NOT EXISTS uq_forecast_metrics_full
    ON forecast_metrics (run_id, model, branch, cell)
    NULLS NOT DISTINCT;

CREATE INDEX IF NOT EXISTS idx_forecast_predictions_branch_cell
    ON forecast_predictions (run_id, branch, cell);
CREATE INDEX IF NOT EXISTS idx_forecast_metrics_branch_cell
    ON forecast_metrics (run_id, branch, cell);
