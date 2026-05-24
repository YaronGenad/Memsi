# -*- coding: utf-8 -*-
"""
scenario_engine.py — ייצור תחזיות מותנות-תרחיש.

הלוגיקה: ה-business תלוי בשני משתנים שאינם מתואמים זה לזה:
1. **נפח-טיסות** (כמה אנשים נחתו) — flights
2. **conversion-rate** (איזה חלק מהנוחתים מביא מזוודה לתיקון) — regime

המשתמש בוחר:
- flight_scenario:  status_quo / escalation / gradual_recovery / open_skies
- conversion_regime: LOW / MEDIUM / HIGH

ה-engine מחזיר תחזית: לכל חודש בהורייזון, יחושב
  expected_demand = expected_flights × conversion_rate

ה-conversion-rate מבוסס על median היסטורי של ה-regime, שמחושב מ-flight_traffic
ו-forecast_history. רואים אילו חודשי-עבר היו ב-regime הזה ולוקחים את הציר.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from dateutil.relativedelta import relativedelta
import pandas as pd
import numpy as np
from db_config import get_conn
from logger import logger


# Conversion-rate medians לפי regime, מחושבים מ-ה-DB.
# Cache לשעה (משתנים לאט).
_conversion_cache: dict[str, float] = {}
_conversion_cache_at: datetime | None = None


# סניפי-הליבה הקבועים (אומתו מול המשתמש: ביאליק ת"א, פולג, קריות אונו,
# הדר ירושלים, אמות באר שבע, שרונים, אשקלון, שפיים).
BASELINE_BRANCH_CODES = ['05', '07', '23', '310', '325', '331', '332', '346']


# תרחישי-טיסות: כל אחד מייצר עקומה של arriving_passengers ל-N חודשים קדימה.
# הערכים יחסיים ל-"baseline" שמחושב מ-3 חודשים אחרונים.
FLIGHT_SCENARIOS = {
    'status_quo': {
        'name': 'סטטוס-קוו (המצב הנוכחי נמשך)',
        # משכפל את ה-baseline על-פני ההורייזון, עם תיקון עונתי קל
        'multipliers': lambda h: [1.0] * h,
    },
    'escalation': {
        'name': 'אסקלציה / החמרה',
        # ירידה חדה תוך 2 חודשים, אז קריסה
        'multipliers': lambda h: ([0.7, 0.3] + [0.2] * (h - 2))[:h],
    },
    'gradual_recovery': {
        'name': 'חזרה הדרגתית',
        # עליה איטית: +15%/חודש עד לתקרת 1.5×
        'multipliers': lambda h: [min(1.5, 1.0 + 0.15 * i) for i in range(h)],
    },
    'open_skies': {
        'name': 'פתיחת שמיים / שגרה מהירה',
        # קפיצה תוך 2 חודשים ל-2×, ואז שגרה
        'multipliers': lambda h: [min(2.0, 1.0 + 0.5 * i) for i in range(h)],
    },
}


# רגרסיות-conversion רגעיות (תיקונים/100K נחיתות). יוחלפו ב-medians-מ-DB
# בעת הקריאה הראשונה, אבל ערכי-בסיס משמשים כ-fallback אם אין נתונים.
DEFAULT_CONVERSION_RATES = {
    'LOW':    50.0,
    'MEDIUM': 80.0,
    'HIGH':   150.0,
}


def compute_conversion_rates(force_refresh: bool = False) -> dict[str, float]:
    """מחשב את ה-conversion-rate החציוני לכל regime מהנתונים ההיסטוריים.
    החישוב: לכל חודש שיש לו flight_traffic ו-forecast_events.conversion_regime,
    מחשב (demand_8_branches / arriving_passengers × 100000) ולוקח median per regime.
    """
    global _conversion_cache, _conversion_cache_at
    now = datetime.now()
    if (not force_refresh and _conversion_cache and _conversion_cache_at
            and (now - _conversion_cache_at).total_seconds() < 3600):
        return dict(_conversion_cache)

    # Sprint C7: parameterized query
    sql = """
        SELECT fe.conversion_regime,
               SUM(fh.quantity)::float / ft.arriving_passengers * 100000.0 AS rate
        FROM forecast_events fe
        JOIN flight_traffic ft USING (year_month)
        JOIN forecast_history fh USING (year_month)
        WHERE fh.branch = ANY(%s)
          AND fe.conversion_regime IS NOT NULL
          AND ft.arriving_passengers > 0
        GROUP BY fe.conversion_regime, fe.year_month, ft.arriving_passengers
    """
    with get_conn() as conn:
        df = pd.read_sql_query(sql, conn, params=(list(BASELINE_BRANCH_CODES),))

    rates: dict[str, float] = dict(DEFAULT_CONVERSION_RATES)
    if not df.empty:
        for regime, sub in df.groupby('conversion_regime'):
            if len(sub) >= 2:
                rates[regime] = float(sub['rate'].median())

    _conversion_cache = rates
    _conversion_cache_at = now
    logger.info("scenario_engine: conversion rates updated = %s", rates)
    return rates


def baseline_arriving_passengers() -> float:
    """ממוצע נחיתות ל-3 החודשים האחרונים שיש להם נתון."""
    with get_conn() as conn:
        df = pd.read_sql_query("""
            SELECT arriving_passengers FROM flight_traffic
            WHERE arriving_passengers IS NOT NULL
              AND notes = 'ok'
            ORDER BY year_month DESC
            LIMIT 3
        """, conn)
    if df.empty:
        return 700_000.0  # fallback סביר
    return float(df['arriving_passengers'].mean())


def _seasonal_multipliers() -> dict[int, float]:
    """מחזיר מקדם-עונתי לכל חודש 1..12.

    הלוגיקה: לכל חודש בשנה, מחשב יחס נחיתות מול ממוצע-שנתי לאותה שנה.
    משתמש בשנים שלמות בלבד (לא 2026 שעוד פתוחה).
    מסנן outlier חודשים: 2023-10..2024-03 (war shock), 2024-10..11 (Lebanon),
    2025-06 (Iran). אלה אירועים שלא יחזרו בצורה צפויה.

    אם לחודש יש <2 דוגמאות, fallback ל-1.0.
    """
    outlier_months = {
        '2023-10','2023-11','2023-12','2024-01','2024-02','2024-03',  # war shock
        '2024-10','2024-11',                                          # Lebanon
        '2025-06',                                                    # Iran
    }
    with get_conn() as conn:
        df = pd.read_sql_query("""
            SELECT year_month, arriving_passengers
            FROM flight_traffic
            WHERE arriving_passengers IS NOT NULL AND notes = 'ok'
            ORDER BY year_month
        """, conn)
    if df.empty:
        return {m: 1.0 for m in range(1, 13)}

    df = df[~df['year_month'].isin(outlier_months)].copy()
    df['year']  = df['year_month'].str[:4].astype(int)
    df['month'] = df['year_month'].str[5:7].astype(int)

    # שנה שלמה בלבד (12 חודשי-נתון)
    full_years = df.groupby('year').size()
    full_years = full_years[full_years >= 10].index.tolist()  # >=10 כי הוצאנו outliers
    df = df[df['year'].isin(full_years)]

    if df.empty:
        return {m: 1.0 for m in range(1, 13)}

    multipliers: dict[int, float] = {}
    for year, sub in df.groupby('year'):
        annual_mean = sub['arriving_passengers'].mean()
        for _, row in sub.iterrows():
            multipliers.setdefault(int(row['month']), []).append(
                row['arriving_passengers'] / annual_mean
            )

    out = {}
    for m in range(1, 13):
        if m in multipliers and len(multipliers[m]) >= 1:
            out[m] = float(sum(multipliers[m]) / len(multipliers[m]))
        else:
            out[m] = 1.0
    return out


@dataclass
class ScenarioForecast:
    """תוצאת תחזית-תרחיש לחודש בודד."""
    year_month: str
    expected_flights: int
    expected_demand: int        # תיקונים ל-8 סניפי-הליבה
    flight_scenario: str
    conversion_regime: str
    conversion_rate: float


def _planned_flights_map() -> dict[str, int]:
    """מחזיר {year_month: planned_flights} מ-flight_schedule. ריק אם אין.

    Sprint C5.4: ה-scenario engine השתמש קודם רק ב-baseline-3-months + תרחיש-תיאורטי.
    עכשיו מעדיף נתון-אמיתי-מנתב"ג כש-זמין (planned_flights מ-IAA scraper)."""
    with get_conn() as conn:
        df = pd.read_sql_query("""
            SELECT year_month, SUM(planned_flights) AS planned
            FROM flight_schedule
            WHERE airline_code = 'TOTAL'
            GROUP BY year_month
        """, conn)
    if df.empty:
        return {}
    return {r['year_month']: int(r['planned']) for _, r in df.iterrows()}


