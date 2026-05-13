# -*- coding: utf-8 -*-
"""
local_inventory_calculator.py — חישוב מלאי-אמיתי מ-logfile_full מקומי.

לוגיקת הספירות (IC docs):
- IC qty=0 לכל השורות במחסן = RESET-doc.
- IC עם qty != 0 = ADD-doc (delta).
- אם באותו יום יש RESET-doc + ADD-doc-חיובי → ה-RESET תקף (running=0, אז +qty).
- אם באותו יום יש RESET-doc + ADD-doc-שלילי → מתעלמים מה-RESET, ה-ADD שלילי
  מתפקד כדלתה רגילה. (זה התסריט בו פריוריטי משתמשת ב-IC עם qty שלילי
  לתיקון מלאי שכבר במינוס — האיפוס הוא טעות מבחינת מציאות פיזית.)
- ADD-doc יחיד בלי RESET-doc אותו יום → delta רגיל.
- תנועה רגילה: +qty אם המק"ט נכנס למחסן (TOWARHSNAME=wh, WARHSNAME!=wh),
  -qty אם המק"ט יוצא מהמחסן.

לסטים: אותו חישוב על parent_sku.
ה-local_inventory הסופי לרכיב = component_balance + Σ kit_balance של סטים-מכילים.
הסטים-עצמם לא מופיעים ב-local_inventory.
"""
from __future__ import annotations
import logging
from collections import defaultdict
from datetime import datetime

from psycopg2.extras import execute_values

from db_config import get_conn
from logger import logger


def _load_ic_classifications() -> set[tuple[str, str]]:
    """מחזיר set של (logdocno, warhsname) שהם RESET."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT logdocno, warhsname FROM ic_doc_classification
                WHERE doc_type = 'reset'
            """)
            return {(r[0], r[1]) for r in cur.fetchall()}


def _load_kit_bom() -> dict[str, list[str]]:
    """child_sku → [parent_sku, ...]"""
    out: dict[str, list[str]] = defaultdict(list)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT parent_sku, child_sku FROM kit_bom")
            for parent, child in cur.fetchall():
                out[child].append(parent)
    return dict(out)


def _compute_running_balance_for_sku(sku: str, warehouse: str,
                                      reset_docs: set[tuple[str, str]]) -> float:
    """ה-running balance של (sku, warehouse) לפי הלוגיקה הסופית.

    שלב 1 — מעבר ראשון: לזהות אילו ימים יש בהם RESET לכבד.
    RESET בימים שיש בהם גם ADD-doc-שלילי — *מתעלמים*.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT logdocno, curdate, warhsname, towarhsname, tquant
                FROM logfile_full
                WHERE partname = %s
                  AND (warhsname = %s OR towarhsname = %s)
                ORDER BY curdate, logdocno
            """, (sku, warehouse, warehouse))
            rows = cur.fetchall()

    return _running_balance_from_rows(rows, warehouse, reset_docs)


def _running_balance_from_rows(rows, warehouse: str,
                                reset_docs: set[tuple[str, str]]) -> float:
    """חישוב running balance מתוך רשימת שורות מסוננת (כבר לסונן ל-sku אחד)."""
    # שלב 1: מיפוי לפי יום + זיהוי RESET-days שצריכים להיות מבוטלים.
    day_rows: dict[str, list] = defaultdict(list)
    for r in rows:
        logdocno, curdate, wh, to, qty = r
        if wh != warehouse and to != warehouse:
            continue
        day_rows[str(curdate)[:10]].append(r)

    honor_reset_on: dict[str, bool] = {}
    for day, drows in day_rows.items():
        has_reset = False
        has_neg_add = False
        for logdocno, _cd, wh, to, qty in drows:
            if logdocno and logdocno.startswith('IC'):
                wh_for_ic = to if to else warehouse
                is_reset = (logdocno, wh_for_ic) in reset_docs
                if is_reset:
                    has_reset = True
                elif float(qty) < 0:
                    has_neg_add = True
        if has_reset:
            honor_reset_on[day] = not has_neg_add

    # שלב 2: walk-through.
    running = 0.0
    for logdocno, curdate, wh, to, qty in rows:
        if wh != warehouse and to != warehouse:
            continue
        qty = float(qty)
        cd = str(curdate)[:10]
        if logdocno and logdocno.startswith('IC'):
            wh_for_ic = to if to else warehouse
            is_reset = (logdocno, wh_for_ic) in reset_docs
            if is_reset:
                if honor_reset_on.get(cd, True):
                    running = 0.0
                # אחרת: מתעלמים — הRESET בוטל ע"י ADD-doc-שלילי באותו יום
            else:
                running += qty
        else:
            if to == warehouse and wh != warehouse:
                running += qty
            elif wh == warehouse and to != warehouse:
                running -= qty
    return running


