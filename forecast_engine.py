# -*- coding: utf-8 -*-
"""
forecast_engine.py

ממשק אחיד לכל מודלי התחזית.
כל מודל מקבל:
    series      — pd.Series עם index מסוג YYYY-MM (str) וערכים int
    horizon     — מספר חודשים לחזות קדימה
    events_df   — DataFrame של forecast_events (לצירוף פיצ'רים)
    context     — dict עם מצב נוכחי (is_war, is_military_op, ...)

ומחזיר pd.DataFrame עמודות: year_month, forecast, lower, upper
"""

import warnings
import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta
from datetime import datetime
from logger import logger

warnings.filterwarnings('ignore')


# ────────────────────────────────────────────────
#  MODEL_VERSION — נכלל ב-cache key.
#  להגדיל בכל שינוי בלוגיקת מודל, ב-features, או באלגוריתם residual std.
#  שינוי הערך הזה גורם לכל ה-cache הקיים להיחשב לא-תקף, וה-app יחשב מחדש.
#  היסטוריה:
#    "1" - גרסה התחלתית.
#    "2" - C1: הסרת is_routine מ-Prophet, פישוט features ב-XGBoost,
#          rolling residual std (12 חודשים), טעינת חגים דינמית מ-pyluach.
#    "3" - C2.5: הוספת flight_volume_lagged ו-conversion_regime כ-features
#          ל-XGBoost ו-Prophet. flight_volume normalized ל-baseline, regime
#          מקודד כ-numeric (LOW=0, MEDIUM=1, HIGH=2).
# ────────────────────────────────────────────────
MODEL_VERSION = "5"


# ────────────────────────────────────────────────
#  Cache להעשרת features מ-DB (flight_traffic + conversion_regime)
# ────────────────────────────────────────────────
_flight_cache: dict[str, float] = {}             # היסטוריה: arriving_passengers
_schedule_cache: dict[str, int] = {}              # עתיד: planned_flights (TOTAL)
_regime_cache: dict[str, str] = {}
_features_cache_loaded: bool = False


# Sprint C5.3: ROUTINE (pre-war שגרה רגילה) ו-LOW (post-trauma) שניהם
# conversion-rate נמוך, אבל ROUTINE יש לו flight_capacity יותר גבוה.
# ערכי הקידוד מספקים סדר טבעי: ROUTINE (-0.5) ← LOW (0) ← MEDIUM (1) ← HIGH (2).
_REGIME_TO_NUM = {'ROUTINE': -0.5, 'LOW': 0.0, 'MEDIUM': 1.0, 'HIGH': 2.0}


