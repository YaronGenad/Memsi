# -*- coding: utf-8 -*-
"""
per_branch_forecast.py — Per-branch hybrid forecasting prototype.

Sprint C8.2 (research, no v-bump):
  The per-cell forecast for May 2026 was 921 vs actual 396 (2.33×). Per-cell
  models train on ~30 months and try to learn BOTH the 2024 summer surge
  (~2000-2500/month) AND the post-Oct-2024 regime (~700/month) as a single
  curve. That conflation is what produces over-prediction.

  This script implements the user-proposed hybrid:
    seasonal shape  = learned from ALL history, as normalized ratios
                       (each month-of-year vs centered rolling-12 mean)
    base level      = learned ONLY from last 18 months (post-Oct-2024)
                       via recency-weighted mean of deseasonalized values
    forecast[ym]    = base × seasonal[month_of(ym)]

  This is run per-branch (13 active branches), then summed and compared
  to the May 2026 actual. The retrospective answers: does per-branch
  hybrid beat per-cell (921), and does it land near actual (396)?

Outputs (all gitignored):
  research/output/per_branch_forecast_table.csv
  research/output/branch_vs_actual_may.png
  research/output/per_branch_history_vs_forecast.png
  research/output/seasonal_shapes.png
  RESEARCH_PER_BRANCH_FINDINGS.md
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make repo modules importable when launched from research/
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


# ---------- Configuration ----------
POST_BREAK_START = '2024-11'   # baseline trains from here
MIN_HIST_MONTHS = 18           # branch needs at least this much history
TARGET_MONTH = '2026-05'       # retrospective target
RECENT_BASE_WEIGHTS = np.array([0.2, 0.3, 0.5])  # exp-decay on last 3 months

# Where the actual May 2026 data lives
ACTUAL_MAY_FILE = _REPO_ROOT / 'combined_output.xlsx'

OUT_DIR = _REPO_ROOT / 'research' / 'output'
OUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT_PATH = _REPO_ROOT / 'RESEARCH_PER_BRANCH_FINDINGS.md'


# ---------- Helpers ----------
def df_to_md(df: pd.DataFrame, index: bool = True) -> str:
    """Render df as a markdown table without requiring `tabulate`."""
    cols = list(df.columns)
    if index:
        cols = [df.index.name or 'index'] + cols
    header = '| ' + ' | '.join(str(c) for c in cols) + ' |'
    sep = '|' + '|'.join(['---'] * len(cols)) + '|'
    rows = []
    for idx, row in df.iterrows():
        cells = []
        if index:
            cells.append(str(idx))
        for c in df.columns:
            v = row[c]
            if isinstance(v, float):
                if pd.isna(v):
                    cells.append('')
                else:
                    cells.append(f"{v:g}")
            elif pd.isna(v):
                cells.append('')
            else:
                cells.append(str(v))
        rows.append('| ' + ' | '.join(cells) + ' |')
    return '\n'.join([header, sep] + rows)


def compute_seasonal_shape(series: pd.Series) -> dict[int, float]:
    """Per month-of-year, the ratio of value to centered rolling-12 mean.
    Normalized so the average across 12 months = 1.0.

    Captures "August is X% above the moving average" without making any
    assumption about absolute levels — so a 2024 spike whose level is 3×
    normal still contributes the SAME shape signal as a normal August.
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
    """Deseasonalize the post-break window and take a recency-weighted
    mean of the last 3 months. Falls back to simple recent mean if
    too few post-break months."""
    post = series[series.index >= post_break_start]
    if len(post) == 0:
        return float(series.iloc[-3:].mean())
    months = pd.to_datetime(post.index + '-01').month
    deseason = post.values.astype(float) / np.array(
        [max(seasonal[m], 0.1) for m in months]
    )
    if len(deseason) >= 3:
        return float(np.dot(deseason[-3:], RECENT_BASE_WEIGHTS))
    return float(np.mean(deseason))


def forecast_one_month(series: pd.Series, target_ym: str) -> dict:
    """Return {base_level, seasonal_index, forecast} for one target month."""
    seasonal = compute_seasonal_shape(series)
    base = compute_base_level(series, POST_BREAK_START, seasonal)
    target_m = int(target_ym.split('-')[1])
    seasonal_at = seasonal[target_m]
    return {
        'base_level': base,
        'seasonal_index': seasonal_at,
        'forecast': base * seasonal_at,
        'seasonal_full': seasonal,   # for plotting
    }


