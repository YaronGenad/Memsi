-- 001_domain_tables.sql
-- מעביר את ה-domain data שהיה ב-pricing_data.py / branch_names.py /
-- warehouse_config.py / product_identification.py אל טבלאות PostgreSQL.
--
-- כל הטבלאות עם updated_at + updated_by ל-audit פשוט.

-- ============================================================
--  Customers — מיפוי קוד לקוח (Priority) → tier מחירון
-- ============================================================
CREATE TABLE IF NOT EXISTS customers (
    code            TEXT PRIMARY KEY,           -- 360010009 וכו'
    pricing_tier    TEXT NOT NULL,              -- ELAL / AIR_FRANCE_KLM / DELTA / QAS_LAUFER / ...
    name            TEXT,                        -- שם תצוגה (אם נדע)
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    notes           TEXT,
    updated_by      TEXT,
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_customers_tier ON customers (pricing_tier);

-- ============================================================
--  Pricing tiers (rows from REPAIR_PRICING / REPLACEMENT_PRICING)
-- ============================================================
CREATE TABLE IF NOT EXISTS pricing_tiers (
    code            TEXT PRIMARY KEY,           -- ELAL / AIR_FRANCE_KLM / QAS / LAUFER / DELTA / QAS_LAUFER
    description     TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    updated_by      TEXT,
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ============================================================
--  Customer repair pricing — מחיר תיקון לפי tier ומק"ט
-- ============================================================
CREATE TABLE IF NOT EXISTS customer_repair_prices (
    pricing_tier    TEXT NOT NULL REFERENCES pricing_tiers(code) ON UPDATE CASCADE,
    part_sku        TEXT NOT NULL,              -- 900000101 וכו'
    price           NUMERIC(10,2) NOT NULL,
    updated_by      TEXT,
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (pricing_tier, part_sku)
);

-- ============================================================
--  Customer replacement pricing — מחיר החלפה לפי tier וסוג מזוודה
-- ============================================================
CREATE TABLE IF NOT EXISTS customer_replacement_prices (
    pricing_tier    TEXT NOT NULL REFERENCES pricing_tiers(code) ON UPDATE CASCADE,
    luggage_type    TEXT NOT NULL,              -- "טרולי קלאסית רכה" וכו'
    price           NUMERIC(10,2) NOT NULL,
    updated_by      TEXT,
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (pricing_tier, luggage_type)
);

-- ============================================================
--  Supplier pricing — תשלום לספק (לא תלוי בלקוח)
-- ============================================================
CREATE TABLE IF NOT EXISTS supplier_repair_prices (
    part_sku        TEXT PRIMARY KEY,
    price           NUMERIC(10,2) NOT NULL,
    updated_by      TEXT,
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS supplier_replacement_prices (
    luggage_type    TEXT PRIMARY KEY,
    price           NUMERIC(10,2) NOT NULL,
    updated_by      TEXT,
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ============================================================
--  Branches — קוד סניף → שם תצוגה
-- ============================================================
CREATE TABLE IF NOT EXISTS branches (
    code            TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    region          TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    updated_by      TEXT,
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ============================================================
--  Warehouses — מחסנים
-- ============================================================
CREATE TABLE IF NOT EXISTS warehouses (
    code            INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    is_approved     BOOLEAN NOT NULL DEFAULT TRUE,  -- היה ברשימת APPROVED_WAREHOUSES
    updated_by      TEXT,
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ============================================================
--  Luggage identification — תיאור מוצר → קטגוריית מזוודה
-- ============================================================
CREATE TABLE IF NOT EXISTS luggage_identification (
    description     TEXT PRIMARY KEY,
    category        TEXT NOT NULL,              -- "טרולי קלאסית קשיחה" וכו'
    updated_by      TEXT,
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_luggage_identification_category
    ON luggage_identification (category);

-- ============================================================
--  Audit log — שמירת היסטוריית שינויים (insert-only)
-- ============================================================
CREATE TABLE IF NOT EXISTS domain_audit_log (
    id              SERIAL PRIMARY KEY,
    table_name      TEXT NOT NULL,
    operation       TEXT NOT NULL,              -- INSERT / UPDATE / DELETE
    key_json        JSONB NOT NULL,             -- {"pricing_tier":"ELAL","part_sku":"900000101"}
    old_values      JSONB,
    new_values      JSONB,
    changed_by      TEXT,
    changed_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_table_time
    ON domain_audit_log (table_name, changed_at DESC);