def _list_warehouse_sku_pairs() -> list[tuple[str, str]]:
    """כל (warehouse, sku) שיש להם תנועה ב-logfile_full."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT warhsname AS wh, partname FROM logfile_full
                WHERE warhsname IS NOT NULL AND partname IS NOT NULL
                UNION
                SELECT DISTINCT towarhsname AS wh, partname FROM logfile_full
                WHERE towarhsname IS NOT NULL AND partname IS NOT NULL
            """)
            return [(r[0], r[1]) for r in cur.fetchall()]


def rebuild_local_inventory(lg: logging.Logger | None = None) -> dict:
    """ה-entry point. מחשב local_inventory מ-logfile_full + ic_doc_classification.

    יעיל: מטעין הכל לזיכרון פעם אחת, ואז ב-pass יחיד מחשב לכל המק"טים+מחסנים.
    """
    lg = lg or logger
    start = datetime.now()

    reset_docs = _load_ic_classifications()
    lg.info("local_inv: %d reset (doc,warehouse) pairs", len(reset_docs))

    bom = _load_kit_bom()
    kit_skus = {p for parents in bom.values() for p in parents}
    lg.info("local_inv: %d kit SKUs, %d component SKUs in BOM",
            len(kit_skus), len(bom))

    lg.info("local_inv: loading full logfile from DB...")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT logdocno, curdate, partname, warhsname, towarhsname, tquant
                FROM logfile_full
                ORDER BY partname, curdate, logdocno
            """)
            all_rows = cur.fetchall()
    lg.info("local_inv: loaded %d total rows", len(all_rows))

    # קיבוץ לפי partname; וזיהוי המחסנים שכל מק"ט מוזכר בהם.
    by_sku: dict[str, list[tuple]] = defaultdict(list)
    sku_to_warehouses: dict[str, set[str]] = defaultdict(set)
    for row in all_rows:
        logdocno, curdate, partname, wh, to, qty = row
        # ה-helper מצפה לרשימה של (logdocno, curdate, wh, to, qty) — בלי partname
        by_sku[partname].append((logdocno, curdate, wh, to, qty))
        if wh:
            sku_to_warehouses[partname].add(wh)
        if to:
            sku_to_warehouses[partname].add(to)

    balances: dict[tuple[str, str], float] = {}
    n_pairs = sum(len(whs) for whs in sku_to_warehouses.values())
    lg.info("local_inv: computing %d (sku, warehouse) balances...", n_pairs)

    for sku, warehouses in sku_to_warehouses.items():
        rows = by_sku[sku]
        for warehouse in warehouses:
            balances[(warehouse, sku)] = _running_balance_from_rows(
                rows, warehouse, reset_docs
            )

    lg.info("local_inv: computed %d balances", len(balances))

    # שלב 4: רכיב-של-סט מקבל גם את ה-running של כל סט-מכיל שלו.
    # קודם מסירים את הסטים-עצמם, אחר-כך מוסיפים את התרומה שלהם לרכיביהם.
    final: dict[tuple[str, str], float] = {}
    for (wh, sku), qty in balances.items():
        if sku in kit_skus:
            continue  # סטים לא ב-local_inventory
        final[(wh, sku)] = qty

    for child, parents in bom.items():
        for parent in parents:
            for (wh, sku), qty in balances.items():
                if sku == parent and qty != 0:
                    key = (wh, child)
                    final[key] = final.get(key, 0.0) + qty

    lg.info("local_inv: %d final cells (after kit unpacking)", len(final))

    # שלב 5: כתיבה ל-DB
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
    lg.info("local_inv rebuild done: %d rows, %.1fs", len(rows), duration)
    return {'rows': len(rows), 'duration_seconds': round(duration, 1)}


if __name__ == '__main__':
    import json
    res = rebuild_local_inventory()
    print(json.dumps(res, ensure_ascii=False, indent=2))
