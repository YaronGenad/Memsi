-- 014_logfile_full_dedupe.sql
-- תיקון: ה-unique index הקודם לא תפס כפילויות עם warhsname=NULL כי
-- ב-Postgres NULL!=NULL. שורות עם warhsname=NULL (כל ה-IC docs במחסן יעד
-- בלבד) נכפלו בסנכרון.
--
-- 1. dedupe ידני.
-- 2. החלפת ה-unique index לעמודות מנורמלות (COALESCE ל-empty-string).

-- שלב 1: dedupe
DELETE FROM logfile_full a
USING logfile_full b
WHERE a.id < b.id
  AND COALESCE(a.logdocno, '')    = COALESCE(b.logdocno, '')
  AND COALESCE(a.warhsname, '')   = COALESCE(b.warhsname, '')
  AND COALESCE(a.towarhsname, '') = COALESCE(b.towarhsname, '')
  AND a.partname = b.partname
  AND a.tquant   = b.tquant
  AND a.curdate  = b.curdate;

-- שלב 2: index חדש שתופס גם NULL
DROP INDEX IF EXISTS uq_logfile_full_row;

CREATE UNIQUE INDEX uq_logfile_full_row
    ON logfile_full (
        COALESCE(logdocno, ''),
        partname,
        COALESCE(warhsname, ''),
        COALESCE(towarhsname, ''),
        tquant,
        curdate
    );
