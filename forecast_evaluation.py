# -*- coding: utf-8 -*-
"""
forecast_evaluation.py
- backtest: train/test split על סדרה היסטורית, מחשב MAE/RMSE/MAPE לכל מודל.
- save_run: שומר ריצת תחזית מלאה ב-forecast_runs / _predictions / _metrics.
- get_run_history: רשימת ריצות אחרונות עבור UI.

עובד עם forecast_engine הקיים - אין שינוי באלגוריתמים, רק evaluation סביבם.
"""
from __future__ import annotations
import json
from typing import Callable
import numpy as np
import pandas as pd
from psycopg2.extras import execute_values

from db_config import get_conn
from logger import logger
from forecast_engine import forecast_arima, forecast_prophet, forecast_xgboost
from causal_forecast import forecast_causal
from forecast_weekly_cell import forecast_total_by_cell


# Sprint C7.6: causal ו-weekly_cell נכנסים ל-backtest כדי שה-MAE/MAPE שלהם
# יחושב מ-test set אמיתי במקום קבועים. forecast_causal מתעלם מ-series ופונה
# ישירות ל-DB; forecast_total_by_cell מקבל branches/categories דרך context
# (אם חסרים → סך-כללי).
_MODEL_FNS: dict[str, Callable] = {
    'arima':       forecast_arima,
    'prophet':     forecast_prophet,
    'xgboost':     forecast_xgboost,
    'causal':      forecast_causal,
    'weekly_cell': forecast_total_by_cell,
}


# ────────────────────────────────────────────────
#  Metrics
# ────────────────────────────────────────────────
def _mae(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.mean(np.abs(actual - predicted)))


def _rmse(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.sqrt(np.mean((actual - predicted) ** 2)))


def _mape(actual: np.ndarray, predicted: np.ndarray) -> float | None:
    """MAPE - מוגדר רק כשactual!=0; מחזיר None אם אין שורה תקפה."""
    mask = actual != 0
    if not mask.any():
        return None
    return float(np.mean(np.abs((actual[mask] - predicted[mask]) / actual[mask])) * 100.0)


# ────────────────────────────────────────────────
#  Backtest
# ────────────────────────────────────────────────
def _context_for_period(events_df: pd.DataFrame, year_months: list[str]) -> dict:
    """בונה context dict שמייצג את התקופה ההיסטורית של ה-test set.

    Sprint C7.4: עד עכשיו ה-backtest קיבל את ה-context הנוכחי מה-UI
    (למשל is_ceasefire=True) ואז העריך מודלים על חודשים היסטוריים שהיו
    is_war=True. ה-MAE שמוצג למשתמש לא שיקף איך המודל יחזה את ה-truth
    האמיתי בתקופה הזאת.

    התיקון: לבנות context מתוך events_df עצמו עבור החודשים בtest set.
    flags בינאריים (is_war וכו') מקבלים 1 אם ROW כלשהו בתקופה הוא 1
    (dominant). travel_impact + conversion_regime לוקחים את הערך
    הכי שכיח.

    המודלים מצפים לפלט context יחיד פר-ריצה — אז זה ה-best-of-period
    representation. עדיין לא per-prediction-month, אבל הרבה יותר נכון
    מ-current-UI-state.
    """
    if events_df is None or events_df.empty or not year_months:
        return {}
    sub = events_df[events_df['year_month'].isin(year_months)]
    if sub.empty:
        return {}

    ctx: dict = {}
    for binary_col in ('is_war', 'is_military_op', 'is_ceasefire',
                       'is_summer_peak'):
        if binary_col in sub.columns:
            ctx[binary_col] = int((sub[binary_col].fillna(0) > 0).any())

    if 'jewish_holiday' in sub.columns:
        # jewish_holiday ב-DB הוא 0/1/2 (none/passover/highh). לוקחים max.
        ctx['jewish_holiday'] = int(sub['jewish_holiday'].fillna(0).max())

    ctx['is_black_friday'] = int(any(ym.endswith('-11') for ym in year_months))
    ctx['is_routine'] = int(not (ctx.get('is_war') or
                                  ctx.get('is_military_op') or
                                  ctx.get('is_ceasefire')))

    if 'travel_impact' in sub.columns and sub['travel_impact'].notna().any():
        ctx['travel_impact'] = sub['travel_impact'].mode().iloc[0]
    else:
        ctx['travel_impact'] = (
            'very_low' if ctx.get('is_war') else
            'low'      if ctx.get('is_military_op') else
            'high'     if (ctx.get('is_summer_peak') or ctx.get('jewish_holiday')) else 'normal')

    # Sprint C5.1 features (anxiety/economy_open/flight_capacity/...) —
    # אותו mapping שיש ב-forecast_tab._translate_context_to_features.
    # משוכפל כאן בכוונה כדי לא לייבא Qt מ-forecast_tab.py.
    ctx.update(_translate_to_weekly_features(ctx))
    return ctx