def _flights_per_pax_ratio() -> float:
    """ממוצע passengers/planned_flights בחודשים שיש להם שניהם.
    משמש להמרה מ-planned_flights (מספר נוסעים) למספר נחיתות."""
    with get_conn() as conn:
        df = pd.read_sql_query("""
            SELECT ft.year_month,
                   ft.arriving_passengers,
                   COALESCE(SUM(fs.planned_flights), 0) AS planned
            FROM flight_traffic ft
            LEFT JOIN flight_schedule fs ON fs.year_month = ft.year_month
                                         AND fs.airline_code = 'TOTAL'
            WHERE ft.arriving_passengers IS NOT NULL AND ft.notes = 'ok'
            GROUP BY ft.year_month, ft.arriving_passengers
            HAVING SUM(fs.planned_flights) > 0
        """, conn)
    if df.empty:
        return 200.0  # fallback סביר: ~200 נוסעים פר טיסה
    return float((df['arriving_passengers'] / df['planned']).mean())


def forecast_scenario(
    last_year_month: str,
    horizon: int,
    flight_scenario: str = 'status_quo',
    conversion_regime: str = 'LOW',
) -> list[ScenarioForecast]:
    """מייצר תחזית ל-horizon חודשים קדימה, החל מהחודש שאחרי last_year_month.

    last_year_month: 'YYYY-MM' של החודש האחרון שיש לו נתונים.
    horizon: כמה חודשים קדימה.
    flight_scenario: אחד מ-FLIGHT_SCENARIOS.
    conversion_regime: 'LOW' / 'MEDIUM' / 'HIGH'.

    Sprint C5.4: עבור חודש עתידי שיש לו planned_flights ב-DB (מ-IAA scraper),
    נשתמש בערך האמיתי ולא ב-baseline × multipliers. ה-multipliers משמשים רק
    כשאין נתון-עתידי (ולשם המקרה של 'escalation' שמייצג ירידה דרסטית בכוונה).
    """
    if flight_scenario not in FLIGHT_SCENARIOS:
        raise ValueError(f"unknown flight_scenario: {flight_scenario}")
    if conversion_regime not in ('LOW', 'MEDIUM', 'HIGH'):
        raise ValueError(f"unknown conversion_regime: {conversion_regime}")

    rates = compute_conversion_rates()
    rate = rates[conversion_regime]
    baseline = baseline_arriving_passengers()
    scen_multipliers = FLIGHT_SCENARIOS[flight_scenario]['multipliers'](horizon)
    seasonal = _seasonal_multipliers()

    # Sprint C5.4: נתוני flight_schedule (נתב"ג) עתידיים — מקור-האמת
    planned_map = _planned_flights_map()
    pax_per_flight = _flights_per_pax_ratio()

    cur = datetime.strptime(last_year_month + '-01', '%Y-%m-%d')
    out: list[ScenarioForecast] = []
    for i in range(horizon):
        cur = cur + relativedelta(months=1)
        ym = cur.strftime('%Y-%m')

        # תרחיש 'escalation' תמיד משתמש ב-multiplier (כי הוא מבטא הנחה
        # על אירוע-חדש). שאר התרחישים מעדיפים נתון-אמיתי-מנתב"ג.
        if flight_scenario != 'escalation' and ym in planned_map:
            # נתון אמיתי: ממירים מ-planned_flights ל-passengers
            flights = planned_map[ym] * pax_per_flight
            # למרות שיש נתון, תרחיש 'gradual_recovery'/'open_skies' עדיין
            # יכול לעלות מעליו (שגרת-שיא). 'status_quo' מציג את הנתון כפי שהוא.
            if flight_scenario in ('gradual_recovery', 'open_skies'):
                flights = max(flights, baseline * scen_multipliers[i] * seasonal.get(cur.month, 1.0))
        else:
            # fallback: baseline × scenario × seasonal
            season_mult = seasonal.get(cur.month, 1.0)
            flights = baseline * scen_multipliers[i] * season_mult

        demand = (flights * rate) / 100000.0
        out.append(ScenarioForecast(
            year_month=ym,
            expected_flights=int(round(flights)),
            expected_demand=int(round(demand)),
            flight_scenario=flight_scenario,
            conversion_regime=conversion_regime,
            conversion_rate=rate,
        ))
    return out


def forecast_all_scenarios(
    last_year_month: str,
    horizon: int,
    conversion_regime: str = 'LOW',
) -> dict[str, list[ScenarioForecast]]:
    """מייצר 4 תחזיות (אחת לכל flight_scenario) ב-regime נתון."""
    return {
        scen: forecast_scenario(last_year_month, horizon, scen, conversion_regime)
        for scen in FLIGHT_SCENARIOS
    }
