-- 017_external_repairs_damage_report.sql
-- Sprint C9.1: add damage_report_number to external_repairs.
-- Captured manually only (OCR doesn't read this field from vendor reports).
-- Used for cross-referencing the company's internal damage-report flow.

ALTER TABLE external_repairs
    ADD COLUMN IF NOT EXISTS damage_report_number TEXT;

CREATE INDEX IF NOT EXISTS idx_external_repairs_damage_report
    ON external_repairs(damage_report_number)
    WHERE damage_report_number IS NOT NULL;
