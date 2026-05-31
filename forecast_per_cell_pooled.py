# -*- coding: utf-8 -*-
"""
forecast_per_cell_pooled.py — Sprint C8.4.

Per-cell tab now uses the SAME pooled-weekly-cell model the main forecast tab
uses, so the per-cell numbers match the main tab cell-by-cell. The hybrid from
C8.3 was closer than C7's per-cell forecast_hierarchical, but the main tab's
forecast_weekly_cell.forecast_per_cell still beats it on the (05, גדולה
קלאסית קשיחה) sniff (10 vs hybrid 8.4, actual 11) because it has regime
features and pools across all cells via a single LinearRegression.

API-compatible with forecast_per_branch_hybrid: same signature, same return
shape ({cells, aggregate, n_cells_processed, n_cells_full, n_cells_fallback}).

forecast_per_branch_hybrid.py is kept on disk for one-commit rollback.
"""
from __future__ import annotations

from typing import Callable

import pandas as pd

from logger import logger
from forecast_hierarchical import CellForecast
from forecast_per_branch_hybrid import is_active_branch, _cell_monthly


def forecast_per_cell_pooled(
    hist_df: pd.DataFrame,
    horizon: int,
    events_df: pd.DataFrame,
    context: dict,
    branches: list[str] | None = None,
    cells: list[str] | None = None,
    n_folds: int = 5,
    progress_callback: Callable[[str], None] | None = None,
) -> dict:
    """Drop-in replacement for forecast_per_branch_hybrid.

    Wraps forecast_weekly_cell.forecast_per_cell — the same pooled
    regression the main tab uses — and emits the per-cell-tab return
    shape (cells, aggregate, n_cells_processed, ...).
    """
    if hist_df is None or hist_df.empty:
        return {'cells': {}, 'aggregate': {}, 'n_cells_processed': 0,
                'n_cells_full': 0, 'n_cells_fallback': 0}

    ctx = dict(context or {})

    # 1. Translate binary regime flags to the numeric features the pooled
    #    model expects (anxiety, economy_open, flight_capacity, etc.).
    #    Lazy import to avoid circular import with forecast_tab.
    if 'anxiety' not in ctx:
        from forecast_tab import _translate_context_to_features
        ctx = {**ctx, **_translate_context_to_features(ctx)}

    if progress_callback:
        progress_callback("מאמן מודל pooled על כל ה-cells (~10s)...")

    # 2. Call the existing pooled per-cell model.
    from forecast_weekly_cell import forecast_per_cell
    df = forecast_per_cell(
        horizon_months=horizon,
        context=ctx,
        categories=cells,
        branches=branches,
    )

    if df.empty:
        logger.warning("forecast_per_cell_pooled: pooled model returned empty df")
        return {'cells': {}, 'aggregate': {}, 'n_cells_processed': 0,
                'n_cells_full': 0, 'n_cells_fallback': 0}

    # 3. Filter to active branches (same rule as the hybrid in C8.3 — drops
    #    zombie branches like הלל כפר סבא that haven't moved in 3 months).
    if progress_callback:
        progress_callback("מסנן סניפי-זומבי...")
    active_branches = {
        b for b in df['branch'].unique() if is_active_branch(hist_df, b)
    }
    if not active_branches:
        logger.warning("forecast_per_cell_pooled: no active branches after filter")
    df = df[df['branch'].isin(active_branches)].copy()

    # 4. Reshape df → {(branch, cell): CellForecast, ...}
    if progress_callback:
        progress_callback("בונה טבלה...")

    cells_out: dict[tuple[str, str], CellForecast] = {}
    aggregate: dict[str, float] = {}

    for (branch, cat), sub in df.groupby(['branch', 'category']):
        sub_sorted = sub.sort_values('year_month')
        fc_df = sub_sorted[['year_month', 'forecast']].copy()
        fc_df['lower'] = (fc_df['forecast'] * 0.7).clip(lower=0.0)
        fc_df['upper'] = fc_df['forecast'] * 1.3
        n_obs = len(_cell_monthly(hist_df, branch, cat))
        cells_out[(branch, cat)] = CellForecast(
            branch=branch,
            cell=cat,
            n_obs=n_obs,
            fallback_level='pooled_weekly',
            forecasts={'pooled': fc_df},
            metrics={'pooled': {'mae': None, 'rmse': None, 'mape': None}},
            champion='pooled',
        )
        for _, r in sub_sorted.iterrows():
            ym = str(r['year_month'])
            aggregate[ym] = aggregate.get(ym, 0.0) + float(r['forecast'])

    logger.info(
        "forecast_per_cell_pooled: %d cells across %d active branches, "
        "aggregate first month=%.1f",
        len(cells_out), len(active_branches),
        next(iter(aggregate.values())) if aggregate else 0.0,
    )

    return {
        'cells': cells_out,
        'aggregate': aggregate,
        'n_cells_processed': len(cells_out),
        'n_cells_full': len(cells_out),
        'n_cells_fallback': 0,
    }


# ---------- Module smoke test ----------
if __name__ == '__main__':
    from forecast_db import ForecastDB
    fdb = ForecastDB()
    hist = fdb.get_history()
    print(f"hist rows: {len(hist)}")
    res = forecast_per_cell_pooled(
        hist, horizon=6, events_df=fdb.get_events(),
        context={'is_war': 0, 'is_ceasefire': 1, 'jewish_holiday': 0},
    )
    print(f"cells: {res['n_cells_processed']}")
    print("aggregate (first 3 months):")
    for ym, q in list(sorted(res['aggregate'].items()))[:3]:
        print(f"  {ym}: {q:.1f}")
    key = ('05', 'גדולה קלאסית קשיחה')
    if key in res['cells']:
        cf = res['cells'][key]
        df = cf.forecasts['pooled']
        for _, r in df.iterrows():
            print(f"  {key} {r['year_month']}: {r['forecast']:.2f}")
