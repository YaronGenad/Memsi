-- 012_kit_bom_and_local_inventory.sql
-- Sprint B2: BOM של סטים ומלאי-אמיתי-לאחר-פירוק.
--
-- בעיה: Priority מנהל את הסטים-של-המזוודות כיחידה אחת ב-PARTBAL. כשחנות
-- מוכרת רכיב-בודד-מסט, ה-PARTBAL של הרכיב יורד אבל ה-PARTBAL של הסט לא
-- מתעדכן. תוצאה: הסט מציג מלאי-חיובי-מטעה, והרכיבים מציגים מינוסים.
--
-- פתרון: kit_bom מאחסן את המבנה של כל סט (אלו רכיבים יש לו, ביחס 1:1).
-- local_inventory מחשב מלאי-אמיתי לכל (warehouse, component):
--   local_inv[c] = PARTBAL[c] + Σ PARTBAL[kit containing c]
-- כלומר: כל סט-במלאי נחשב כמספר-הרכיבים שלו.
--
-- המק"טים-של-הסט עצמם (sku שמסתיים ב-'-00') לא מופיעים ב-local_inventory.
-- רק הרכיבים.

-- ============================================================
--  kit_bom — Bill of Materials של סטים
-- ============================================================
CREATE TABLE IF NOT EXISTS kit_bom (
    parent_sku   TEXT NOT NULL,   -- SKU של הסט, למשל 'DISPP03-001-00'
    child_sku    TEXT NOT NULL,   -- SKU של רכיב, למשל 'DISPP03-001-0L'
    -- ה-BOM אצלנו תמיד 1:1 (אומת מול המשתמש בעת התכנון).
    -- שדה quantity לא נחוץ כרגע, ניתן להוסיף בעתיד אם יתגלו חריגות.
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (parent_sku, child_sku)
);

CREATE INDEX IF NOT EXISTS idx_kit_bom_child   ON kit_bom (child_sku);
CREATE INDEX IF NOT EXISTS idx_kit_bom_parent  ON kit_bom (parent_sku);


-- ============================================================
--  local_inventory — מלאי-אמיתי-לאחר-פירוק-סטים
-- ============================================================
CREATE TABLE IF NOT EXISTS local_inventory (
    warehouse_code  TEXT NOT NULL,
    sku             TEXT NOT NULL,
    quantity        NUMERIC(12,2) NOT NULL,
    last_calculated TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (warehouse_code, sku)
);

CREATE INDEX IF NOT EXISTS idx_local_inventory_sku  ON local_inventory (sku);


-- ============================================================
--  kit_bom_build_log — תיעוד בנייה
-- ============================================================
CREATE TABLE IF NOT EXISTS kit_bom_build_log (
    build_id        SERIAL PRIMARY KEY,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    kits_found      INTEGER,
    components_found INTEGER,
    families_processed INTEGER,
    notes           TEXT
);
