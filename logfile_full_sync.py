# -*- coding: utf-8 -*-
"""
logfile_full_sync.py — סנכרון logfile_full (תנועות-מלאי מלאות) מ-Priority.

זה שונה מ-cache_manager.save_logfile שמסונן ללקוחות-מבוטחים בלבד.
כאן אנחנו רוצים את הכל — כולל ספירות-מלאי (IC) ותנועות-בין-מחסנים — כדי
לחשב את ה-running balance נכון לחישוב local_inventory.

מצבים:
- initial_sync(): מהפעם הראשונה. מושך הכל פר-מק"ט-של-מזוודות. לוקח זמן.
- incremental_sync(days): מושך רק את N הימים האחרונים. רץ מהר ב-nightly.
"""
from __future__ import annotations
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from collections import defaultdict

import requests
from psycopg2.extras import execute_values

from db_config import get_conn
from logger import logger
from kit_bom_builder import _is_luggage_sku


REQUEST_TIMEOUT = 60
# Sprint C7.2: 4 workers במקביל. כשמקבילים, אין צורך ב-sleep גדול בין
# קריאות (ה-workers ממילא פורסים את הלחץ). אם Priority מחזיר 429, להעלות
# את SLEEP או להוריד את PRIORITY_API_WORKERS דרך env.
SLEEP_BETWEEN = 0.0
PRIORITY_API_WORKERS = int(os.environ.get('PRIORITY_API_WORKERS', '4'))


def _fetch_logfile_for_sku(session: requests.Session, base_url: str,
                            sku: str,
                            min_date: str | None = None) -> list[dict]:
    """מושך את כל תנועות LOGFILE עבור מק"ט. עם או בלי הגבלת-תאריך."""
    flt_parts = [f"PARTNAME eq '{sku}'"]
    if min_date:
        flt_parts.append(f"CURDATE gt {min_date}T00:00:00Z")
    flt = ' and '.join(flt_parts)

    all_rows: list[dict] = []
    skip = 0
    while True:
        params = {
            '$filter': flt,
            '$select': 'LOGDOCNO,CURDATE,PARTNAME,WARHSNAME,TOWARHSNAME,TQUANT',
            '$top': 1000,
            '$skip': skip,
            '$orderby': 'CURDATE',
        }
        r = session.get(f'{base_url}/LOGFILE', params=params, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            logger.warning("logfile_full: sku=%s status=%s", sku, r.status_code)
            return all_rows
        batch = r.json().get('value', [])
        if not batch:
            break
        all_rows.extend(batch)
        if len(batch) < 1000:
            break
        skip += 1000
        if skip > 50000:
            logger.warning("logfile_full: pagination exceeded 50K for %s", sku)
            break
    return all_rows


def _list_luggage_skus_from_db() -> list[str]:
    """רשימת כל מק"טי-מזוודות שיש לנו ידיעה עליהם (מ-kit_bom + logfile-cached)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT parent_sku FROM kit_bom UNION SELECT DISTINCT child_sku FROM kit_bom")
            from_bom = {r[0] for r in cur.fetchall()}
            cur.execute("SELECT DISTINCT partname FROM logfile WHERE partname IS NOT NULL")
            from_logfile = {r[0] for r in cur.fetchall()}
    skus = (from_bom | from_logfile)
    luggage = [s for s in skus if _is_luggage_sku(s)]
    return sorted(luggage)


# thread-local session: כל thread שמושך נתונים יוצר session משלו בפעם
# הראשונה, ושומר אותו בין קריאות. requests.Session לא thread-safe בין threads,
# אבל בתוך thread יחיד היא כן יעילה (keep-alive).
_thread_local = threading.local()


def _get_session() -> requests.Session:
    s = getattr(_thread_local, 'session', None)
    if s is None:
        s = requests.Session()
        s.headers['Authorization'] = os.environ['PRIORITY_AUTH_HEADER']
        _thread_local.session = s
    return s


def _fetch_and_write_one(sku: str, base_url: str,
                         min_date: str | None = None) -> int:
    """מושך + כותב מק"ט בודד. מחזיר מספר שורות שנכתבו. ל-Executor."""
    session = _get_session()
    rows = _fetch_logfile_for_sku(session, base_url, sku, min_date=min_date)
    if rows:
        _write_rows(rows)
        if SLEEP_BETWEEN > 0:
            time.sleep(SLEEP_BETWEEN)
        return len(rows)
    if SLEEP_BETWEEN > 0:
        time.sleep(SLEEP_BETWEEN)
    return 0


def initial_sync(lg: logging.Logger | None = None) -> dict:
    """סנכרון ראשוני: מושך את כל ההיסטוריה לכל מק"ט-של-מזוודות שאנחנו מכירים.
    Sprint C7.2: רץ ב-ThreadPoolExecutor במקביל."""
    lg = lg or logger
    base_url = os.environ['PRIORITY_BASE_URL']

    skus = _list_luggage_skus_from_db()
    lg.info("logfile_full initial_sync: %d luggage SKUs to fetch, %d workers",
            len(skus), PRIORITY_API_WORKERS)

    total_rows = 0
    errors = 0
    done = 0
    progress_lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=PRIORITY_API_WORKERS,
                            thread_name_prefix='logfile-full') as ex:
        futures = {ex.submit(_fetch_and_write_one, sku, base_url): sku
                   for sku in skus}
        for fut in as_completed(futures):
            sku = futures[fut]
            try:
                n = fut.result()
            except Exception as e:
                lg.warning("logfile_full initial_sync: %s failed: %s", sku, e)
                errors += 1
                n = 0
            with progress_lock:
                total_rows += n
                done += 1
                if done % 50 == 0:
                    lg.info("logfile_full initial_sync: %d/%d, rows so far: %d",
                            done, len(skus), total_rows)

    return {'skus_processed': len(skus), 'rows_written': total_rows, 'errors': errors}


