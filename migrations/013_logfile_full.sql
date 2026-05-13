-- 013_logfile_full.sql
-- Sprint B2 (continued): טבלה מלאה של תנועות-מלאי לכל המק"טים והמחסנים.
--
-- ההבדל מ-logfile הקיים: logfile מסונן ללקוחות-מבוטחים בלבד (לצורך דוחות-מכירה).
-- logfile_full כולל הכל — תנועות-בין-מחסנים, ספירות (IC), תיקונים (IK), הכל.
-- נדרש לחישוב נכון של local_inventory עם איפוסי-ספירה.
--
-- מבנה דומה ל-logfile אבל עם הרחבות שצריכות לחישוב:
-- - logdocno (לזיהוי IC ו-טיפוס תעודה)
-- - warhsname / towarhsname (מחסן מקור / יעד)
-- - is_ic_reset boolean: מסומן בעיבוד, אומר אם התעודה היא ספירת-איפוס
--   (כל השורות שלה qty=0)

CREATE TABLE IF NOT EXISTS logfile_full (
    id              BIGSERIAL PRIMARY KEY,
    logdocno        TEXT,
    curdate         TIMESTAMPTZ,
    partname        TEXT NOT NULL,
    warhsname       TEXT,
    towarhsname     TEXT,
    tquant          NUMERIC(12,2) NOT NULL,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- מניעת כפילויות. ה-LOGDOCNO+PARTNAME+WARHSNAME+TOWARHSNAME+TQUANT+CURDATE
-- אמורים להיות ייחודיים (כי אין ID יחיד ב-Priority).
CREATE UNIQUE INDEX IF NOT EXISTS uq_logfile_full_row
    ON logfile_full (logdocno, partname, warhsname, towarhsname, tquant, curdate)
    WHERE logdocno IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_logfile_full_part_wh
    ON logfile_full (partname, warhsname);
CREATE INDEX IF NOT EXISTS idx_logfile_full_part_to
    ON logfile_full (partname, towarhsname);
CREATE INDEX IF NOT EXISTS idx_logfile_full_curdate
    ON logfile_full (curdate);
CREATE INDEX IF NOT EXISTS idx_logfile_full_docno
    ON logfile_full (logdocno);

-- ============================================================
--  ic_doc_classification: סיווג של כל IC doc.
--  RESET = כל השורות שלו qty=0 → מאפס.
--  ADD   = יש לו לפחות שורה אחת qty != 0 → מוסיף.
-- ============================================================
CREATE TABLE IF NOT EXISTS ic_doc_classification (
    logdocno        TEXT NOT NULL,
    warhsname       TEXT NOT NULL,        -- ה-warehouse שאליו התעודה רלוונטית (TOWARHSNAME)
    doc_type        TEXT NOT NULL CHECK (doc_type IN ('reset', 'add')),
    classified_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (logdocno, warhsname)
);

CREATE INDEX IF NOT EXISTS idx_ic_class_warhsname
    ON ic_doc_classification (warhsname);
