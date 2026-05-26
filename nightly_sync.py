# -*- coding: utf-8 -*-
"""
nightly_sync.py — entry point לסקריפט הלילי שרץ ב-Task Scheduler.

מה הוא עושה:
1. מושך rolling 30 ימים אחרונים של DOCUMENTS_D + LOGFILE מ-Priority,
   ושומר ב-cache (מטפל ב-retroactive edits).
2. מרענן PARTBAL (תמונת מלאי נוכחית).
3. בודק את IAA monthly reports — אם יש חודש חדש, מוריד ומחלץ.
4. רושם כל ריצה ב-sync_runs.

לא קורא ל-forecast engine — תחזיות נשארות ידניות דרך ה-GUI.

שימוש:
    python nightly_sync.py              ריצה מלאה
    python nightly_sync.py --skip-iaa   בלי הרצת IAA monthly
    python nightly_sync.py --days 14    rolling window אחר

Logging: ~/.memsi/logs/nightly_YYYY-MM-DD.log.
"""
from __future__ import annotations
import argparse
import calendar
import logging
import os
import sys
import traceback
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from pathlib import Path

# ────────────────────────────────────────────────
#  Logging נפרד מ-app log
# ────────────────────────────────────────────────
def _setup_logging(verbose: bool = False) -> logging.Logger:
    log_dir = Path(os.path.expanduser('~/.memsi/logs'))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f'nightly_{date.today().isoformat()}.log'

    handler = logging.FileHandler(log_file, encoding='utf-8')
    handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    ))

    lg = logging.getLogger('nightly_sync')
    lg.setLevel(logging.DEBUG if verbose else logging.INFO)
    lg.addHandler(handler)

    # גם לקונסול
    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    lg.addHandler(sh)
    return lg


# ────────────────────────────────────────────────
#  ה-pipeline עצמו
# ────────────────────────────────────────────────
def _rolling_date_range(days: int) -> tuple[str, str]:
    end = date.today()
    start = end - relativedelta(days=days)
    return start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')


def _months_in_range(start_iso: str, end_iso: str) -> list[str]:
    """מחזיר רשימת year_months שנכללים בטווח (כולל)."""
    start = date.fromisoformat(start_iso).replace(day=1)
    end = date.fromisoformat(end_iso).replace(day=1)
    months = []
    cur = start
    while cur <= end:
        months.append(cur.strftime('%Y-%m'))
        cur = cur + relativedelta(months=1)
    return months


def sync_priority_rolling(days: int, lg: logging.Logger) -> dict:
    """מושך rolling N ימים. מטפל ב-retroactive edits של מסמכים ישנים."""
    from fetch_combined import fetch_documents, fetch_logfile
    from cache_manager import CacheManager

    start, end = _rolling_date_range(days)
    lg.info("sync_priority_rolling: %s to %s (%d days)", start, end, days)

    # למחוק מ-cache את החודשים שבטווח כדי שה-INSERT...ON CONFLICT לא ידחה
    # rows ישנים שהשתנו (retroactive edits).
    #
    # Sprint C7.5: clear+fetch+save מאוחדים פר-חודש. עד C7.4 היה two-pass —
    # קודם clear של כל החודשים, ואז fetch של כולם. אם ה-API נפל בפס השני
    # (אחרי שמחקנו את חודש N אבל לפני שמשכנו אותו), חודש N נשאר ריק עד
    # הריצה הבאה. עכשיו כל חודש נשמר מהcache הישן עד הרגע שלפני שאנחנו
    # מושכים אותו מחדש — אם המשיכה נופלת, ה-data הישן נשאר.
    cache = CacheManager()
    months = _months_in_range(start, end)

    counts = {'documents': 0, 'logfile': 0}
    for ym in months:
        year, month = map(int, ym.split('-'))
        last_day = calendar.monthrange(year, month)[1]
        m_start = f"{ym}-01"
        m_end = f"{ym}-{last_day:02d}"

        lg.info("pulling month %s", ym)
        docs = fetch_documents(m_start, m_end)
        logs = fetch_logfile(m_start, m_end)

        # רק אחרי שגם documents וגם logfile נמשכו בהצלחה — מנקים ושומרים.
        lg.debug("clearing cache for %s before save", ym)
        cache.clear_month_data(ym)

        cache.save_documents(docs, ym)
        cache.update_metadata('documents', ym, m_start, m_end, len(docs))
        counts['documents'] += len(docs)

        cache.save_logfile(logs, ym)
        cache.update_metadata('logfile', ym, m_start, m_end, len(logs))
        counts['logfile'] += len(logs)

    lg.info("sync_priority_rolling done: %s", counts)
    return counts


