-- 016_external_repairs.sql
-- Sprint C9: pad-ספק repairs that happen physically at branches and never
-- pass through Priority. Captured manually via the new "טיפול בספקים" tab,
-- optionally OCR'd from photographed handwritten vendor reports.

CREATE TABLE IF NOT EXISTS external_repairs (
    id              BIGSERIAL PRIMARY KEY,
    repair_date     DATE NOT NULL,
    vendor          TEXT NOT NULL,
    sender_name     TEXT,
    branch_code     TEXT NOT NULL REFERENCES branches(code) ON UPDATE CASCADE,
    luggage_type    TEXT,
    part_sku        TEXT,
    repair_notes    TEXT,
    amount_due      NUMERIC(10,2) NOT NULL,
    -- TO_CHAR אינו IMMUTABLE (תלוי ב-lc_time) אז אנחנו בונים את ה-string ידנית.
    year_month      TEXT GENERATED ALWAYS AS (
        LPAD(EXTRACT(YEAR FROM repair_date)::TEXT, 4, '0') || '-' ||
        LPAD(EXTRACT(MONTH FROM repair_date)::TEXT, 2, '0')
    ) STORED,
    created_by      TEXT,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_external_repairs_ym     ON external_repairs(year_month);
CREATE INDEX IF NOT EXISTS idx_external_repairs_vendor ON external_repairs(vendor);
CREATE INDEX IF NOT EXISTS idx_external_repairs_branch ON external_repairs(branch_code);
