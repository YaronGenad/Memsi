-- 006_timestamps_tz.sql
-- ממיר את כל עמודות ה-TIMESTAMP (ללא TZ) ל-TIMESTAMPTZ.
-- ההנחה: הנתונים הקיימים נכתבו ב-Asia/Jerusalem (שעון המקומי של ה-app
-- והמכונות שמריצות אותו). ב-ALTER, נתונים קיימים נחשבים כאילו נכתבו ב-TZ
-- הזה ומומרים ל-UTC פנימית.
--
-- חשוב: אם DB ישן עבר את המיגרציה הזאת, ערכי הזמן ההיסטוריים מסומנים
-- כ-Asia/Jerusalem retroactively. אם בעבר הנתונים נכתבו בפועל ב-UTC,
-- יש קונפליקט — תקן ידנית. במערכת הקיימת כל הקוד אינו מציין TZ ולכן
-- ההנחה נכונה.

ALTER TABLE customers
    ALTER COLUMN updated_at TYPE TIMESTAMPTZ
    USING updated_at AT TIME ZONE 'Asia/Jerusalem';

ALTER TABLE pricing_tiers
    ALTER COLUMN updated_at TYPE TIMESTAMPTZ
    USING updated_at AT TIME ZONE 'Asia/Jerusalem';

ALTER TABLE customer_repair_prices
    ALTER COLUMN updated_at TYPE TIMESTAMPTZ
    USING updated_at AT TIME ZONE 'Asia/Jerusalem';

ALTER TABLE customer_replacement_prices
    ALTER COLUMN updated_at TYPE TIMESTAMPTZ
    USING updated_at AT TIME ZONE 'Asia/Jerusalem';

ALTER TABLE supplier_repair_prices
    ALTER COLUMN updated_at TYPE TIMESTAMPTZ
    USING updated_at AT TIME ZONE 'Asia/Jerusalem';

ALTER TABLE supplier_replacement_prices
    ALTER COLUMN updated_at TYPE TIMESTAMPTZ
    USING updated_at AT TIME ZONE 'Asia/Jerusalem';

ALTER TABLE branches
    ALTER COLUMN updated_at TYPE TIMESTAMPTZ
    USING updated_at AT TIME ZONE 'Asia/Jerusalem';

ALTER TABLE warehouses
    ALTER COLUMN updated_at TYPE TIMESTAMPTZ
    USING updated_at AT TIME ZONE 'Asia/Jerusalem';

ALTER TABLE luggage_identification
    ALTER COLUMN updated_at TYPE TIMESTAMPTZ
    USING updated_at AT TIME ZONE 'Asia/Jerusalem';

ALTER TABLE domain_audit_log
    ALTER COLUMN changed_at TYPE TIMESTAMPTZ
    USING changed_at AT TIME ZONE 'Asia/Jerusalem';

ALTER TABLE forecast_runs
    ALTER COLUMN ran_at TYPE TIMESTAMPTZ
    USING ran_at AT TIME ZONE 'Asia/Jerusalem';

-- cache_metadata.fetched_at ו-forecast_history.updated_at מוגדרות
-- כ-TIMESTAMPTZ כבר ב-005_cache_tables.sql, כך שאין צורך לטפל בהן כאן.
-- אם DB ישן עוד מחזיק אותן כ-TIMESTAMP, נטפל בהן בנפרד:

DO $$
BEGIN
    IF (SELECT data_type FROM information_schema.columns
        WHERE table_name = 'cache_metadata' AND column_name = 'fetched_at')
       = 'timestamp without time zone' THEN
        EXECUTE 'ALTER TABLE cache_metadata
                 ALTER COLUMN fetched_at TYPE TIMESTAMPTZ
                 USING fetched_at AT TIME ZONE ''Asia/Jerusalem''';
    END IF;

    IF (SELECT data_type FROM information_schema.columns
        WHERE table_name = 'forecast_history' AND column_name = 'updated_at')
       = 'timestamp without time zone' THEN
        EXECUTE 'ALTER TABLE forecast_history
                 ALTER COLUMN updated_at TYPE TIMESTAMPTZ
                 USING updated_at AT TIME ZONE ''Asia/Jerusalem''';
    END IF;
END $$;
