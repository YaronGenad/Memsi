# -*- coding: utf-8 -*-
"""
forecast_per_branch_hybrid.py — Sprint C8.3.

Replaces forecast_hierarchical for the per-cell tab.

Why: the old forecast_hierarchical trained one ARIMA/Prophet/XGBoost model
PER CELL on ~40 monthly points. With 225 cells, that's 225 tiny noisy models
that over-fit. May 2026 prediction came out at 921 (actual: 396, 2.33× over).

This module uses the hybrid approach validated in C8.2:
  - Per-branch monthly base level (recency-weighted, post-Oct-2024 only)
  - Seasonal shape learned from ALL history but NORMALIZED (ratios, not levels)
  - Category disaggregation via 6-month proportions per branch
  - Inactive branch filter (no activity in last 3 months → skip)

API-compatible with forecast_hierarchical:
  forecast_per_branch_hybrid(hist_df, horizon, events_df, context, ...) -> dict
with the same shape ({cells, aggregate, n_cells_processed, ...}).

forecast_hierarchical.py is kept on disk for fast rollback if this misbehaves.
"""
from __future__ import annotations

from typing import Callable
import numpy as np
import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta

from logger import logger
from forecast_hierarchical import CellForecast   # reuse dataclass for shape


# ---------- Configuration ----------
POST_BREAK_START = '2024-11'   # baseline level trains from here onward
INACTIVE_THRESHOLD_MONTHS = 3  # branch needs activity in last N months
MIN_HIST_MONTHS = 18           # branch needs at least this many months
CATEGORY_LOOKBACK_MONTHS = 6   # category proportions over last N months
RECENT_BASE_WEIGHTS = np.array([0.2, 0.3, 0.5])  # exp-decay on last 3 deseasonalized
HYBRID_FALLBACK_LABEL = 'hybrid_branch'


# ---------- Core math (lifted from research/per_branch_forecast.py) ----------
def compute_seasonal_shape(series: pd.Series) -> dict[int, float]:
    """Per month-of-year, the ratio of value to centered rolling-12 mean.
    Normalized so the average across 12 months = 1.0.

    Captures shape (Aug is X% above annual avg) without inheriting the
    absolute level of any single year — so the 2024 surge doesn't pollute
    the seasonal index.
    """
    if len(series) < 12:
        return {m: 1.0 for m in range(1, 13)}
    months = pd.to_datetime(series.index + '-01').month
    df = pd.DataFrame({'y': series.values.astype(float), 'm': months.values})
    df['rolling12'] = df['y'].rolling(12, center=True, min_periods=6).mean()
    df['ratio'] = df['y'] / df['rolling12'].replace(0, np.nan)
    grouped = df.dropna(subset=['ratio']).groupby('m')['ratio'].mean()
    raw = {m: float(grouped.get(m, 1.0)) for m in range(1, 13)}
    avg = float(np.mean(list(raw.values())))
    if avg == 0:
        return raw
    return {m: raw[m] / avg for m in raw}


def compute_base_level(series: pd.Series, post_break_start: str,
                       seasonal: dict[int, float]) -> float:
    """Deseasonalize the post-break window and recency-weighted mean of last 3.
    Falls back to simple recent mean if too few post-break months."""
    post = series[series.index >= post_break_start]
    if len(post) == 0:
        return float(series.iloc[-3:].mean()) if len(series) >= 1 else 0.0
    months = pd.to_datetime(post.index + '-01').month
    deseason = post.values.astype(float) / np.array(
        [max(seasonal[m], 0.1) for m in months]
    )
    if len(deseason) >= 3:
        return float(np.dot(deseason[-3:], RECENT_BASE_WEIGHTS))
    return float(np.mean(deseason))


# ---------- Data slicing ----------
def _branch_monthly(hist_df: pd.DataFrame, branch: str) -> pd.Series:
    """Returns sorted pd.Series of branch's monthly totals."""
    sub = hist_df[hist_df['branch'] == branch]
    if sub.empty:
        return pd.Series(dtype=float)
    return sub.groupby('year_month')['quantity'].sum().sort_index()