# ---------- Data loading ----------
def load_train_history() -> pd.DataFrame:
    """Pull forecast_history, drop the target month if it leaked in."""
    from forecast_db import ForecastDB
    fdb = ForecastDB()
    df = fdb.get_history()
    df['year_month'] = df['year_month'].astype(str)
    return df[df['year_month'] < TARGET_MONTH].copy()


def load_may_actuals_per_branch() -> pd.DataFrame:
    """Read May 2026 actuals from combined_output.xlsx, aggregate per branch."""
    if not ACTUAL_MAY_FILE.exists():
        return pd.DataFrame(columns=['branch', 'actual_may'])
    xl = pd.ExcelFile(ACTUAL_MAY_FILE)
    # Last sheet is "פירוט מאוחד" (unified detail) per fetch_combined
    actuals = pd.read_excel(ACTUAL_MAY_FILE, sheet_name=xl.sheet_names[-1])
    from domain_repository import identify_luggage
    actuals['category'] = actuals['תיאור מוצר'].fillna('').apply(identify_luggage)
    lug = actuals[actuals['category'].notna() & (actuals['category'] != '')].copy()

    def normalize_branch(v):
        """Branch values from Excel come as floats (7.0). forecast_history
        stores them as zero-padded strings ('07'). We try both forms and
        let the merge below match whichever exists in the forecast set."""
        try:
            n = int(float(v))
            # Return BOTH possible forms; the merge will use the actual hist key
            return f'{n:02d}' if n < 100 else str(n)
        except (ValueError, TypeError):
            return str(v).strip()

    lug['branch'] = lug['סניף'].apply(normalize_branch)
    return lug.groupby('branch').size().reset_index(name='actual_may')


# ---------- Plots ----------
def plot_branch_vs_actual(df: pd.DataFrame, out: Path):
    """Side-by-side bars: forecast vs actual per branch, sorted by actual."""
    d = df.sort_values('actual_may', ascending=False).copy()
    x = np.arange(len(d))
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.bar(x - 0.2, d['forecast_may'], width=0.4, label='Forecast (hybrid)',
           color='steelblue')
    ax.bar(x + 0.2, d['actual_may'], width=0.4, label='Actual May 2026',
           color='orange')
    ax.set_xticks(x)
    ax.set_xticklabels(d['branch'].astype(str), rotation=45, ha='right')
    ax.set_ylabel('Repairs')
    ax.set_title('Per-branch forecast vs actual — May 2026 retrospective')
    ax.legend()
    ax.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    plt.savefig(out, dpi=120)
    plt.close()


def plot_history_vs_forecast(hist: pd.DataFrame, branches: list[str],
                              forecast_per_branch: dict[str, float],
                              out: Path):
    """Per-branch time series with the forecast point overlaid."""
    n = len(branches)
    cols = 3
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(15, 3 * rows), sharex=False)
    axes = np.atleast_2d(axes).ravel()
    for i, b in enumerate(branches):
        s = hist[hist['branch'] == b].groupby('year_month')['quantity'].sum().sort_index()
        ax = axes[i]
        ax.plot(s.index, s.values, '-o', markersize=3, alpha=0.7, color='steelblue')
        # Forecast point
        fcst = forecast_per_branch.get(b)
        if fcst is not None:
            ax.scatter([TARGET_MONTH], [fcst], color='red', s=80, zorder=5,
                       label=f'Forecast={fcst:.0f}')
            ax.axvline(POST_BREAK_START, color='gray', linestyle='--', alpha=0.5,
                       label='post-break start')
        ax.set_title(f'Branch {b}', fontsize=10)
        ax.tick_params(axis='x', rotation=45, labelsize=7)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=7)
    # Hide unused subplots
    for j in range(n, len(axes)):
        axes[j].axis('off')
    plt.suptitle('Per-branch history with May 2026 forecast (red)', y=1.0)
    plt.tight_layout()
    plt.savefig(out, dpi=120, bbox_inches='tight')
    plt.close()


