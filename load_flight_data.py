# -*- coding: utf-8 -*-
"""
load_flight_data.py — טוען את iaa_flight_data.csv לטבלת flight_traffic,
ומסמן conversion_regime היסטורי ב-forecast_events לפי הניתוח של C1.5.

הסיווג ההיסטורי מבוסס על הניתוח של conversion_rate (תיקונים/100K נחיתות)
שבוצע על נתוני 8 סניפי-הליבה:

  pre-war (2023-Q1..Q3)         → LOW    (~20-50/100K)
  war shock (2023-11..2024-03)  → HIGH   (~120-180; backlog burn)
  war normalized (2024-04..09)  → HIGH   (~122-194; sustained backlog)
  late 24 ceasefire (2024-10..2025-05) → MEDIUM (~70-90)
  post-iran (2025-06..)         → LOW    (~50-60; new normal)

הסיווג ניתן לתיקון ידני דרך UI אחרי שיבוצע. הסקריפט הזה רץ פעם-אחת.
"""
import csv
from pathlib import Path
from psycopg2.extras import execute_values
from db_config import get_conn
from logger import logger


CSV_PATH = Path(__file__).parent / 'iaa_flight_data.csv'


def _to_int(s):
    s = (s or '').strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def load_flight_traffic():
    rows = []
    with open(CSV_PATH, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append((
                r['year_month'],
                _to_int(r.get('total_passengers')),
                _to_int(r.get('arriving_passengers')),
                _to_int(r.get('total_flights')),
                _to_int(r.get('arriving_flights')),
                r.get('source_url') or None,
                r.get('notes') or None,
            ))

    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_values(cur, """
                INSERT INTO flight_traffic
                    (year_month, total_passengers, arriving_passengers,
                     total_flights, arriving_flights, source_url, notes)
                VALUES %s
                ON CONFLICT (year_month) DO UPDATE SET
                    total_passengers    = EXCLUDED.total_passengers,
                    arriving_passengers = EXCLUDED.arriving_passengers,
                    total_flights       = EXCLUDED.total_flights,
                    arriving_flights    = EXCLUDED.arriving_flights,
                    source_url          = EXCLUDED.source_url,
                    notes               = EXCLUDED.notes,
                    updated_at          = NOW()
            """, rows)
    logger.info("flight_traffic: loaded %d rows", len(rows))
    return len(rows)


# טבלת regimes ההיסטוריים. מבוסס על מחקר C1.5.
# כל טופל: (start_ym, end_ym, regime).
_HISTORICAL_REGIMES = [
    # pre-war: conversion ~5-50, נמוך מאוד בתחילת התקופה (panel rollout)
    ('2022-01', '2023-09', 'LOW'),
    # war shock + war normalized 2024: backlog burning, conversion ~120-194
    ('2023-10', '2024-09', 'HIGH'),
    # late 24 ceasefire + early 2025: conversion ירד ל-50-90
    ('2024-10', '2025-05', 'MEDIUM'),
    # post-iran new normal: conversion חזר ל-50-67
    ('2025-06', '2026-03', 'LOW'),
]


def _months_between(start_ym: str, end_ym: str):
    """generator של year_months ביניהם, כולל."""
    from datetime import datetime
    from dateutil.relativedelta import relativedelta
    cur = datetime.strptime(start_ym + '-01', '%Y-%m-%d')
    end = datetime.strptime(end_ym + '-01', '%Y-%m-%d')
    while cur <= end:
        yield cur.strftime('%Y-%m')
        cur += relativedelta(months=1)


def mark_historical_regimes_v2():
    """גרסה פשוטה: UPSERT לכל חודש."""
    rows = []
    for start, end, regime in _HISTORICAL_REGIMES:
        for ym in _months_between(start, end):
            rows.append((ym, regime))

    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_values(cur, """
                INSERT INTO forecast_events (year_month, conversion_regime)
                VALUES %s
                ON CONFLICT (year_month) DO UPDATE SET
                    conversion_regime = EXCLUDED.conversion_regime
            """, rows)
    logger.info("conversion_regime: marked %d months", len(rows))
    return len(rows)


if __name__ == '__main__':
    # Sprint C7.7: config check לפני שמתחילים.
    from config_check import assert_env_configured
    assert_env_configured('PRIORITY_AUTH_HEADER', 'PRIORITY_BASE_URL')

    n_flights = load_flight_traffic()
    print(f"flight_traffic: {n_flights} months loaded")
    n_regimes = mark_historical_regimes_v2()
    print(f"conversion_regime: {n_regimes} months tagged")

    # אישור-עין
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT conversion_regime, COUNT(*)
                FROM forecast_events
                WHERE conversion_regime IS NOT NULL
                GROUP BY conversion_regime
                ORDER BY conversion_regime
            """)
            print("\nRegime distribution:")
            for r, n in cur.fetchall():
                print(f"  {r}: {n} months")
