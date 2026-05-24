# -*- coding: utf-8 -*-
"""
local_inventory_calculator.py — חישוב מלאי-אמיתי לסניפי-הליבה.

נכון ל-v0.16.0 המקור-האמת הוא PARTBAL מ-Priority. רואים את rebuild_local_inventory_from_partbal.

(Sprint B2 ניסה לחשב את ה-running balance מ-logfile_full + ic_doc_classification.
זה נכשל באימות מול ספירה פיזית בסניף 800, ולכן ב-Sprint B2-Finish עברנו ל-PARTBAL.
החישוב הישן הוסר ב-Sprint C6 כקוד-מת — git history יש לו את ההיסטוריה.)
"""
from __future__ import annotations
import logging
from collections import defaultdict
from datetime import datetime

from psycopg2.extras import execute_values

from db_config import get_conn
from logger import logger


def _load_kit_bom() -> dict[str, list[str]]:
    """child_sku → [parent_sku, ...]"""
    out: dict[str, list[str]] = defaultdict(list)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT parent_sku, child_sku FROM kit_bom")
            for parent, child in cur.fetchall():
                out[child].append(parent)
    return dict(out)


# ============================================================
#  שיטה החדשה (אחרי B2 validation):
#  PARTBAL הוא מקור-האמת. הלוגיקה של logfile_full משמשת רק לתיקון חריגים.
# ============================================================
def rebuild_local_inventory_from_partbal(lg: logging.Logger | None = None) -> dict:
    """ה-entry point החדש. מבוסס PARTBAL הטרי כמקור-אמת.

    הליך:
    1. מחשב את רשימת הסניפים-הזכאים דינמית (אלה שיש להם פעילות-לקוח-מבוטח
       ב-12 חודשים אחרונים — אותה הגדרה כמו ב-min-stock tab).
    2. מושך PARTBAL טרי מ-Priority, מסנן לסניפים-זכאים בלבד.
    3. כותב הכל ל-local_inventory.
    4. לכל רשומה עם quantity <= -2 (חריג), מוסיף תרומת-סטים-מכילים מ-kit_bom.

    הסיבה לסף -2 ולא -1: PARTBAL לפעמים מציג -1 בגלל timing-issues
    זמני; -2 ומטה זה drift אמיתי שכדאי לנסות לפרק-סטים-עליו.
    """
    lg = lg or logger
    start = datetime.now()

    # שלב 0: מי הסניפים הזכאים? (דינמי — אם סניף יוצא מפעילות, הוא יורד מהרשימה)
    from min_stock_calculator import eligible_branches
    eligible = set(eligible_branches())
    lg.info("local_inv (partbal): %d eligible branches (dynamic)", len(eligible))
    if not eligible:
        lg.warning("local_inv (partbal): no eligible branches — aborting")
        return {'rows': 0, 'duration_seconds': 0}

    # שלב 1: מושך PARTBAL טרי
    lg.info("local_inv (partbal): fetching fresh PARTBAL...")
    from inventory_manager import fetch_partbal_inventory
    df = fetch_partbal_inventory()  # all warehouses; we filter below
    if df.empty:
        lg.warning("local_inv (partbal): PARTBAL returned 0 rows")
        return {'rows': 0, 'duration_seconds': 0}
    lg.info("local_inv (partbal): %d rows from PARTBAL (before filter)", len(df))

    # נורמליזציה: PARTBAL מחזיר בעמודות-עברית
    df = df[['מחסן', 'מקט', 'יתרה']].copy()
    df.columns = ['warehouse', 'sku', 'quantity']
    df['quantity'] = df['quantity'].astype(float)

    # סינון לסניפים-זכאים בלבד
    df = df[df['warehouse'].isin(eligible)].copy()
    lg.info("local_inv (partbal): %d rows after filtering to eligible branches", len(df))

    # ב-PARTBAL יכולות להיות כפילויות באותו (warehouse, sku) — סוכמים.
    df = df.groupby(['warehouse', 'sku'], as_index=False)['quantity'].sum()

    inventory: dict[tuple[str, str], float] = {
        (r['warehouse'], r['sku']): r['quantity'] for _, r in df.iterrows()
    }
    lg.info("local_inv (partbal): %d distinct (warehouse, sku) cells", len(inventory))

    # שלב 2: לחריגים (qty <= -2), נסה להוסיף תרומת-סטים-מכילים.
    # ה-balance של הסט-עצמו מחושב מ-logfile_full, ואז מתפזר לרכיביו.
    bom = _load_kit_bom()  # child_sku → [parent_sku, ...]
    if bom:
        anomalies = [(wh, sku) for (wh, sku), q in inventory.items() if q <= -2]
        lg.info("local_inv (partbal): %d anomalies (qty <= -2) — checking kit contributions",
                len(anomalies))

        # לכל אנומליה, חפש את הסטים-המכילים ובדוק את ה-PARTBAL שלהם באותו מחסן.
        # אם לסט עצמו יש יתרה חיובית — נוסיף אותה לרכיב.
        fixed = 0
        for (wh, child_sku) in anomalies:
            parents = bom.get(child_sku, [])
            kit_contribution = 0.0
            for parent_sku in parents:
                # ה-PARTBAL של הסט-עצמו במחסן הזה
                kit_qty = inventory.get((wh, parent_sku), 0.0)
                if kit_qty > 0:
                    kit_contribution += kit_qty
            if kit_contribution > 0:
                inventory[(wh, child_sku)] += kit_contribution
                fixed += 1

        lg.info("local_inv (partbal): adjusted %d anomalies via kit contribution", fixed)

    # שלב 3: מסירים סטים-עצמם (parent_skus) מ-local_inventory — הם
    # מיוצגים כרכיביהם.
    kit_skus = {p for parents in bom.values() for p in parents}
    final = {k: v for k, v in inventory.items() if k[1] not in kit_skus}
    lg.info("local_inv (partbal): %d final cells (after removing kit parents)", len(final))

    # שלב 4: כתיבה ל-DB
    rows = [(wh, sku, round(qty, 2)) for (wh, sku), qty in final.items()]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE local_inventory")
            if rows:
                execute_values(cur, """
                    INSERT INTO local_inventory (warehouse_code, sku, quantity)
                    VALUES %s
                """, rows, page_size=1000)

    duration = (datetime.now() - start).total_seconds()
    lg.info("local_inv (partbal) rebuild done: %d rows, %.1fs", len(rows), duration)
    return {'rows': len(rows), 'duration_seconds': round(duration, 1)}


if __name__ == '__main__':
    import json
    res = rebuild_local_inventory_from_partbal()
    print(json.dumps(res, ensure_ascii=False, indent=2))