def _load_features_cache() -> None:
    """טוען פעם אחת את flight_traffic + flight_schedule + conversion_regime
    מ-DB. cache בזיכרון כי הנתונים משתנים רק פעם בחודש (אחרי nightly_sync).
    """
    global _flight_cache, _schedule_cache, _regime_cache, _features_cache_loaded
    if _features_cache_loaded:
        return
    try:
        from db_config import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT year_month, arriving_passengers
                    FROM flight_traffic
                    WHERE arriving_passengers IS NOT NULL
                """)
                _flight_cache = {ym: float(v) for ym, v in cur.fetchall()}
                cur.execute("""
                    SELECT year_month, planned_flights
                    FROM flight_schedule
                    WHERE airline_code = 'TOTAL'
                """)
                _schedule_cache = {ym: int(n) for ym, n in cur.fetchall()}
                cur.execute("""
                    SELECT year_month, conversion_regime
                    FROM forecast_events
                    WHERE conversion_regime IS NOT NULL
                """)
                _regime_cache = {ym: r for ym, r in cur.fetchall()}
        _features_cache_loaded = True
        logger.info("features cache loaded: flights=%d, schedule=%d, regimes=%d",
                    len(_flight_cache), len(_schedule_cache), len(_regime_cache))
    except Exception:
        logger.exception("failed to load features cache; falling back to defaults")
        _flight_cache = {}
        _schedule_cache = {}
        _regime_cache = {}
        _features_cache_loaded = True


def invalidate_features_cache() -> None:
    """לקריאה אחרי IAA sync או שינוי ידני ב-regimes."""
    global _features_cache_loaded
    _features_cache_loaded = False


def _flight_baseline() -> float:
    """ממוצע 3 חודשים אחרונים של arriving_passengers, ל-normalization."""
    _load_features_cache()
    if not _flight_cache:
        return 700_000.0
    last_3 = sorted(_flight_cache.keys())[-3:]
    return sum(_flight_cache[k] for k in last_3) / len(last_3)


def _flight_volume_for(ym: str, fallback: float | None = None) -> float:
    """מחזיר arriving_passengers ל-year_month, מנורמלל ל-baseline.

    הזרת-נתונים (Sprint C5.3):
    1. אם יש arriving_passengers ב-flight_traffic — משתמש בו (היסטוריה).
    2. אחרת אם יש planned_flights ב-flight_schedule — מעריך passengers
       על-בסיס יחס היסטורי של passengers/planned-flights.
    3. אחרת — לוקח ממוצע של אותו חודש-בלוח-השנה בשנים קודמות (seasonality).
    4. אחרון — fallback ל-1.0 (baseline).
    """
    _load_features_cache()
    baseline = _flight_baseline()
    if baseline <= 0:
        baseline = 700_000.0

    # שלב 1: היסטוריה אמיתית
    if ym in _flight_cache:
        return _flight_cache[ym] / baseline

    # שלב 2: planned_flights
    if ym in _schedule_cache and _schedule_cache[ym] > 0:
        # יחס היסטורי: passengers/planned. נחשב על חודשים שיש להם את שניהם.
        ratios = []
        for k, v in _flight_cache.items():
            if k in _schedule_cache and _schedule_cache[k] > 0:
                ratios.append(v / _schedule_cache[k])
        if ratios:
            avg_ratio = sum(ratios) / len(ratios)
            estimated = _schedule_cache[ym] * avg_ratio
            return estimated / baseline

    # שלב 3: ממוצע חודש-בלוח-שנה בשנים קודמות
    month = ym[5:7]
    same_month_values = [v for k, v in _flight_cache.items() if k[5:7] == month]
    if same_month_values:
        avg = sum(same_month_values) / len(same_month_values)
        return avg / baseline

    if fallback is not None:
        return fallback
    return 1.0


def _regime_for(ym: str, default: str = 'LOW') -> float:
    """מחזיר conversion_regime ל-year_month ככערך מספרי. ברירת-מחדל = LOW (0)."""
    _load_features_cache()
    regime = _regime_cache.get(ym, default)
    return _REGIME_TO_NUM.get(regime, 0.0)


def _prev_month(ym: str) -> str:
    """'2026-04' → '2026-03'. עוטף date arithmetic ב-helper קצר."""
    dt = datetime.strptime(ym + '-01', '%Y-%m-%d') - relativedelta(months=1)
    return dt.strftime('%Y-%m')


# ────────────────────────────────────────────────
#  עזרים משותפים
# ────────────────────────────────────────────────

def _extend_events(events_df: pd.DataFrame, last_ym: str,
                   horizon: int, context: dict) -> pd.DataFrame:
    """מוסיף שורות עתידיות ל-events_df לפי context הנוכחי.

    אירועים היסטוריים שכבר מופיעים ב-events_df שומרים על ערכיהם המקוריים — שורות
    עתידיות מסונפות רק לחודשים שאינם קיימים. זה קריטי ל-backtest: כש-train_end
    נמצא בעבר, חלון ה-horizon של ה-backtest נופל על חודשים שיש להם נתוני-עבר
    ב-events_df. בלי הסינון, ה-context-default היה דורס את העובדות ההיסטוריות
    ופוגם ב-metrics.

    jewish_holiday מחושב דינמית מ-pyluach לחודשים עתידיים; ה-context יכול
    לעקוף אם המשתמש סיפק ערך מפורש.
    """
    from holiday_calendar import get_jewish_holiday_months

    existing_yms = (set(events_df['year_month'].astype(str))
                    if 'year_month' in events_df.columns else set())
    rows = []
    cur = datetime.strptime(last_ym + "-01", "%Y-%m-%d")
    # חישוב חד-פעמי של חודשי-חג בטווח הרלוונטי, חוסך קריאות חוזרות.
    end = cur + relativedelta(months=horizon)
    holiday_months = get_jewish_holiday_months(cur.year, end.year)
    for _ in range(horizon):
        cur = (cur + relativedelta(months=1))
        ym  = cur.strftime("%Y-%m")
        if ym in existing_yms:
            continue  # לא לדרוס נתונים היסטוריים ב-events_df
        _w = int(context.get('is_war', 0))
        _o = int(context.get('is_military_op', 0))
        _c = int(context.get('is_ceasefire', 0))
        # ה-context יכול לעקוף, אבל ברירת המחדל היא חישוב דינמי מהלוח-העברי.
        _jh = int(context['jewish_holiday']) if 'jewish_holiday' in context \
              else (1 if ym in holiday_months else 0)
        rows.append({
            'year_month':      ym,
            'is_war':          _w,
            'is_military_op':  _o,
            'is_ceasefire':    _c,
            'jewish_holiday':  _jh,
            'season':          int(context.get('season', _infer_season(ym))),
            'is_summer_peak':  int(context.get('is_summer_peak',
                                               1 if cur.month in (7, 8) else 0)),
            'travel_impact':   context.get('travel_impact', 'normal'),
            'is_routine':      int(not (_w or _o or _c)),
            'is_black_friday': int(cur.month == 11),
        })
    if not rows:
        return events_df
    future = pd.DataFrame(rows)
    return pd.concat([events_df, future], ignore_index=True)


def _infer_season(ym: str) -> int:
    month = int(ym.split('-')[1])
    if month in (12, 1, 2):  return 1   # חורף
    if month in (3, 4, 5):   return 2   # אביב
    if month in (6, 7, 8):   return 3   # קיץ
    return 4                             # סתיו


def _travel_impact_num(val) -> float:
    mapping = {
        'collapse': -2.0, 'very_low': -1.5, 'low': -0.5,
        'recovering': 0.3, 'normal': 1.0, 'high': 1.5,
    }
    return mapping.get(str(val), 1.0)


def _future_months(last_ym: str, horizon: int) -> list[str]:
    cur = datetime.strptime(last_ym + "-01", "%Y-%m-%d")
    months = []
    for _ in range(horizon):
        cur = (cur + relativedelta(months=1))
        months.append(cur.strftime("%Y-%m"))
    return months


def _result_df(months: list[str], forecast: np.ndarray,
               lower: np.ndarray | None = None,
               upper: np.ndarray | None = None) -> pd.DataFrame:
    n = len(months)
    f = np.maximum(forecast[:n], 0).round().astype(int)
    l = np.maximum(lower[:n],   0).round().astype(int) if lower  is not None else f
    u = np.maximum(upper[:n],   0).round().astype(int) if upper  is not None else f
    return pd.DataFrame({'year_month': months, 'forecast': f,
                         'lower': l, 'upper': u})


# ────────────────────────────────────────────────
#  מודל 1 — Naive Prev ("חודש קודם")
#
#  Sprint C4 (2026-05): ARIMA הוצא, החליף ב-naive_prev.
#  Sandbox-validation: ARIMA SARIMAX היה MAE=747 (MAPE=119%), בעוד
#  naive_prev MAE=242 (MAPE=33%). ARIMA היה למעשה פעיל-מזיק —
#  גורם לשגיאות גדולות בגלל regime-shifts תכופים שהוא לא מבין.
# ────────────────────────────────────────────────
ARIMA_DESCRIPTION = (
    "חודש קודם — תחזית פשוטה שמחזירה את ערך החודש האחרון, עם רעידות-אזעקה"
    " של ±std-rolling-12-month. המודל הזה הוכיח את עצמו כמדויק ביותר על נתונים"
    " של עד 40 חודשים עם regime-shifts (MAE/MAPE טובים פי 3 מ-ARIMA)."
)

def forecast_arima(series: pd.Series, horizon: int,
                   events_df: pd.DataFrame, context: dict) -> pd.DataFrame:
    """Naive-prev: תחזית = ערך החודש האחרון.

    שם הפונקציה נשמר לתאימות אחורה (UI מצביע עליו).
    """
    y = series.values.astype(float)
    months = _future_months(series.index[-1], horizon)

    if len(y) == 0:
        return _result_df(months, np.zeros(horizon))

    last_val = float(y[-1])
    # רעידת-טבע: 1 std של 12 חודשים אחרונים (אם יש). ±1σ ≈ 68% interval,
    # אבל אצלנו ה-UI מציג .lower/.upper כ-"טווח", ככל הנראה.
    recent = y[-12:] if len(y) >= 12 else y
    sigma = float(np.std(recent)) if len(recent) > 1 else last_val * 0.2

    pred = np.full(horizon, last_val)
    lower = pred - sigma
    upper = pred + sigma
    return _result_df(months, pred, lower, upper)


# ────────────────────────────────────────────────
#  מודל 2 — Regime-Aware Naive ("חודש קודם, מותאם ל-regime")
#
#  Sprint C4 (2026-05): Prophet הוצא, החליף ב-regime_naive.
#  Prophet היה מתבלבל מ-correlation מעוות של is_war/+0.43 ו-is_ceasefire/-0.56
#  עם הביקוש (confounded by Summer-peak 2024), והפיק תחזיות "מלחמה=יותר".
#  regime_naive מתחיל מ-naive_prev, אבל מתאים את התחזית לפי יחס הממוצעים
#  בין ה-regime הצפוי ל-regime הנוכחי, אם הם שונים.
# ────────────────────────────────────────────────
PROPHET_DESCRIPTION = (
    "מותאם-regime — חודש קודם, אבל אם ה-regime (LOW/MEDIUM/HIGH) צפוי"
    " להשתנות, התחזית מתאימה את עצמה לפי היחס בין הממוצעים ההיסטוריים."
    " Sandbox: MAE=260 (טוב יותר מ-Prophet שהיה ~330 ופחות-הגיוני)."
)

def forecast_prophet(series: pd.Series, horizon: int,
                     events_df: pd.DataFrame, context: dict) -> pd.DataFrame:
    """Regime-aware naive: חודש קודם × ratio של ממוצעי-regime.

    שם הפונקציה נשמר לתאימות אחורה.
    """
    y = series.values.astype(float)
    months = _future_months(series.index[-1], horizon)

    if len(y) == 0:
        return _result_df(months, np.zeros(horizon))

    last_val = float(y[-1])

    # ה-regime הצפוי בא מ-context ('conversion_regime' = LOW/MEDIUM/HIGH).
    # אם אין שינוי או אין מספיק נתונים — מתנהג כ-naive_prev.
    ctx_regime = context.get('conversion_regime', 'LOW')

    # נחשב את ה-regime ההיסטורי לכל חודש בסדרה
    series_regimes = []
    for ym in series.index:
        r = _regime_for(ym)  # מחזיר מספר (0/1/2)
        series_regimes.append(r)
    series_regimes = np.array(series_regimes)

    target_regime_num = _REGIME_TO_NUM.get(ctx_regime, 0.0)
    last_regime_num = series_regimes[-1] if len(series_regimes) else 0.0

    pred_value = last_val
    if abs(target_regime_num - last_regime_num) >= 0.5 and len(y) >= 6:
        mask_now = np.isclose(series_regimes, last_regime_num)
        mask_target = np.isclose(series_regimes, target_regime_num)
        if mask_now.sum() >= 3 and mask_target.sum() >= 3:
            mean_now = float(y[mask_now].mean())
            mean_target = float(y[mask_target].mean())
            if mean_now > 0:
                ratio = mean_target / mean_now
                pred_value = last_val * ratio

    recent = y[-12:] if len(y) >= 12 else y
    sigma = float(np.std(recent)) if len(recent) > 1 else pred_value * 0.2

    pred = np.full(horizon, pred_value)
    return _result_df(months, pred, pred - sigma, pred + sigma)


# ────────────────────────────────────────────────
#  מודל 3 — Flight-Rate ("טיסות × ממוצע rate היסטורי")
#
#  Sprint C4 (2026-05): XGBoost הוצא, החליף ב-flight_rate.
#  XGBoost על 38 נתונים-של-הדרכה היה תפס overfit-משמעותי. MAE שלו בריצה
#  פנימית היה ~290, אבל באמת לא הוסיף ערך מעל naive. flight_rate הוא
#  המודל ה-causal: rate = qty / flights בחודשים האחרונים, ומכפיל ב-flights
#  הצפויים. MAE=280 ומגיב ב-causality נכונה (יותר טיסות → יותר ביקוש).
# ────────────────────────────────────────────────
XGBOOST_DESCRIPTION = (
    "תחזית-טיסות — מבוסס על נוסחה סיבתית: rate = ביקוש / טיסות בחודשים האחרונים,"
    " ומחשב תחזית = rate × טיסות צפויות. הגיוני: יותר טיסות → יותר ביקוש."
    " Sandbox: MAE=280."
)

def _build_features(series: pd.Series, events_df: pd.DataFrame) -> pd.DataFrame:
    ev = events_df.drop_duplicates(subset='year_month', keep='last').set_index('year_month')
    rows = []
    yms  = list(series.index)
    for i, ym in enumerate(yms):
        y, m    = int(ym[:4]), int(ym[5:7])
        ev_row  = ev.loc[ym] if ym in ev.index else pd.Series(dtype=float)
        # הערה (Sprint C1): month/quarter/is_summer_peak/is_routine הוסרו.
        # sin_month/cos_month מקודדים עונתיות חודשית באופן רציף.
        # is_summer_peak (Jul/Aug) חופף עם sin/cos. is_routine היה
        # collinear עם is_war/military_op/ceasefire.
        # Sprint C2.5: flight_volume_lag1 = נחיתות חודש קודם, מנורמללות לבייסליין.
        # הטענה הסיבתית: ביקוש לתיקונים בחודש N מונע מנחיתות בחודש N-1 (lag
        # של 2-4 שבועות בין נחיתה לתיקון). conversion_regime מקודד את הרגישות.
        prev_ym = yms[i-1] if i > 0 else ym
        flight_lag1 = _flight_volume_for(prev_ym)
        flight_curr = _flight_volume_for(ym)
        regime_num  = _regime_for(ym)

        row = {
            'sin_month':      np.sin(2 * np.pi * m / 12),
            'cos_month':      np.cos(2 * np.pi * m / 12),
            'is_war':          float(ev_row.get('is_war', 0)),
            'is_military_op':  float(ev_row.get('is_military_op', 0)),
            'is_ceasefire':    float(ev_row.get('is_ceasefire', 0)),
            'jewish_holiday':  float(ev_row.get('jewish_holiday', 0)),
            'travel_num':      _travel_impact_num(ev_row.get('travel_impact','normal')),
            'is_black_friday': float(1 if m == 11 else 0),
            'lag1':           float(series.iloc[i-1]) if i > 0 else 0,
            'lag2':           float(series.iloc[i-2]) if i > 1 else 0,
            'lag3':           float(series.iloc[i-3]) if i > 2 else 0,
            'lag12':          float(series.iloc[i-12]) if i >= 12 else float(np.mean(series.values)),
            'roll3_mean':     float(np.mean(series.values[max(0,i-3):i])) if i > 0 else 0,
            'roll6_mean':     float(np.mean(series.values[max(0,i-6):i])) if i > 0 else 0,
            'flight_lag1':    flight_lag1,
            'flight_curr':    flight_curr,
            'regime':         regime_num,
            'target':         float(series.iloc[i]),
        }
        rows.append(row)
    return pd.DataFrame(rows)


def forecast_xgboost(series: pd.Series, horizon: int,
                     events_df: pd.DataFrame, context: dict) -> pd.DataFrame:
    """Flight-rate: rate = ממוצע (qty/flights) ב-6 חודשים אחרונים × flights צפויים.

    שם הפונקציה נשמר לתאימות אחורה (UI מצביע עליו).
    """
    y = series.values.astype(float)
    months = _future_months(series.index[-1], horizon)

    if len(y) == 0:
        return _result_df(months, np.zeros(horizon))

    # rate = qty/flight בחודשים האחרונים. fallback ל-naive_prev אם אין flights.
    rates = []
    for i in range(max(0, len(series) - 6), len(series)):
        ym = series.index[i]
        flights = _flight_volume_for(ym)
        if flights and flights > 0.01:  # _flight_volume_for מחזיר normalized או 0
            # ה-flight מ-_flight_volume_for הוא normalized; ננסה לקבל את הערך הגולמי
            rates.append(y[i] / max(flights, 0.1))
    if not rates:
        # אין נתוני טיסות → fallback ל-naive_prev
        last_val = float(y[-1])
        recent = y[-12:] if len(y) >= 12 else y
        sigma = float(np.std(recent)) if len(recent) > 1 else last_val * 0.2
        pred = np.full(horizon, last_val)
        return _result_df(months, pred, pred - sigma, pred + sigma)

    avg_rate = float(np.mean(rates))

    # ה-flights הצפויים: נשתמש ב-flight_curr לכל חודש עתידי. אם אין —
    # נשתמש בממוצע 6 חודשים אחרונים.
    last_flight = _flight_volume_for(series.index[-1]) or 1.0
    preds = []
    for ym in months:
        f = _flight_volume_for(ym) or last_flight
        preds.append(avg_rate * f)

    pred_arr = np.array(preds)
    recent = y[-12:] if len(y) >= 12 else y
    sigma = float(np.std(recent)) if len(recent) > 1 else pred_arr.mean() * 0.2

    return _result_df(months, pred_arr, pred_arr - sigma, pred_arr + sigma)


# ────────────────────────────────────────────────
#  מודל 4 — Newsvendor (המלצת רכש)
# ────────────────────────────────────────────────
NEWSVENDOR_DESCRIPTION = (
    "Newsvendor — מחשב כמות רכש אופטימלית תחת אי-ודאות."
    " מאזן בין עלות עודף מלאי לעלות חסר מלאי."
)

def newsvendor_order(mean_demand: float, std_demand: float,
                     gross_margin: float = 0.35,
                     holding_cost_ratio: float = 0.15) -> dict:
    """
    gross_margin      — רווח גולמי יחסי (ברירת מחדל 35%)
    holding_cost_ratio — עלות החזקת מלאי יחסית (ברירת מחדל 15%)
    """
    from scipy.stats import norm

    cu = gross_margin                      # עלות חסר (lost sale)
    co = holding_cost_ratio                # עלות עודף (holding)
    cr = cu / (cu + co)                    # critical ratio

    z        = float(norm.ppf(cr))
    optimal  = mean_demand + z * std_demand
    safety   = z * std_demand

    return {
        'mean_demand':    round(mean_demand, 1),
        'std_demand':     round(std_demand,  1),
        'critical_ratio': round(cr, 3),
        'safety_stock':   max(0, round(safety, 1)),
        'order_quantity': max(0, round(optimal, 0)),
    }


# ────────────────────────────────────────────────
#  ממשק מאחד
# ────────────────────────────────────────────────

def run_all_models(series: pd.Series, horizon: int,
                   events_df: pd.DataFrame, context: dict,
                   progress_callback=None) -> dict:
    """
    מריץ את כל המודלים ומחזיר dict:
    {
        'arima':     DataFrame(year_month, forecast, lower, upper),
        'prophet':   DataFrame(...),
        'xgboost':   DataFrame(...),
        'newsvendor': dict עם המלצת רכש ל-horizon חודשים,
        'descriptions': {model: str},
    }

    progress_callback: Callable[[str], None] אופציונלי. אם סופק, מקבל הודעות
    התקדמות במקום ה-print שהיה כאן בעבר. workers שמשתמשים ב-Qt signals
    צריכים לעטוף את ה-signal.emit ב-callback.
    """
    results = {}

    def _note(msg: str):
        if progress_callback is not None:
            progress_callback(msg)
        else:
            logger.info(msg)

    logger.info("run_all_models: n=%d horizon=%d context=%s", len(series), horizon, context)

    # שימוש ב-forecast_cache עוקף אימון אם הקלטים זהים לריצה קודמת.
    # אם המטמון לא זמין (למשל בייבוא ראשוני/ביצוע מבדיקות), נופל למימושים הישירים.
    try:
        from forecast_cache import cached_arima, cached_prophet, cached_xgboost
        _arima_fn   = cached_arima
        _prophet_fn = cached_prophet
        _xgboost_fn = cached_xgboost
    except Exception:
        _arima_fn, _prophet_fn, _xgboost_fn = forecast_arima, forecast_prophet, forecast_xgboost

    # כל מודל בנפרד עם try/except: כשל בודד לא ממוטט את כל הריצה.
    # ARIMA כבר עוטף את עצמו ב-try (fallback ל-MA(6)), אבל Prophet/XGBoost
    # היו זורקים ישר לקורא. עכשיו השלושה מטופלים אחיד.
    model_errors: dict[str, str] = {}

    def _run_model(name: str, fn):
        try:
            _note(f"  מריץ {name}...")
            return fn(series, horizon, events_df, context)
        except Exception as e:
            logger.exception("%s failed in run_all_models", name)
            model_errors[name] = f"{type(e).__name__}: {e}"
            return None

    results['arima']   = _run_model('ARIMA', _arima_fn)
    results['prophet'] = _run_model('Prophet', _prophet_fn)
    results['xgboost'] = _run_model('XGBoost', _xgboost_fn)

    # Sprint C2.8: מודל סיבתי מבוסס-נוסחה. לא תלוי ב-series; קורא ישירות
    # מ-flight_schedule/flight_traffic ומ-breakage_rate. MAPE 14.9% ב-backtest.
    # ה-slice_share מועבר מ-UI דרך context — מתאר איזה אחוז של ה-core
    # הסלייס-הנבחר מייצג. אם None, ה-causal לא רץ.
    try:
        from causal_forecast import forecast_causal
        slice_share = (context or {}).get('_causal_slice_share')
        if slice_share is not None:
            _note("  מריץ Causal...")
            results['causal'] = forecast_causal(
                series, horizon, events_df, context,
                slice_share=slice_share,
            )
        else:
            results['causal'] = None
    except Exception as e:
        logger.exception("Causal failed in run_all_models")
        model_errors['causal'] = f"{type(e).__name__}: {e}"
        results['causal'] = None

    # Sprint C5: מודל פר-cell. אומן על שבועיים × סניף × קטגוריה
    # (~70K נקודות). הציג 22% שיפור MAE על cells לא-אפסיים ב-sandbox.
    # נקרא רק אם context מכיל פיצ'רים החדשים (anxiety, economy_open וכו') —
    # אחרת מדלגים. הרצה לוקחת ~10 שניות לכל המודל.
    has_new_ctx = any(k in (context or {}) for k in
                       ('anxiety', 'economy_open', 'flight_capacity'))
    if has_new_ctx:
        try:
            from forecast_weekly_cell import forecast_total_by_cell
            _note("  מריץ פר-cell (weekly)...")
            results['weekly_cell'] = forecast_total_by_cell(
                series, horizon, events_df, context
            )
        except Exception as e:
            logger.exception("weekly_cell failed in run_all_models")
            model_errors['weekly_cell'] = f"{type(e).__name__}: {e}"
            results['weekly_cell'] = None
    else:
        results['weekly_cell'] = None

    if model_errors:
        results['model_errors'] = model_errors

    # Newsvendor — רק מהמודלים שהצליחו.
    successful = [m for m in ('arima', 'prophet', 'xgboost')
                  if results.get(m) is not None]
    if not successful:
        raise RuntimeError(f"כל המודלים נכשלו: {model_errors}")
    combined = sum(results[m]['forecast'].values for m in successful) / len(successful)
    results['newsvendor'] = newsvendor_order(
        mean_demand=float(combined.sum()),
        std_demand=float(np.std(series.values[-12:]) * np.sqrt(horizon)),
    )

    from causal_forecast import CAUSAL_DESCRIPTION
    results['descriptions'] = {
        'arima':      ARIMA_DESCRIPTION,
        'prophet':    PROPHET_DESCRIPTION,
        'xgboost':    XGBOOST_DESCRIPTION,
        'causal':     CAUSAL_DESCRIPTION,
        'newsvendor': NEWSVENDOR_DESCRIPTION,
    }
    return results