def _cell_monthly(hist_df: pd.DataFrame, branch: str, cell: str) -> pd.Series:
    """Returns sorted pd.Series of (branch, cell) monthly totals."""
    sub = hist_df[(hist_df['branch'] == branch) &
                  (hist_df['luggage_type'] == cell)]
    if sub.empty:
        return pd.Series(dtype=float)
    return sub.groupby('year_month')['quantity'].sum().sort_index()


def is_active_branch(hist_df: pd.DataFrame, branch: str,
                     last_n: int = INACTIVE_THRESHOLD_MONTHS) -> bool:
    """True if the branch had activity in at least one of the LAST 2 months
    AND in at least 2 of the last `last_n` months. This catches "zombie"
    branches whose last activity was 3+ months ago (e.g. הלל כפר סבא had
    activity in Feb 2026 but nothing in Mar/Apr → trailing decline, not
    active).
    Looking only at "any activity in last 3 months" is too lenient — it
    keeps branches that stopped in the last quarter still in the forecast.
    """
    s = _branch_monthly(hist_df, branch)
    if s.empty:
        return False
    global_last = hist_df['year_month'].max()
    # Build the exact list of last `last_n` months
    last_yms = [_add_months(global_last, -i) for i in range(last_n)]   # e.g. [Apr, Mar, Feb]
    values = [float(s.get(ym, 0.0)) for ym in last_yms]
    # Rule A: at least one of the last 2 months has activity
    if not any(v > 0 for v in values[:2]):
        return False
    # Rule B: at least 2 of the last `last_n` months had activity
    if sum(1 for v in values if v > 0) < 2:
        return False
    return True


def compute_category_proportions(hist_df: pd.DataFrame, branch: str,
                                  lookback: int = CATEGORY_LOOKBACK_MONTHS) -> dict[str, float]:
    """Returns {category: proportion} based on last `lookback` months of
    the given branch. Proportions sum to 1.0 across non-zero cells.
    Empty dict if branch has no recent activity."""
    s = hist_df[hist_df['branch'] == branch]
    if s.empty:
        return {}
    global_last = s['year_month'].max()
    cutoff = _add_months(global_last, -(lookback - 1))
    recent = s[s['year_month'] >= cutoff]
    if recent.empty:
        return {}
    totals = recent.groupby('luggage_type')['quantity'].sum()
    total_sum = float(totals.sum())
    if total_sum <= 0:
        return {}
    return {str(cat): float(qty) / total_sum for cat, qty in totals.items()}


# ---------- Month arithmetic ----------
def _add_months(ym: str, n: int) -> str:
    """ym = 'YYYY-MM', add n months (n can be negative). Returns 'YYYY-MM'."""
    dt = datetime.strptime(ym + '-01', '%Y-%m-%d') + relativedelta(months=n)
    return dt.strftime('%Y-%m')


def _next_n_months(last_ym: str, n: int) -> list[str]:
    """Returns [last_ym+1, last_ym+2, ..., last_ym+n]."""
    return [_add_months(last_ym, i) for i in range(1, n + 1)]