def incremental_sync(days: int = 30, lg: logging.Logger | None = None) -> dict:
    """סנכרון אינקרמנטלי: רק N הימים האחרונים, לכל המק"טים הידועים.
    Sprint C7.2: רץ ב-ThreadPoolExecutor במקביל."""
    lg = lg or logger
    base_url = os.environ['PRIORITY_BASE_URL']

    skus = _list_luggage_skus_from_db()
    cutoff = (date.today() - timedelta(days=days)).strftime('%Y-%m-%d')
    lg.info("logfile_full incremental_sync: %d SKUs, cutoff=%s, %d workers",
            len(skus), cutoff, PRIORITY_API_WORKERS)

    total_rows = 0
    errors = 0
    done = 0
    progress_lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=PRIORITY_API_WORKERS,
                            thread_name_prefix='logfile-inc') as ex:
        futures = {ex.submit(_fetch_and_write_one, sku, base_url, cutoff): sku
                   for sku in skus}
        for fut in as_completed(futures):
            sku = futures[fut]
            try:
                n = fut.result()
            except Exception as e:
                lg.warning("logfile_full incremental: %s failed: %s", sku, e)
                errors += 1
                n = 0
            with progress_lock:
                total_rows += n
                done += 1
                if done % 100 == 0:
                    lg.info("logfile_full incremental_sync: %d/%d, rows so far: %d",
                            done, len(skus), total_rows)

    return {'skus_processed': len(skus), 'rows_attempted': total_rows,
            'errors': errors}


def _write_rows(rows: list[dict]) -> None:
    """כתיבת רשומות ל-logfile_full. ON CONFLICT DO NOTHING מונע כפילות."""
    if not rows:
        return
    payload = []
    for d in rows:
        payload.append((
            d.get('LOGDOCNO'),
            d.get('CURDATE'),
            d.get('PARTNAME'),
            d.get('WARHSNAME'),
            d.get('TOWARHSNAME'),
            float(d.get('TQUANT') or 0),
        ))
    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_values(cur, """
                INSERT INTO logfile_full
                    (logdocno, curdate, partname, warhsname, towarhsname, tquant)
                VALUES %s
                ON CONFLICT (
                    COALESCE(logdocno, ''),
                    partname,
                    COALESCE(warhsname, ''),
                    COALESCE(towarhsname, ''),
                    tquant,
                    curdate
                ) DO NOTHING
            """, payload, page_size=500)


# ============================================================
#  Classification of IC docs (reset vs add)
# ============================================================
def classify_ic_docs(lg: logging.Logger | None = None) -> dict:
    """לכל IC doc בלrigfile_full, סווג: 'reset' אם כל השורות שלו qty=0 ב-warehouse,
    אחרת 'add'. הסיווג הוא per-warehouse כי אותו doc יכול להיות reset במחסן
    אחד ו-add באחר (אם המק"טים שונים)."""
    lg = lg or logger
    with get_conn() as conn:
        with conn.cursor() as cur:
            # אספים: לכל (logdocno, towarhsname), האם כל השורות qty=0?
            cur.execute("""
                SELECT logdocno, towarhsname,
                       COUNT(*) AS n_rows,
                       SUM(CASE WHEN tquant = 0 THEN 1 ELSE 0 END) AS n_zeros
                FROM logfile_full
                WHERE logdocno LIKE 'IC%' AND towarhsname IS NOT NULL
                GROUP BY logdocno, towarhsname
            """)
            classifications = []
            for doc, wh, n_rows, n_zeros in cur.fetchall():
                doc_type = 'reset' if n_rows == n_zeros else 'add'
                classifications.append((doc, wh, doc_type))

    if classifications:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE ic_doc_classification")
                execute_values(cur, """
                    INSERT INTO ic_doc_classification (logdocno, warhsname, doc_type)
                    VALUES %s
                """, classifications)
    lg.info("classify_ic_docs: %d (doc, warehouse) pairs classified", len(classifications))
    n_reset = sum(1 for _, _, t in classifications if t == 'reset')
    n_add = len(classifications) - n_reset
    return {'pairs': len(classifications), 'reset': n_reset, 'add': n_add}


if __name__ == '__main__':
    import json
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else 'incremental'
    if mode == 'initial':
        res = initial_sync()
    elif mode == 'classify':
        res = classify_ic_docs()
    else:
        res = incremental_sync()
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