def _translate_to_weekly_features(ctx: dict) -> dict:
    is_war = ctx.get('is_war', 0)
    is_op = ctx.get('is_military_op', 0)
    is_cease = ctx.get('is_ceasefire', 0)
    is_holiday = ctx.get('jewish_holiday', 0)
    is_summer = ctx.get('is_summer_peak', 0)

    if is_war and is_op:
        anxiety, economy, flight, spend, passengers = 10, 2, 2, 2, 200_000
    elif is_war:
        anxiety, economy, flight, spend, passengers = 8, 5, 4, 4, 400_000
    elif is_op:
        anxiety, economy, flight, spend, passengers = 6, 7, 7, 6, 500_000
    elif is_cease:
        anxiety, economy, flight, spend, passengers = 3, 9, 9, 10, 800_000
    else:
        anxiety, economy, flight, spend, passengers = 3, 10, 10, 8, 700_000

    if is_holiday:
        spend = min(10, spend + 2)
    if is_summer:
        flight = min(10, flight + 1)
        spend = min(10, spend + 2)
        passengers = int(passengers * 1.5)

    return {
        'anxiety': anxiety,
        'economy_open': economy,
        'flight_capacity': flight,
        'consumer_spending': spend,
        'arriving_passengers': passengers,
    }


def backtest(series: pd.Series, events_df: pd.DataFrame, context: dict,
             test_size: int = 6,
             branches: list | None = None,
             categories: list | None = None) -> dict[str, dict]:
    """
    מאמן כל מודל על series[:-test_size] וחוזה את החלק האחרון.
    מחזיר dict: {model: {'mae': X, 'rmse': Y, 'mape': Z|None, 'test_n': N}}.
    אם הסדרה קצרה מדי - מחזיר dict ריק (אין מספיק נתונים).

    Sprint C7.4: ה-context הנכנס מתעלמים ממנו לטובת context שמשקף את
    התקופה ההיסטורית הנבחנת (חודשי test set). זה מבטיח שהמטריקות שמוצגות
    ל-UI ("דיוק 78%") חושבו תחת אותו state שהמודל יחזה איתו ב-production
    עבור תקופה דומה.

    Sprint C7.7: branches/categories מועברים ל-weekly_cell דרך
    `_selected_branches`/`_selected_categories` ב-period_context. עד C7.6
    ה-backtest תמיד הריץ weekly_cell על "כל הסניפים" ולכן ה-MAE שהוצג
    למשתמש לא תאם לסלייס שהוא בחר ב-UI.
    """
    if len(series) < test_size + 6:
        logger.info("backtest: series too short (%d < %d+6), skipping",
                    len(series), test_size)
        return {}

    train = series.iloc[:-test_size]
    test_yms = list(series.index[-test_size:])
    actual = series.iloc[-test_size:].values.astype(float)

    # Sprint C7.4: context מ-events_df במקום ה-snapshot של ה-UI.
    period_context = _context_for_period(events_df, test_yms)
    if not period_context:
        # fallback: השתמש ב-context שהועבר (התנהגות קודמת). זה קורה רק
        # אם events_df ריק או חסר את החודשים — לא קורה ב-production.
        period_context = dict(context) if context else {}

    # Sprint C7.7: הזרקת ה-slice ל-period_context כדי ש-weekly_cell יתאמן
    # על אותם branches/categories שה-UI מציג. שאר המודלים לא משתמשים
    # במפתחות האלה ולכן זה no-op עבורם.
    if branches:
        period_context['_selected_branches'] = list(branches)
    if categories:
        period_context['_selected_categories'] = list(categories)

    # Sprint C7.9: גם causal צריך slice_share כדי שה-MAE ב-backtest יתאם
    # לסלייס שה-UI מציג. עד C7.8, causal ב-backtest רץ עם share=1.0 (כל
    # ה-core) ולכן ה-MAE שהוצג היה למלוא 9 הסניפים, לא לסלייס הנבחר.
    if branches or categories:
        try:
            from causal_forecast import compute_slice_share
            share = compute_slice_share(branches, categories)
            if share is not None:
                period_context['_causal_slice_share'] = share
        except Exception:
            logger.exception("backtest: compute_slice_share failed; "
                             "causal stays on full-core")

    metrics: dict[str, dict] = {}

    for name, fn in _MODEL_FNS.items():
        try:
            df = fn(train, test_size, events_df, period_context)
            pred = df['forecast'].values.astype(float)[:test_size]
            metrics[name] = {
                'test_n': int(test_size),
                'mae':    _mae(actual, pred),
                'rmse':   _rmse(actual, pred),
                'mape':   _mape(actual, pred),
            }
        except Exception as e:
            logger.exception("backtest %s failed", name)
            metrics[name] = {
                'test_n': int(test_size),
                'mae':    None, 'rmse': None, 'mape': None,
                'error':  f"{type(e).__name__}: {e}",
            }

    return metrics