def plot_seasonal_shapes(seasonal_per_branch: dict[str, dict], out: Path):
    """All branches' seasonal shapes overlaid + median."""
    fig, ax = plt.subplots(figsize=(10, 5))
    months = list(range(1, 13))
    ratios_matrix = []
    for b, seasonal in seasonal_per_branch.items():
        y = [seasonal[m] for m in months]
        ax.plot(months, y, alpha=0.4, label=b)
        ratios_matrix.append(y)
    median_seasonal = np.median(np.array(ratios_matrix), axis=0)
    ax.plot(months, median_seasonal, color='black', linewidth=2.5,
            label='MEDIAN across branches', linestyle='--')
    ax.axhline(1.0, color='gray', alpha=0.5, linewidth=0.8)
    ax.set_xticks(months)
    ax.set_xticklabels(['Jan','Feb','Mar','Apr','May','Jun',
                        'Jul','Aug','Sep','Oct','Nov','Dec'])
    ax.set_ylabel('Seasonal index (1.0 = annual avg)')
    ax.set_title('Seasonal shape per branch — derived from ALL history (normalized)')
    ax.legend(fontsize=8, ncol=2, loc='upper right')
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(out, dpi=120)
    plt.close()


# ---------- Main ----------
def main():
    print('== Sprint C8.2: per-branch hybrid forecast ==')

    hist = load_train_history()
    print(f'Loaded {len(hist)} rows of forecast_history (before {TARGET_MONTH}).')

    # Qualified branches
    months_per = hist.groupby('branch')['year_month'].nunique()
    qualified = months_per[months_per >= MIN_HIST_MONTHS].index.tolist()
    # Order by total volume for sanity
    totals = hist.groupby('branch')['quantity'].sum()
    qualified = sorted(qualified, key=lambda b: -totals.get(b, 0))
    print(f'Qualified branches ({len(qualified)}): {qualified}')

    # Forecast per branch
    rows = []
    seasonal_per_branch = {}
    forecast_per_branch = {}
    for b in qualified:
        s = hist[hist['branch'] == b].groupby('year_month')['quantity'].sum().sort_index()
        res = forecast_one_month(s, TARGET_MONTH)
        seasonal_per_branch[b] = res['seasonal_full']
        forecast_per_branch[b] = res['forecast']
        rows.append({
            'branch': b,
            'n_months': len(s),
            'last_actual_apr': float(s.iloc[-1]) if len(s) else 0,
            'base_level': round(res['base_level'], 1),
            'seasonal_may': round(res['seasonal_index'], 3),
            'forecast_may': round(res['forecast'], 1),
        })
    df = pd.DataFrame(rows)

    # Merge actual May
    actuals_may = load_may_actuals_per_branch()
    df = df.merge(actuals_may, on='branch', how='left')
    df['actual_may'] = df['actual_may'].fillna(0).astype(int)
    df['error'] = df['actual_may'] - df['forecast_may']
    df['abs_error'] = df['error'].abs()

    sum_forecast = df['forecast_may'].sum()
    sum_actual = df['actual_may'].sum()
    print(f'\nSUM forecast (qualified branches): {sum_forecast:.0f}')
    print(f'SUM actual (same branches):        {sum_actual}')

    # Also note: actuals include long-tail branches not in qualified
    total_may_actual_anywhere = int(actuals_may['actual_may'].sum())
    long_tail_actual = total_may_actual_anywhere - sum_actual
    print(f'Long-tail (branches not in qualified): {long_tail_actual} repairs')
    print(f'OVERALL actual May (all branches): {total_may_actual_anywhere}')

    # Save outputs
    df.to_csv(OUT_DIR / 'per_branch_forecast_table.csv', index=False)
    plot_branch_vs_actual(df, OUT_DIR / 'branch_vs_actual_may.png')
    plot_history_vs_forecast(hist, qualified, forecast_per_branch,
                              OUT_DIR / 'per_branch_history_vs_forecast.png')
    plot_seasonal_shapes(seasonal_per_branch, OUT_DIR / 'seasonal_shapes.png')

    # Report
    write_report(df, qualified, sum_forecast, sum_actual,
                 total_may_actual_anywhere, long_tail_actual)
    print(f'\nReport: {REPORT_PATH}')
    print(f'Plots:  {OUT_DIR}')


