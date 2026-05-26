# -*- coding: utf-8 -*-
"""
kit_bom_builder.py — בניית טבלת kit_bom מ-Priority LOGPART.

הלוגיקה:
1. שולפים את כל הפריטים מ-LOGPART בקטגוריית-מזוודות (DIS*, BAGG*, CLBS*, DISPP*).
2. לכל פריט, ה-MPARTNAME הוא מפתח-המשפחה (DISPP03 vs DISPP03SL = משפחות נפרדות).
3. ה-variant הוא החלק שאחרי MPARTNAME ב-PARTNAME, ללא ה-size בקצה.
   PARTNAME = MPARTNAME-VARIANT-SIZE.
4. בכל קבוצה (MPARTNAME, VARIANT):
   - מק"ט עם SIZE='00' הוא הסט.
   - שאר המק"טים הם רכיביו.
5. אם בקבוצה אין SIZE='00' — אלה מק"טים-עצמאיים, לא BOM.

יחס: תמיד 1:1 (אומת מול המשתמש בתכנון Sprint B2).
"""
from __future__ import annotations
import logging
from collections import defaultdict
from datetime import datetime

import requests
from psycopg2.extras import execute_values

from db_config import get_conn
from logger import logger


# ה-prefixes של מק"טים-של-מזוודות. בקטגוריות אחרות (בגדים 00001-*) המבנה
# של MPARTNAME שונה ולא תקף כאן.
LUGGAGE_PREFIXES = ('DIS', 'BAGG', 'CLBS', 'DISPP')

# קוד-המק"ט-של-הסט תמיד מסתיים ב-'-00' (variant-suffix). הרכיבים מסתיימים
# במידה אחרת: -0S, -0M, -0L, -0XL, -S, -L, -M, -XL וכו'.
KIT_SIZE = '00'


def _parse_sku(partname: str, mpartname: str) -> tuple[str, str] | None:
    """מפרק PARTNAME ל-(variant, size). מצריך MPARTNAME ידוע.

    החזרה: (variant, size) או None אם הפרסור נכשל.

    דוגמה:
        PARTNAME='DISPP03SL-001-0L', MPARTNAME='DISPP03SL'
        → variant='001', size='0L'

        PARTNAME='DIS065-001-00', MPARTNAME='DIS065'
        → variant='001', size='00'
    """
    if not partname or not mpartname:
        return None
    if not partname.startswith(mpartname + '-'):
        return None
    rest = partname[len(mpartname) + 1:]  # אחרי 'MPARTNAME-'
    if '-' not in rest:
        return None
    variant, size = rest.rsplit('-', 1)
    return (variant, size)


def _is_luggage_sku(partname: str | None) -> bool:
    if not partname:
        return False
    return any(partname.startswith(p) for p in LUGGAGE_PREFIXES)