# ────────────────────────────────────────────────
#  Persistence
# ────────────────────────────────────────────────
def save_run(branches: list[str], categories: list[str],
             horizon_months: int, context: dict, series_n: int,
             results: dict, metrics: dict | None = None,
             ran_by: str | None = None, notes: str | None = None) -> int:
    """
    שומר ריצת תחזית ב-forecast_runs (+ predictions + metrics).
    results: dict[model -> DataFrame(year_month, forecast, lower, upper)]
             שווה לפלט של forecast_engine.run_all_models.
    מחזיר run_id.
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO forecast_runs
                (ran_by, branches, categories, horizon_months,
                 context_json, series_n, notes)
            VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)
            RETURNING run_id
        """, (
            ran_by or _current_user(),
            branches, categories,
            horizon_months,
            json.dumps(context, ensure_ascii=False),
            series_n,
            notes,
        ))
        run_id = cur.fetchone()[0]

        # predictions — bulk insert עם execute_values
        # Sprint C7.9: כל מודל ש-results מכיל DataFrame עבורו (גם causal,
        # gold weekly_cell) נשמר. עד C7.8 רק 3 מודלים סטטיסטיים נשמרו, אז
        # ה-UI הציג metrics ל-causal/weekly_cell אבל ה-predictions עצמן
        # לא תועדו ב-DB.
        pred_rows = []
        for model_name, df in results.items():
            # דילוג על non-DataFrame entries (newsvendor, descriptions, metrics, ...)
            if not isinstance(df, pd.DataFrame) or df.empty:
                continue
            if 'year_month' not in df.columns or 'forecast' not in df.columns:
                continue
            for _, row in df.iterrows():
                pred_rows.append((
                    run_id, model_name,
                    str(row['year_month']),
                    float(row['forecast']),
                    float(row['lower']) if pd.notna(row.get('lower')) else None,
                    float(row['upper']) if pd.notna(row.get('upper')) else None,
                ))

        # 'avg' (ממוצע 3 המודלים) לצרכי השוואה אחר כך
        # Sprint C7.9: results[m] יכול להיות None אם המודל נפל ב-_run_model.
        # ה-guard המקורי בדק `m in results` בלבד וקרס על None.empty.
        models_with_data = [m for m in ('arima', 'prophet', 'xgboost')
                            if results.get(m) is not None and not results[m].empty]
        if len(models_with_data) >= 2:
            base = results[models_with_data[0]]
            avg_forecast = sum(results[m]['forecast'].values
                               for m in models_with_data) / len(models_with_data)
            for ym, val in zip(base['year_month'].tolist(), avg_forecast):
                pred_rows.append((run_id, 'avg', str(ym), float(val), None, None))

        if pred_rows:
            execute_values(cur, """
                INSERT INTO forecast_predictions
                    (run_id, model, year_month, forecast, lower, upper)
                VALUES %s
                ON CONFLICT (run_id, model, year_month) DO NOTHING
            """, pred_rows)

        # metrics — bulk insert
        if metrics:
            metric_rows = [
                (
                    run_id, model_name,
                    m.get('test_n'),
                    m.get('mae'),
                    m.get('rmse'),
                    m.get('mape'),
                )
                for model_name, m in metrics.items()
            ]
            if metric_rows:
                execute_values(cur, """
                    INSERT INTO forecast_metrics
                        (run_id, model, test_n, mae, rmse, mape)
                    VALUES %s
                    ON CONFLICT (run_id, model) DO NOTHING
                """, metric_rows)

    # get_conn() commits on clean exit; no manual commit needed.
    logger.info("forecast run saved: id=%d horizon=%d branches=%s",
                run_id, horizon_months, branches)
    return run_id


def get_run_history(limit: int = 30) -> pd.DataFrame:
    """מחזיר DataFrame של ריצות אחרונות (ל-UI ב-updates/forecast tab)."""
    with get_conn() as conn:
        return pd.read_sql_query("""
            SELECT
                r.run_id, r.ran_at, r.ran_by,
                array_length(r.branches, 1)   AS n_branches,
                array_length(r.categories, 1) AS n_categories,
                r.horizon_months, r.series_n,
                COALESCE(m.mae,  0) AS arima_mae,
                COALESCE(m2.mae, 0) AS prophet_mae,
                COALESCE(m3.mae, 0) AS xgboost_mae
            FROM forecast_runs r
            LEFT JOIN forecast_metrics m  ON m.run_id  = r.run_id AND m.model  = 'arima'
            LEFT JOIN forecast_metrics m2 ON m2.run_id = r.run_id AND m2.model = 'prophet'
            LEFT JOIN forecast_metrics m3 ON m3.run_id = r.run_id AND m3.model = 'xgboost'
            ORDER BY r.ran_at DESC
            LIMIT %s
        """, conn, params=(limit,))


def _current_user() -> str:
    import os
    return os.environ.get('USERNAME') or os.environ.get('USER') or 'unknown'