# ---------- Main forecast function ----------
def forecast_per_branch_hybrid(
    hist_df: pd.DataFrame,
    horizon: int,
    events_df: pd.DataFrame,
    context: dict,
    branches: list[str] | None = None,
    cells: list[str] | None = None,
    n_folds: int = 5,
    progress_callback: Callable[[str], None] | None = None,
) -> dict:
    """Drop-in replacement for forecast_hierarchical.forecast_hierarchical.

    Same return shape:
        {
            'cells': dict[(branch, cell)] -> CellForecast,
            'aggregate': dict[year_month -> float],
            'n_cells_processed': int,
            'n_cells_full': int,
            'n_cells_fallback': int,
        }

    Logic:
      1. Filter to active branches (activity in last 3 months) with enough history.
      2. For each branch, compute monthly forecast via hybrid (base × seasonal).
      3. Disaggregate to categories using 6-month proportions.
      4. Return per-cell forecasts in CellForecast objects.

    The `n_folds` arg is accepted for API compatibility but ignored (the
    hybrid doesn't need cross-validation — its base/seasonal are
    deterministic from the data window).
    """
    if hist_df is None or hist_df.empty:
        return {'cells': {}, 'aggregate': {}, 'n_cells_processed': 0,
                'n_cells_full': 0, 'n_cells_fallback': 0}

    # Normalize and filter
    hist_df = hist_df.copy()
    hist_df['year_month'] = hist_df['year_month'].astype(str)
    if branches:
        hist_df = hist_df[hist_df['branch'].isin(branches)]
    if cells:
        hist_df = hist_df[hist_df['luggage_type'].isin(cells)]
    if hist_df.empty:
        return {'cells': {}, 'aggregate': {}, 'n_cells_processed': 0,
                'n_cells_full': 0, 'n_cells_fallback': 0}

    # Generate target year_months from the latest data point
    global_last_ym = hist_df['year_month'].max()
    target_yms = _next_n_months(global_last_ym, horizon)

    # Active branches with enough history
    candidate_branches = sorted(hist_df['branch'].unique())
    active = []
    for b in candidate_branches:
        if not is_active_branch(hist_df, b):
            continue
        s = _branch_monthly(hist_df, b)
        if len(s) < MIN_HIST_MONTHS:
            continue
        active.append(b)

    logger.info("forecast_per_branch_hybrid: %d candidates → %d active",
                len(candidate_branches), len(active))

    results: dict[tuple[str, str], CellForecast] = {}
    aggregate = {ym: 0.0 for ym in target_yms}
    n_full, n_fallback = 0, 0

    for i, branch in enumerate(active):
        if progress_callback:
            progress_callback(f"[{i+1}/{len(active)}] {branch}")

        branch_series = _branch_monthly(hist_df, branch)
        seasonal = compute_seasonal_shape(branch_series)
        base = compute_base_level(branch_series, POST_BREAK_START, seasonal)
        branch_fc_by_ym = {
            ym: max(base * seasonal[int(ym.split('-')[1])], 0.0)
            for ym in target_yms
        }

        # Category proportions for this branch (last 6 months)
        cat_props = compute_category_proportions(hist_df, branch)
        if not cat_props:
            logger.debug("forecast_per_branch_hybrid: branch %s has no recent "
                         "category activity, skipping", branch)
            continue

        # If caller restricted cells, intersect with branch's active cells
        target_cells = list(cat_props.keys())
        if cells:
            target_cells = [c for c in target_cells if c in cells]

        for cell in target_cells:
            prop = cat_props.get(cell, 0.0)
            if prop <= 0:
                continue
            rows = []
            for ym in target_yms:
                fval = branch_fc_by_ym[ym] * prop
                rows.append({
                    'year_month': ym,
                    'forecast': fval,
                    'lower': max(fval * 0.7, 0.0),
                    'upper': fval * 1.3,
                })
                aggregate[ym] += fval
            cell_fcst_df = pd.DataFrame(rows)
            n_obs = len(_cell_monthly(hist_df, branch, cell))
            cf = CellForecast(
                branch=branch,
                cell=cell,
                n_obs=n_obs,
                fallback_level=HYBRID_FALLBACK_LABEL,
                forecasts={'hybrid': cell_fcst_df},
                metrics={'hybrid': {'mae': None, 'rmse': None, 'mape': None}},
                champion='hybrid',
            )
            results[(branch, cell)] = cf
            n_full += 1

    logger.info("forecast_per_branch_hybrid: produced %d cells, agg first month=%.1f",
                len(results),
                aggregate.get(target_yms[0], 0.0) if target_yms else 0.0)

    return {
        'cells': results,
        'aggregate': aggregate,
        'n_cells_processed': len(results),
        'n_cells_full': n_full,
        'n_cells_fallback': n_fallback,
    }


# ---------- Module smoke test (if invoked directly) ----------
if __name__ == '__main__':
    from forecast_db import ForecastDB
    fdb = ForecastDB()
    hist = fdb.get_history()
    print(f"hist rows: {len(hist)}")
    res = forecast_per_branch_hybrid(
        hist, horizon=6, events_df=fdb.get_events(), context={},
    )
    print(f"cells: {res['n_cells_processed']}")
    print(f"aggregate (first 3 months):")
    for ym, q in list(res['aggregate'].items())[:3]:
        print(f"  {ym}: {q:.1f}")
    if ('05', 'גדולה קלאסית קשיחה') in res['cells']:
        cf = res['cells'][('05', 'גדולה קלאסית קשיחה')]
        v = cf.forecasts['hybrid'].iloc[0]['forecast']
        print(f"05 × גדולה קלאסית קשיחה first month: {v:.2f}")