def fetch_all_luggage_parts() -> list[dict]:
    """מושך מ-LOGPART רק את המק"טים שכבר היו בעסקאות שלנו, ואת כל בני-משפחתם.

    הסיבה: LOGPART של פריוריטי גדול-מדי לשליפה כוללת (timeout). הגישה:
    1. שולפים מ-forecast_history את כל ה-PARTNAMEs הייחודיים שיש להם
       קונבנציית-מק"ט של מזוודה (DIS*, BAGG*, ...).
    2. מחלצים מהם MPARTNAMEs ייחודיים (חלק ראשון לפני המקף).
    3. לכל MPARTNAME, שולחים שאילתה צרה ל-Priority: MPARTNAME eq '<x>'.
       זה מחזיר ~50 שורות לשאילתה, מהיר.
    4. מאחדים את הכל.
    """
    import os
    from db_config import get_conn

    base_url = os.environ['PRIORITY_BASE_URL']
    auth = os.environ['PRIORITY_AUTH_HEADER']

    # שלב 1: PARTNAMEs ייחודיים מהעבר העסקי שלנו
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT partname FROM logfile
                WHERE partname IS NOT NULL
                  AND partname != ''
            """)
            all_skus = {r[0] for r in cur.fetchall() if r[0]}

    luggage_skus = {s for s in all_skus if _is_luggage_sku(s)}
    logger.info("kit_bom: %d luggage SKUs in forecast/logfile history",
                len(luggage_skus))

    # שלב 2: לחלץ MPARTNAMEs. ההנחה היא ש-MPARTNAME הוא חלק ראשון לפני '-'.
    # מאחר ויש מק"טים-מרכז עם dash בתוכם (כמו DISPP03SL-001-0L), נסמוך על
    # הקונבנציה הבסיסית: MPARTNAME הוא prefix של PARTNAME עד '-' הראשון.
    # שאילתה לפריוריטי תאמת זאת.
    candidate_mparts = set()
    for sku in luggage_skus:
        # קודם חלק ראשון לפני המקף, אחר-כך השני אם יש
        # אנחנו לא יודעים בוודאות מהו MPARTNAME — נסה כמה אפשרויות
        parts = sku.split('-')
        if len(parts) >= 1:
            candidate_mparts.add(parts[0])           # DIS207
        if len(parts) >= 2:
            candidate_mparts.add('-'.join(parts[:2]))  # DIS207-001 (אם DIS207 לא קיים)

    # שלב 3: לכל מועמד, שלח שאילתה ל-Priority
    all_parts: list[dict] = []
    tried_mparts = set()
    from fetch_combined import odata_escape
    for mpart in sorted(candidate_mparts):
        if mpart in tried_mparts:
            continue
        tried_mparts.add(mpart)
        try:
            r = requests.get(
                f'{base_url}/LOGPART',
                headers={'Authorization': auth},
                params={
                    '$filter': f"MPARTNAME eq '{odata_escape(mpart)}'",
                    '$select': 'PARTNAME,MPARTNAME,PARTDES,TOPP_SET',
                    '$top': 200,
                },
                timeout=30,
            )
            if r.status_code == 200:
                batch = r.json().get('value', [])
                all_parts.extend(batch)
        except requests.RequestException as e:
            logger.warning("kit_bom: query failed for MPARTNAME=%s: %s", mpart, e)
            continue

    logger.info("kit_bom: fetched %d parts from %d MPARTNAME queries",
                len(all_parts), len(tried_mparts))
    return all_parts


def build_bom_from_parts(parts: list[dict]) -> list[tuple[str, str]]:
    """מקבל רשימת מק"טים, מחזיר רשימת (parent_sku, child_sku) — BOM-זוגות.

    הלוגיקה:
    1. קבוצה לפי (MPARTNAME, variant) — שני אלה ביחד = משפחה ספציפית.
    2. בכל קבוצה: מק"ט עם size='00' הוא הסט; השאר הם רכיביו.
    3. ייצור zוגות parent→child.
    """
    # קיבוץ
    families: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
    # families[(mpart, variant)] = {size: partname}

    skipped_no_mpart = 0
    skipped_unparseable = 0
    for p in parts:
        partname = p.get('PARTNAME')
        mpartname = p.get('MPARTNAME')
        if not _is_luggage_sku(partname):
            continue
        if not mpartname:
            skipped_no_mpart += 1
            continue
        parsed = _parse_sku(partname, mpartname)
        if not parsed:
            skipped_unparseable += 1
            continue
        variant, size = parsed
        families[(mpartname, variant)][size] = partname

    logger.info("kit_bom: %d families, %d skipped (no mpart), %d skipped (unparseable)",
                len(families), skipped_no_mpart, skipped_unparseable)

    # ייצור זוגות
    bom_pairs: list[tuple[str, str]] = []
    kits_count = 0
    components_in_kits = 0
    families_with_kit = 0
    for (mpart, variant), sizes in families.items():
        if KIT_SIZE not in sizes:
            continue  # אין סט, רק רכיבים-עצמאיים
        kit_sku = sizes[KIT_SIZE]
        kits_count += 1
        families_with_kit += 1
        for size, child_sku in sizes.items():
            if size == KIT_SIZE:
                continue
            bom_pairs.append((kit_sku, child_sku))
            components_in_kits += 1

    logger.info("kit_bom: %d kits, %d components, %d BOM pairs",
                kits_count, components_in_kits, len(bom_pairs))
    return bom_pairs


def write_bom_to_db(bom_pairs: list[tuple[str, str]]) -> dict:
    """מחליף את ה-kit_bom הקיים בנתון החדש.

    הגישה: TRUNCATE + INSERT. ה-BOM קטן (מאות זוגות) ויציב, אין צורך
    ב-incremental merge.
    """
    if not bom_pairs:
        logger.warning("kit_bom: no BOM pairs to write")
        return {'wrote': 0}

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE kit_bom")
            execute_values(cur, """
                INSERT INTO kit_bom (parent_sku, child_sku)
                VALUES %s
            """, bom_pairs)
    logger.info("kit_bom: wrote %d pairs to DB", len(bom_pairs))
    return {'wrote': len(bom_pairs)}


def rebuild_bom(lg: logging.Logger | None = None) -> dict:
    """ה-entry point. מושך מ-Priority, בונה BOM, כותב ל-DB."""
    lg = lg or logger
    start = datetime.now()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO kit_bom_build_log (started_at)
                VALUES (NOW()) RETURNING build_id
            """)
            build_id = cur.fetchone()[0]

    try:
        parts = fetch_all_luggage_parts()
        bom_pairs = build_bom_from_parts(parts)
        result = write_bom_to_db(bom_pairs)

        kits = len({p for p, _ in bom_pairs})
        components = len({c for _, c in bom_pairs})
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE kit_bom_build_log
                    SET finished_at = NOW(),
                        kits_found = %s,
                        components_found = %s,
                        families_processed = %s
                    WHERE build_id = %s
                """, (kits, components, len(parts), build_id))
        result['build_id'] = build_id
        result['kits'] = kits
        result['components'] = components
        lg.info("kit_bom rebuild done: %s (took %s)",
                result, datetime.now() - start)
        return result
    except Exception as e:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE kit_bom_build_log
                    SET finished_at = NOW(),
                        notes = %s
                    WHERE build_id = %s
                """, (f"FAILED: {type(e).__name__}: {e}"[:1000], build_id))
        lg.exception("kit_bom rebuild failed")
        raise


if __name__ == '__main__':
    # Sprint C7.7: config check לפני שמתחילים.
    from config_check import assert_env_configured
    assert_env_configured('PRIORITY_AUTH_HEADER', 'PRIORITY_BASE_URL')

    import json
    res = rebuild_bom()
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
