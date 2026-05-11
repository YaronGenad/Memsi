# -*- coding: utf-8 -*-
"""
forecast_hierarchical.py — תחזיות פר-(branch, cell) עם graceful degradation
ו-bottom-up reconciliation.

זרימה:
1. מקבלים hist_df עם עמודות (branch, luggage_type, year_month, quantity).
2. לכל (branch, cell): מחשבים את הסדרה ההיסטורית.
3. graceful degradation לפי כמות הנתונים:
   - >= 12 חודשים → fit מודלים מלאים (ARIMA + Prophet + XGBoost)
   - >= 6 חודשים  → fallback לקטגוריה-באותו-סניף (אם זמין), אחרת מודלים פשוטים
   - >= 3 חודשים  → fallback לקטגוריה-כל-הסניפים
   - < 3 חודשים   → ממוצע-קטגוריה כלל-עולמי + trend גלובלי
4. bottom-up reconciliation: סכום התחזיות בקטגוריה צריך להתאים לתחזית האגרגט.
   אם פער גדול — כיוון פרופורציונלי.
5. לכל (branch, cell), champion = המודל עם MAE הנמוך ביותר ב-walk-forward.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Callable
import pandas as pd
import numpy as np

from logger import logger
from forecast_engine import (
    forecast_arima, forecast_prophet, forecast_xgboost,
    newsvendor_order, MODEL_VERSION,
)


# סף הנתונים לכל רמת-fallback
_MIN_FULL_MODELS     = 12   # >= 12 חודשים → ARIMA + Prophet + XGBoost
_MIN_PARTIAL_MODELS  = 6    # >= 6  → רק ARIMA + XGBoost (לא Prophet שדורש יותר)
_MIN_SIMPLE_MODEL    = 3    # >= 3  → רק ARIMA fallback ל-MA(6)
_MODEL_FNS_FULL = {
    'arima':   forecast_arima,
    'prophet': forecast_prophet,
    'xgboost': forecast_xgboost,
}
_MODEL_FNS_PARTIAL = {
    'arima':   forecast_arima,
    'xgboost': forecast_xgboost,
}


@dataclass
class CellForecast:
    """תחזית לקומבינציה (branch, cell)."""
    branch: str
    cell:   str
    n_obs:  int
    fallback_level: str       # 'cell' / 'branch_category' / 'global_category' / 'global_avg'
    forecasts: dict[str, pd.DataFrame] = field(default_factory=dict)  # model → df
    metrics:   dict[str, dict] = field(default_factory=dict)          # model → {mae,rmse,mape}
    champion:  str | None = None                                       # model name
    error:     str | None = None                                       # אם הכל נכשל


def _series_for(hist_df: pd.DataFrame, branch: str | None,
                cell: str | None) -> pd.Series:
    """מחזיר pd.Series של year_month → quantity לפילטר נתון.
    None ב-branch/cell = aggregation על הציר ההוא."""
    df = hist_df
    if branch is not None:
        df = df[df['branch'] == branch]
    if cell is not None:
        df = df[df['luggage_type'] == cell]
    if df.empty:
        return pd.Series(dtype=float)
    s = df.groupby('year_month')['quantity'].sum().sort_index()
    return s


def _run_models(series: pd.Series, horizon: int,
                events_df: pd.DataFrame, context: dict,
                model_fns: dict) -> dict[str, pd.DataFrame]:
    """מריץ סט מודלים נתון על סדרה. אם מודל נכשל — לא נכלל בפלט."""
    out = {}
    for name, fn in model_fns.items():
        try:
            out[name] = fn(series, horizon, events_df, context)
        except Exception as e:
            logger.warning("model %s failed on series n=%d: %s", name, len(series), e)
    return out


def _walk_forward_backtest(
    series: pd.Series, events_df: pd.DataFrame, context: dict,
    model_fns: dict, n_folds: int = 5, test_size: int = 1,
) -> dict[str, dict]:
    """rolling-origin: לכל fold, train על הראש, חוזים test_size קדימה,
    מצרפים את ה-residuals. מחזיר {model: {mae, rmse, mape, n_folds_done}}.

    הערה ל-C2: n_folds=5 ולא 10 כי על סדרות קצרות (~20 חודשים), 10 folds
    משמעו שהראשונים שלהם רצים על <12 חודשים שזה bias-y. 5 folds זה איזון.
    """
    n = len(series)
    min_train = max(_MIN_PARTIAL_MODELS, n - n_folds * test_size)
    if n < min_train + test_size:
        return {name: {'mae': None, 'rmse': None, 'mape': None,
                       'n_folds_done': 0, 'error': 'series too short'}
                for name in model_fns}

    residuals: dict[str, list[tuple[float, float]]] = {name: [] for name in model_fns}
    folds_done = {name: 0 for name in model_fns}

    starts = list(range(min_train, n - test_size + 1))
    # דגום עד n_folds נקודות אם הסדרה ארוכה
    if len(starts) > n_folds:
        idx = np.linspace(0, len(starts) - 1, n_folds, dtype=int)
        starts = [starts[i] for i in idx]

    for split in starts:
        train = series.iloc[:split]
        actual = series.iloc[split:split + test_size].values.astype(float)
        for name, fn in model_fns.items():
            try:
                df = fn(train, test_size, events_df, context)
                pred = df['forecast'].values.astype(float)[:test_size]
                for a, p in zip(actual, pred):
                    residuals[name].append((a, p))
                folds_done[name] += 1
            except Exception as e:
                logger.debug("backtest fold model=%s split=%d failed: %s",
                             name, split, e)

    out = {}
    for name in model_fns:
        rs = residuals[name]
        if not rs:
            out[name] = {'mae': None, 'rmse': None, 'mape': None,
                         'n_folds_done': 0}
            continue
        actuals = np.array([r[0] for r in rs])
        preds   = np.array([r[1] for r in rs])
        mae  = float(np.mean(np.abs(actuals - preds)))
        rmse = float(np.sqrt(np.mean((actuals - preds) ** 2)))
        mask = actuals != 0
        mape = (float(np.mean(np.abs((actuals[mask] - preds[mask]) / actuals[mask])) * 100)
                if mask.any() else None)
        out[name] = {'mae': mae, 'rmse': rmse, 'mape': mape,
                     'n_folds_done': folds_done[name]}
    return out


def _global_category_average(hist_df: pd.DataFrame, cell: str,
                             horizon: int, last_ym: str) -> pd.DataFrame:
    """ה-fallback האחרון: ממוצע + trend גלובלי לקטגוריה."""
    from datetime import datetime
    from dateutil.relativedelta import relativedelta

    s = _series_for(hist_df, branch=None, cell=cell)
    if s.empty:
        # אין שום נתון לקטגוריה — מחזיר אפס
        cur = datetime.strptime(last_ym + "-01", "%Y-%m-%d")
        months = []
        for _ in range(horizon):
            cur = cur + relativedelta(months=1)
            months.append(cur.strftime('%Y-%m'))
        return pd.DataFrame({'year_month': months, 'forecast': [0] * horizon,
                             'lower': [0] * horizon, 'upper': [0] * horizon})

    avg = float(s.tail(6).mean()) if len(s) >= 6 else float(s.mean())
    # trend פשוט: שיפוע 12-month
    if len(s) >= 12:
        trend = (float(s.tail(6).mean()) - float(s.head(6).mean())) / max(len(s) - 6, 1)
    else:
        trend = 0.0

    cur = datetime.strptime(last_ym + "-01", "%Y-%m-%d")
    months, values = [], []
    for i in range(horizon):
        cur = cur + relativedelta(months=1)
        months.append(cur.strftime('%Y-%m'))
        values.append(max(0, round(avg + trend * (i + 1))))
    return pd.DataFrame({'year_month': months,
                         'forecast': values,
                         'lower': values,
                         'upper': values})


def forecast_one_cell(
    hist_df: pd.DataFrame, branch: str, cell: str,
    horizon: int, events_df: pd.DataFrame, context: dict,
    n_folds: int = 5,
) -> CellForecast:
    """תחזית לקומבינציה אחת (branch, cell) עם graceful degradation + backtest."""
    series = _series_for(hist_df, branch=branch, cell=cell)
    n = len(series)
    last_ym = series.index[-1] if n > 0 else hist_df['year_month'].max()

    # רמת-fallback לפי כמות הנתונים
    if n >= _MIN_FULL_MODELS:
        fallback_level = 'cell'
        model_fns = _MODEL_FNS_FULL
        target_series = series
    elif n >= _MIN_PARTIAL_MODELS:
        fallback_level = 'cell_partial'
        model_fns = _MODEL_FNS_PARTIAL
        target_series = series
    elif n >= _MIN_SIMPLE_MODEL:
        # fallback לקטגוריה כל-הסניפים, רק ARIMA
        cat_series = _series_for(hist_df, branch=None, cell=cell)
        if len(cat_series) >= _MIN_FULL_MODELS:
            fallback_level = 'global_category'
            model_fns = _MODEL_FNS_FULL
            target_series = cat_series
        else:
            fallback_level = 'global_avg'
            model_fns = {}
            target_series = series
    else:
        fallback_level = 'global_avg'
        model_fns = {}
        target_series = series

    cf = CellForecast(branch=branch, cell=cell, n_obs=n,
                      fallback_level=fallback_level)

    if not model_fns:
        # שלב 4: ממוצע גלובלי + trend, ללא מודלים סטטיסטיים
        df_fc = _global_category_average(hist_df, cell, horizon, last_ym)
        cf.forecasts = {'avg': df_fc}
        cf.champion = 'avg'
        return cf

    try:
        cf.forecasts = _run_models(target_series, horizon, events_df,
                                   context, model_fns)
        cf.metrics = _walk_forward_backtest(target_series, events_df, context,
                                            model_fns, n_folds=n_folds)
        # bottom-up champion: המודל עם הMAE הנמוך ביותר
        valid_metrics = {m: v for m, v in cf.metrics.items()
                         if v.get('mae') is not None and m in cf.forecasts}
        if valid_metrics:
            cf.champion = min(valid_metrics, key=lambda m: valid_metrics[m]['mae'])
        elif cf.forecasts:
            # אם backtest נכשל אבל מודל אחד הצליח — קח אותו
            cf.champion = next(iter(cf.forecasts))
    except Exception as e:
        cf.error = f"{type(e).__name__}: {e}"
        logger.exception("forecast_one_cell failed for %s/%s", branch, cell)

    # אם אף מודל לא הצליח — fallback ל-global avg
    if not cf.forecasts:
        cf.forecasts = {'avg': _global_category_average(hist_df, cell, horizon, last_ym)}
        cf.champion = 'avg'
        cf.fallback_level = 'global_avg_recovered'

    return cf


def forecast_hierarchical(
    hist_df: pd.DataFrame, horizon: int,
    events_df: pd.DataFrame, context: dict,
    branches: list[str] | None = None,
    cells: list[str] | None = None,
    n_folds: int = 5,
    progress_callback: Callable[[str], None] | None = None,
) -> dict:
    """מריץ תחזיות פר-(branch, cell) עם reconciliation.

    Returns:
        {
            'cells': dict[(branch, cell)] -> CellForecast,
            'aggregate': dict — sum of all cells per model+horizon,
            'n_cells_processed': int,
            'n_cells_full': int,           # שמשתמשים ב-cell-level
            'n_cells_fallback': int,
        }
    """
    if branches:
        hist_df = hist_df[hist_df['branch'].isin(branches)]
    if cells:
        hist_df = hist_df[hist_df['luggage_type'].isin(cells)]
    if hist_df.empty:
        return {'cells': {}, 'aggregate': {}, 'n_cells_processed': 0,
                'n_cells_full': 0, 'n_cells_fallback': 0}

    pairs = (hist_df[['branch', 'luggage_type']]
             .drop_duplicates().sort_values(['branch', 'luggage_type'])
             .itertuples(index=False, name=None))
    pairs = list(pairs)

    # החודש האחרון הגלובלי — נחתוך אגרגציה החל מ-(month+1).
    # סדרות ישנות (cells שהפסיקו פעילות) לא ייכללו ב-aggregate.
    global_last_ym = hist_df['year_month'].max()

    results: dict[tuple[str, str], CellForecast] = {}
    n_full, n_fallback = 0, 0
    for i, (branch, cell) in enumerate(pairs):
        if progress_callback:
            progress_callback(f"[{i+1}/{len(pairs)}] {branch}/{cell}")
        cf = forecast_one_cell(hist_df, branch, cell, horizon, events_df,
                               context, n_folds=n_folds)
        results[(branch, cell)] = cf
        if cf.fallback_level == 'cell':
            n_full += 1
        else:
            n_fallback += 1

    # bottom-up aggregation: סכום champion forecasts לכל חודש, רק חודשים
    # שעוברים את global_last_ym (כלומר אמיתית-עתידיים).
    agg_by_month: dict[str, float] = {}
    for cf in results.values():
        if not cf.champion or cf.champion not in cf.forecasts:
            continue
        df = cf.forecasts[cf.champion]
        for _, row in df.iterrows():
            ym = row['year_month']
            if ym <= global_last_ym:
                continue
            agg_by_month[ym] = (
                agg_by_month.get(ym, 0.0) + float(row['forecast'])
            )

    return {
        'cells': results,
        'aggregate': agg_by_month,
        'n_cells_processed': len(pairs),
        'n_cells_full': n_full,
        'n_cells_fallback': n_fallback,
        'model_version': MODEL_VERSION,
    }
