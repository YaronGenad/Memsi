# -*- coding: utf-8 -*-
# backfill_history.py - סקריפט חד-פעמי
#
# מה הוא עושה:
# 1. בודק אילו חודשים 2023-01 עד 2026-03 חסרים מה-cache הגולמי
# 2. מושך חודשים חסרים מה-API (עם השהייה למניעת עומס)
# 3. מאגרג את כל הנתונים מה-cache ל-forecast_history:
#    branch x luggage_type x year_month - כמות תעודות סופיות
#
# הרץ אחת מהטרמינל:
#   cd priority_interface
#   venv/Scripts/python.exe backfill_history.py

import time
import calendar
from datetime import date, datetime
from dateutil.relativedelta import relativedelta

from cache_manager import CacheManager
from forecast_db import ForecastDB
from domain_repository import identify_luggage
from fetch_combined import fetch_documents, fetch_logfile

BACKFILL_START = "2023-01"
# BACKFILL_END = החודש הנוכחי (דינמי). אם רוצים להגביל ידנית — לשנות פה.
BACKFILL_END   = date.today().strftime("%Y-%m")
API_DELAY_SEC  = 2          # שניות המתנה בין קריאות API


def month_range(start_ym: str, end_ym: str) -> list[str]:
    current = datetime.strptime(start_ym + "-01", "%Y-%m-%d").date()
    end     = datetime.strptime(end_ym   + "-01", "%Y-%m-%d").date()
    months  = []
    while current <= end:
        months.append(current.strftime("%Y-%m"))
        current = (current + relativedelta(months=1)).replace(day=1)
    return months


def fetch_missing_months(cache: CacheManager, months: list[str]):
    """מושך מה-API חודשים שחסרים מה-cache"""
    cached_docs = cache.get_cached_months('documents')
    cached_logs = cache.get_cached_months('logfile')

    for ym in months:
        year, month = map(int, ym.split('-'))
        last_day    = calendar.monthrange(year, month)[1]
        start_date  = f"{year}-{month:02d}-01"
        end_date    = f"{year}-{month:02d}-{last_day}"

        if ym not in cached_docs:
            print(f"  [{ym}] מושך מסמכים מה-API...")
            docs = fetch_documents(start_date, end_date)
            cache.save_documents(docs, ym)
            cache.update_metadata('documents', ym, start_date, end_date, len(docs))
            print(f"  [{ym}] נשמרו {len(docs)} מסמכים")
            time.sleep(API_DELAY_SEC)

        if ym not in cached_logs:
            print(f"  [{ym}] מושך תנועות מה-API...")
            logs = fetch_logfile(start_date, end_date)
            cache.save_logfile(logs, ym)
            cache.update_metadata('logfile', ym, start_date, end_date, len(logs))
            print(f"  [{ym}] נשמרו {len(logs)} תנועות")
            time.sleep(API_DELAY_SEC)


import re as _re

# נרמול שמות — אנגלית/עברית/גרסאות שונות → שם קנוני
_BRANCH_ALIASES = {
    'HALEL KFAR SABA':  'הלל כפר סבא',
    'הילל':             'הלל כפר סבא',
    'SH. TIK HOLON':    'ש.תיק חולון',
    'שין תיק':          'ש.תיק חולון',
    'שיח תיק':          'ש.תיק חולון',
    'ש.תיק חולו':       'ש.תיק חולון',   # קיצור חלקי
}

# תבנית תאריך: DD/MM/YY, DD.MM.YY, DD/MM/YYYY
_DATE_PAT = _re.compile(r'\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b')

def _resolve_branch(doc: dict) -> str:
    """מחזיר שם סניף: BRANCHNAME אם קיים, אחרת DETAILS מנורמל."""
    branch = (doc or {}).get('BRANCHNAME') or ''
    if branch:
        return branch
    details = ((doc or {}).get('DETAILS') or '').strip()
    # הסר "משווק - " prefix
    if details.startswith('משווק - '):
        details = details[len('משווק - '):]
    # נרמל וריאנטים עם תאריך ("מיכאל ידני 30/01/25", "16/10/25", וכדומה)
    details_no_date = _DATE_PAT.sub('', details).strip()
    if details_no_date != details:          # תאריך הוסר
        details = details_no_date          # עשוי להיות ריק → 'לא ידוע' בסוף
    return _BRANCH_ALIASES.get(details, details) or 'לא ידוע'