def write_report(df: pd.DataFrame, qualified: list[str],
                 sum_forecast: float, sum_actual: int,
                 total_may_actual_anywhere: int,
                 long_tail_actual: int):
    PER_CELL_PRODUCTION_FORECAST = 921   # known from C8.1 context
    PER_CELL_PRODUCTION_ACTUAL = 396     # actual May totals (all branches)

    # Verdict
    abs_total_gap = abs(sum_forecast - sum_actual)
    if abs_total_gap < 100:
        verdict = (f"**SUCCESS** — sum gap = {abs_total_gap:.0f} (target <100). "
                   f"Recommend C8.3 production refactor.")
        traffic = "🟢"
    elif abs_total_gap < 200:
        verdict = (f"**PROMISING** — sum gap = {abs_total_gap:.0f} (target <100). "
                   f"Worth tuning before production. See ideas below.")
        traffic = "🟡"
    else:
        verdict = (f"**INSUFFICIENT** — sum gap = {abs_total_gap:.0f} (target <100). "
                   f"Approach doesn't work as-is. Alternatives needed.")
        traffic = "🔴"

    # Per-branch verdict counts
    big_misses = int((df['abs_error'] > df['actual_may'] * 0.5).sum())
    n_branches = len(df)

    lines = [
        "# Sprint C8.2 — Per-Branch Hybrid Forecast Findings",
        "",
        "**Generated**: from `research/per_branch_forecast.py`. Not in git.",
        "",
        "## TL;DR",
        "",
        f"- **Branches forecast**: {n_branches} (qualified with ≥{MIN_HIST_MONTHS} months of history)",
        f"- **SUM forecast May**:  {sum_forecast:.0f}",
        f"- **SUM actual May (same branches)**: {sum_actual}",
        f"- **Long-tail (branches not modeled)**: {long_tail_actual} repairs",
        f"- **OVERALL actual May (all branches)**: {total_may_actual_anywhere}",
        f"- **Per-cell production forecast (baseline)**: {PER_CELL_PRODUCTION_FORECAST}",
        f"- **Verdict**: {traffic} {verdict}",
        "",
        "## Per-branch results",
        "",
        df_to_md(df.sort_values('actual_may', ascending=False).round(1),
                  index=False),
        "",
        f"Branches with >50% error: {big_misses} / {n_branches}",
        "",
        "## Comparison vs other models",
        "",
        "| Model | May 2026 forecast | Gap vs actual ({}) |".format(PER_CELL_PRODUCTION_ACTUAL),
        "|---|---|---|",
        f"| Per-cell production (current) | {PER_CELL_PRODUCTION_FORECAST} | +{PER_CELL_PRODUCTION_FORECAST - PER_CELL_PRODUCTION_ACTUAL} ({(PER_CELL_PRODUCTION_FORECAST / PER_CELL_PRODUCTION_ACTUAL - 1) * 100:+.0f}%) |",
        f"| Per-branch hybrid (this sprint) | {sum_forecast:.0f} | {sum_forecast - sum_actual:+.0f} (qualified-only base) |",
        "",
        "## Method recap",
        "",
        f"For each branch with ≥{MIN_HIST_MONTHS} months of data:",
        "",
        "1. **Seasonal shape** from ALL history — for each month-of-year, the ratio",
        "   of value to centered rolling-12 mean. Normalized so 12-month avg = 1.0.",
        "   Captures \"August is 1.3× annual avg\" without inheriting summer 2024's",
        "   absolute level.",
        f"2. **Base level** from post-break window ({POST_BREAK_START}→) only.",
        "   Deseasonalize each month and take recency-weighted mean of last 3",
        "   (weights [0.2, 0.3, 0.5]).",
        "3. **Forecast** = base × seasonal[target_month].",
        "",
        "## Plots",
        "",
        "- `research/output/branch_vs_actual_may.png` — bar chart of forecast vs actual per branch",
        "- `research/output/per_branch_history_vs_forecast.png` — time-series per branch with May forecast",
        "- `research/output/seasonal_shapes.png` — all branches' seasonal indices overlaid",
        "- `research/output/per_branch_forecast_table.csv` — full machine-readable table",
        "",
        "## Recommendation for Sprint C8.3",
        "",
    ]

    if abs_total_gap < 100:
        lines.extend([
            "### Build per-branch hybrid into production",
            "",
            "Create `forecast_per_branch.py` (or extend `forecast_engine.py`)",
            "with the same three-step method. Replace per-cell aggregation with",
            "per-branch forecasts. Add category disaggregation as a final step",
            "(use last 6 months' category proportions per branch).",
            "",
            "Suggested implementation order:",
            "1. Port `compute_seasonal_shape` and `compute_base_level` from",
            "   this research script to a new module `forecast_per_branch.py`.",
            "2. Add `forecast_total_by_branch(branches, horizon, context) -> DataFrame`",
            "   matching the API of `forecast_total_by_cell`.",
            "3. Add disaggregation: `_split_to_categories(branch_total, branch)`",
            "   using `historical_proportions(branch, lookback=6)`.",
            "4. Wire into `forecast_engine.run_all_models` as a new model entry,",
            "   or replace the existing weekly_cell model entirely if this is",
            "   the new preferred path.",
            "5. Add to `_MODEL_FNS` in `forecast_evaluation.py` so backtest tracks it.",
            "",
        ])
    elif abs_total_gap < 200:
        lines.extend([
            "### Tune before production",
            "",
            "The hybrid is close to actual but not yet within ±100 of the target.",
            "Levers to try (in order of likely impact):",
            "",
            "1. **Blend two base levels**. Currently base = recency-weighted last",
            "   3 months only. The war recovery (Mar-Apr 2026 were 39 and 41 at",
            "   branch 800) may be dragging the base too low. Try:",
            "   ```",
            "   base = 0.6 × recency_weighted_last_3 + 0.4 × median_of_last_12",
            "   ```",
            "   This adds memory of pre-war level so a 2-month dip doesn't reset",
            "   the base.",
            "",
            "2. **Trim seasonal outliers**. The current `compute_seasonal_shape`",
            "   uses simple mean of ratios per month. The 2024 summer surge may",
            "   pollute Aug/Sep ratios. Use median or trimmed mean instead.",
            "",
            "3. **Floor at last-3-month minimum**. If forecast < min(last_3),",
            "   cap at min(last_3). Prevents over-pessimism.",
            "",
        ])
    else:
        lines.extend([
            "### Approach doesn't work as-is",
            "",
            "Possible causes:",
            "",
            "1. The post-Oct-2024 \"new normal\" is itself non-stationary (war",
            "   recovery is ongoing). 18-month base isn't a stable target.",
            "2. Long-tail branches (not in qualified set) contribute meaningful",
            "   May volume that this method ignores entirely.",
            "3. The seasonal shape derived from ALL history is contaminated by",
            "   the surge year.",
            "",
            "Alternative candidates for C8.3:",
            "- **Per-branch state-space model** (Kalman filter / exponential",
            "  smoothing with level and seasonal components, separated by",
            "  regime indicator)",
            "- **Cluster-pooled forecast** (from C8.1) — train one model per",
            "  cluster with branch_id as feature",
            "- **Manual override layer** — accept that the model is noisy and",
            "  give users a UI to adjust forecasts per branch",
            "",
        ])

    lines.extend([
        "## Long-tail caveat",
        "",
        f"This method only forecasts {n_branches} branches with ≥{MIN_HIST_MONTHS}",
        f"months of history. May 2026 had {long_tail_actual} additional repairs",
        "from long-tail branches (newer or smaller branches without enough data).",
        "These would need separate treatment in production:",
        "- Pool all long-tail into a single \"OTHER\" forecast,",
        "- Use a simple last-N-month rolling mean for each,",
        "- Or accept that they're unforecastable individually and report a",
        "  per-region or per-cluster total.",
        "",
        "## Caveats",
        "",
        f"- **18-month post-break window is small**. {n_branches} × 18 = a few",
        "  hundred observations for level estimation. Recency-weighted-3 is",
        "  appropriate here (no ML model that needs more data).",
        f"- **Seasonal shape uses {len(qualified) and 'all 36-ish'} months including",
        "  the 2024 surge**. The normalization (ratio vs rolling-12) damps the",
        "  surge but doesn't eliminate it. Inspect `seasonal_shapes.png` —",
        "  if Aug/Sep are abnormally high, consider switching to median ratios.",
        "- **War as continuous regime is not handled here**. Mar-Apr 2026 were",
        "  war-trough months and they ARE in the base window. This pulls the",
        "  base down, which may explain under-prediction at some branches.",
        "  A future iteration could exclude war-tagged months from the base.",
        "- **Disaggregation to categories was deferred**. This script only",
        "  forecasts branch totals. Production refactor needs to add proportion-",
        "  based category splitting.",
        "",
    ])

    with REPORT_PATH.open('w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


if __name__ == '__main__':
    main()