def sync_partbal(lg: logging.Logger) -> dict:
    """רענון תמונת מלאי. שומר ל-cache table באמצעות אותה לוגיקה."""
    from inventory_manager import fetch_partbal_inventory
    lg.info("sync_partbal: fetching")
    df = fetch_partbal_inventory()
    lg.info("sync_partbal done: %d rows", len(df))
    # הערה: PARTBAL הוא live-view; אין טבלת cache ייעודית. הקוד הקיים
    # מציג אותו ישירות. כאן רק בודקים שהקריאה עברה (smoke test ללילה).
    return {'partbal_rows': len(df)}


def sync_iaa(lg: logging.Logger) -> dict:
    """מחפש דו"ח IAA חדש. ראה iaa_sync.py."""
    from iaa_sync import sync_iaa_monthly
    lg.info("sync_iaa: starting")
    res = sync_iaa_monthly()
    lg.info("sync_iaa done: %s", res)
    return {
        'iaa_months_checked': res.get('months_checked', 0),
        'iaa_months_synced': res.get('months_synced', 0),
    }


def sync_flight_schedule(lg: logging.Logger) -> dict:
    """מושך תוכניות-טיסה עתידיות מ-IAA flight-board."""
    from flight_schedule_scraper import scrape_months
    lg.info("sync_flight_schedule: starting (12 months ahead)")
    res = scrape_months(months_ahead=12, lg=lg)
    lg.info("sync_flight_schedule done: %s", res)
    return {
        'schedule_records':       res.get('records', 0),
        'schedule_total_flights': res.get('total_flights', 0),
        'schedule_failures':      res.get('failures', 0),
    }


def _logfile_full_initial_done() -> bool:
    """בודק האם נמצא marker של initial-sync ב-sync_runs.records_pulled.
    זה מבטיח שגם אם logfile_full מתמלא חלקית בגלל ריצה שנפלה באמצע,
    לא נריץ initial_sync שוב בטעות.

    Precondition: טבלת sync_runs קיימת. מובטח כי start_run() נקרא קודם
    (sync_worker.py:99 או nightly_sync.run_full). אם הטבלה חסרה במכונה
    חדשה — start_run יקרוס לפני שמגיעים לכאן, וההודעה תפנה את המשתמש
    להריץ `python migrate.py` (README:142)."""
    from db_config import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 1
                FROM sync_runs
                WHERE (records_pulled ->> 'logfile_full_initial_done')::boolean = true
                LIMIT 1
            """)
            return cur.fetchone() is not None


def sync_logfile_full(lg: logging.Logger) -> dict:
    """Sprint C7.1 step 1/3 — סנכרון logfile_full + classify_ic_docs.

    איטי (5-12 דקות בריצה ראשונה, ~5-7 דקות בריצה רגילה).
    כולל את logfile_full incremental (1404 SKUs × API call) ואת classification
    של IC-docs. צריך לרוץ לפני rebuild_local_inventory_from_partbal כדי שה-PARTBAL
    יראה את ה-IC החדשים, אבל זה לא חובה לכל ריצת-רענון.
    """
    from logfile_full_sync import incremental_sync, initial_sync, classify_ic_docs

    out: dict = {}
    if _logfile_full_initial_done():
        lg.info("logfile_full: incremental sync (last 30 days)")
        r = incremental_sync(days=30, lg=lg)
        out['logfile_full_rows'] = r.get('rows_attempted', 0)
        out['logfile_full_skus']  = r.get('skus_processed', 0)
    else:
        lg.info("logfile_full: initial sync (full history) — first run")
        r = initial_sync(lg=lg)
        out['logfile_full_rows']   = r.get('rows_written', 0)
        out['logfile_full_skus']   = r.get('skus_processed', 0)
        out['logfile_full_errors'] = r.get('errors', 0)
        out['logfile_full_initial_done'] = True

    lg.info("classify_ic_docs: starting")
    r = classify_ic_docs(lg=lg)
    out['ic_docs_classified'] = r.get('pairs', 0)
    return out


def sync_local_inventory(lg: logging.Logger) -> dict:
    """Sprint C7.1 step 2/3 — build local_inventory מ-PARTBAL טרי.

    איטי (~5 דקות, רובו קריאה ל-Priority PARTBAL API).
    מנותק מ-logfile_full sync — ה-PARTBAL הוא ה-source-of-truth.

    Sundays-only: weekly rebuild של kit_bom (משתנה לאט; פעם בשבוע מספיק).
    """
    from datetime import date
    from kit_bom_builder import rebuild_bom
    from local_inventory_calculator import rebuild_local_inventory_from_partbal

    out: dict = {}

    if date.today().weekday() == 6:  # Sunday
        lg.info("sync_kit_bom: weekly rebuild")
        r = rebuild_bom(lg=lg)
        out['bom_kits'] = r.get('kits', 0)
        out['bom_pairs'] = r.get('wrote', 0)
    else:
        out['bom_kits'] = 'skipped'
        out['bom_pairs'] = 'skipped'

    lg.info("sync_local_inventory: starting (from PARTBAL)")
    r = rebuild_local_inventory_from_partbal(lg=lg)
    out['local_inv_rows'] = r.get('rows', 0)
    return out


def sync_forecast_history(lg: logging.Logger) -> dict:
    """Sprint C7.1 step 3/3 — aggregate forecast_history לחודשים האחרונים.

    מהיר (~5 שניות). לא קורא ל-Priority API; רק חישוב פנימי על cache.
    בלי שזה רץ, התחזיות "מקבעות" על החודש האחרון שאוגרג ידנית (bug v0.13.5).
    """
    from backfill_history import aggregate_recent_months
    lg.info("sync_forecast_history: aggregating recent months")
    r = aggregate_recent_months(lookback_months=3)
    return {
        'forecast_history_months': r.get('months', 0),
        'forecast_history_rows':   r.get('rows', 0),
        'forecast_history_newest': r.get('newest_month'),
    }


def sync_kit_bom_and_inventory(lg: logging.Logger) -> dict:
    """Backwards-compatible wrapper (Sprint C7.1): מריץ את 3 השלבים בסדר.
    משמש ע"י run_full ב-nightly. ה-GUI sync משתמש בשלבים בנפרד."""
    out: dict = {}
    out.update(sync_logfile_full(lg))
    out.update(sync_local_inventory(lg))
    out.update(sync_forecast_history(lg))
    return out