def aggregate_month(cache: CacheManager, ym: str) -> list[dict]:
    """
    מחזיר רשימת {branch, luggage_type, year_month, quantity}
    עבור חודש אחד — JOIN תעודות סופיות × תנועות × identify_luggage
    """
    year, month = map(int, ym.split('-'))
    last_day    = calendar.monthrange(year, month)[1]
    start_date  = f"{year}-{month:02d}-01"
    end_date    = f"{year}-{month:02d}-{last_day}"

    documents = cache.get_documents(start_date, end_date)
    logfile   = cache.get_logfile(start_date, end_date)

    # רק תעודות סופיות
    final_docs = {d['DOCNO'] for d in documents if d.get('STATDES') == 'סופית'}

    # ספירה לפי סניף × זיהוי מזוודה
    counts: dict[tuple, int] = {}
    for log in logfile:
        docno  = log.get('LOGDOCNO')
        if docno not in final_docs:
            continue

        # מציאת הסניף מהמסמך המקביל
        doc    = next((d for d in documents if d['DOCNO'] == docno), None)
        branch = _resolve_branch(doc)

        luggage_type = identify_luggage(log.get('TOPARTDES', ''))
        if not luggage_type:
            continue

        key = (branch, luggage_type)
        counts[key] = counts.get(key, 0) + 1

    return [
        {'branch': branch, 'luggage_type': lt, 'year_month': ym, 'quantity': qty}
        for (branch, lt), qty in counts.items()
    ]


def aggregate_recent_months(lookback_months: int = 3) -> dict:
    """API ל-nightly_sync. מאגרג את N החודשים האחרונים ל-forecast_history.

    משתמש ב-cache הקיים (לא קורא ל-API). מחדש-אגרגציה של חודשים שקיימים
    כדי לתפוס שינויי-נתונים שהגיעו ב-incremental sync (תיקונים רטרואקטיביים
    של תעודות-לקוח-מבוטח, וכו').

    מדלג על החודש הנוכחי אם הוא לא הסתיים — חודש חלקי יעוות את ההיסטוריה
    כשמשתמשים בה לתחזית (החודש האחרון יראה כירידה דרסטית).
    """
    today = date.today()
    # אם היום הוא ה-1 בחודש, החודש הקודם בדיוק הסתיים — מתחילים ממנו.
    # אחרת, החודש הנוכחי חלקי — מתחילים מהקודם.
    start_offset = 0 if today.day == 1 else 1
    months_to_agg = []
    for i in range(start_offset, start_offset + lookback_months):
        d = today - relativedelta(months=i)
        months_to_agg.append(d.strftime("%Y-%m"))

    cache = CacheManager()
    fdb = ForecastDB()
    try:
        total_rows = 0
        for ym in sorted(months_to_agg):
            # מחק קיים לפני re-aggregate (לטפל בתיקונים רטרואקטיביים)
            fdb.delete_history_for_month(ym)
            records = aggregate_month(cache, ym)
            if records:
                fdb.bulk_upsert_history(records)
                total_rows += len(records)
        return {'months': len(months_to_agg), 'rows': total_rows,
                'oldest_month': months_to_agg[-1], 'newest_month': months_to_agg[0]}
    finally:
        cache.close()
        fdb.close()


def main():
    print("=" * 50)
    print("  backfill_history — מילוי היסטוריה לתחזיות")
    print("=" * 50)

    all_months  = month_range(BACKFILL_START, BACKFILL_END)
    cache       = CacheManager()
    fdb         = ForecastDB()

    # קודם בודקים מה יש לעשות, אחר-כך יודעים כמה צעדים יהיו בפועל.
    unknown_months = fdb.get_months_for_branch('לא ידוע')
    has_unknown = bool(unknown_months)
    total_steps = 4 if has_unknown else 3
    step = 1

    def tag() -> str:
        return f"[{step}/{total_steps}]"

    print(f"\n{tag()} בודק ומגדיר טבלאות...")
    fdb.setup_tables()
    print("  טבלאות מוכנות")
    step += 1

    print(f"\n{tag()} מושך חודשים חסרים מה-API ({BACKFILL_START} — {BACKFILL_END})...")
    fetch_missing_months(cache, all_months)
    print("  כל החודשים בcache")
    step += 1

    if has_unknown:
        print(f"\n{tag()} מוחק {len(unknown_months)} חודשי 'לא ידוע' ומאגרג מחדש...")
        fdb.delete_branch_history('לא ידוע')
        for i, ym in enumerate(sorted(unknown_months), 1):
            records = aggregate_month(cache, ym)
            fdb.bulk_upsert_history(records)
            print(f"  [{i}/{len(unknown_months)}] {ym} — {len(records)} שורות")
        step += 1

    covered = fdb.get_covered_months()
    to_aggregate = [m for m in all_months if m not in covered]

    if not to_aggregate:
        print(f"\n{tag()} forecast_history כבר מלא — אין מה לאגרג.")
    else:
        print(f"\n{tag()} מאגרג {len(to_aggregate)} חודשים ל-forecast_history...")
        for i, ym in enumerate(to_aggregate, 1):
            records = aggregate_month(cache, ym)
            fdb.bulk_upsert_history(records)
            print(f"  [{i}/{len(to_aggregate)}] {ym} — {len(records)} שורות")

    cache.close()
    fdb.close()
    print("\nהושלם בהצלחה!")


if __name__ == "__main__":
    main()