# ────────────────────────────────────────────────
#  Orchestration עם sync_runs tracking
# ────────────────────────────────────────────────
def run_full(days: int = 30, skip_iaa: bool = False,
             triggered_by: str = 'scheduler') -> int:
    """מריץ הכל. מחזיר exit-code: 0=ok, 1=partial, 2=failed."""
    lg = _setup_logging()
    lg.info("=" * 60)
    lg.info("nightly_sync START (triggered_by=%s)", triggered_by)

    from sync_runs import start_run, update_progress, finish_run
    run_id = start_run(triggered_by=triggered_by)

    pulled: dict = {}
    errors: list[str] = []

    def _step(name: str, fn, **kwargs):
        try:
            r = fn(**kwargs)
            pulled.update(r)
            update_progress(run_id, pulled)
        except Exception as e:
            tb = traceback.format_exc()
            lg.error("%s FAILED: %s\n%s", name, e, tb)
            errors.append(f"{name}: {type(e).__name__}: {e}")

    _step('priority_rolling', sync_priority_rolling, days=days, lg=lg)
    _step('partbal',          sync_partbal,          lg=lg)
    _step('kit_bom_inv',      sync_kit_bom_and_inventory, lg=lg)
    if not skip_iaa:
        _step('iaa',              sync_iaa,              lg=lg)
        _step('flight_schedule',  sync_flight_schedule,  lg=lg)

    if not errors:
        status, exit_code = 'ok', 0
    elif pulled:
        status, exit_code = 'partial', 1
    else:
        status, exit_code = 'failed', 2

    finish_run(
        run_id=run_id,
        status=status,
        records_pulled=pulled,
        errors_count=len(errors),
        last_error_text='\n'.join(errors) if errors else None,
    )

    lg.info("nightly_sync END: status=%s pulled=%s errors=%d",
            status, pulled, len(errors))
    return exit_code


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--days', type=int, default=30,
                    help='rolling window in days (default 30)')
    ap.add_argument('--skip-iaa', action='store_true',
                    help='skip IAA monthly fetch')
    ap.add_argument('--triggered-by', default='scheduler',
                    help='label written to sync_runs.triggered_by')
    args = ap.parse_args()
    sys.exit(run_full(
        days=args.days,
        skip_iaa=args.skip_iaa,
        triggered_by=args.triggered_by,
    ))


if __name__ == '__main__':
    main()
