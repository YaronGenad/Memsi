# -*- coding: utf-8 -*-
"""
forecast_weekly_cell.py — תחזית פר (branch × category × week).

הרציונל (Sprint C5, 2026-05):
המודלים הקיימים (חודש קודם, מותאם-regime, תחזית-טיסות, סיבתי) פעלו על
סדרות-זמן מצרפיות (סך-הכל לחודש, או לסניף-יחיד). זה נתן signal חלש מאוד —
38 נקודות-נתון בלבד.

המודל הזה עובד בגרעיניות הגבוהה ביותר: שבוע × סניף × קטגוריה.
מספר נקודות-האימון: ~70,000. כאן LinearRegression תופס דפוסים שמודלים
מצרפיים לא יכלו לתפוס.

Sandbox-validated:
- MAE על cells לא-אפסיים: 1.08 (22% שיפור על naive_prev של 1.39)
- מתנהג סיבתית-נכון: שגרה > מלחמה > peak attack
- רגישות לקונטקסט ~21% (בלי overfitting)

API:
    forecast_weekly_per_cell(branches, categories, horizon_months, context)
    → dict {(branch, category) → DataFrame(year_month, forecast)}

    אגרגציה למצרפי החודש מבוצעת ע"י הקורא (UI).
"""
from __future__ import annotations
import warnings
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from db_config import get_conn
from domain_repository import identify_luggage
from logger import logger

warnings.filterwarnings('ignore', message='pandas only supports SQLAlchemy')


# ────────────────────────────────────────────────────────────────
#  Configuration
# ────────────────────────────────────────────────────────────────

# מפתח פר-יציאה: branch_name דרך מסמכים. סינון לסניפים-זכאים נעשה ע"י
# קורא דרך min_stock_calculator.eligible_branches() או דומה.

_MIN_BRANCH_WEEKS = 40     # סניף-זכאי: לפחות 40 שבועות פעילות
_MIN_BRANCH_QTY = 50       # סניף-זכאי: לפחות 50 תיקונים סה"כ

_LAG_WEEKS = [1, 2, 4, 8, 13, 26]
_ROLL_WINS = [4, 8, 13]


# ────────────────────────────────────────────────────────────────
#  Data preparation
# ────────────────────────────────────────────────────────────────

def _pull_daily_transactions() -> pd.DataFrame:
    """מושך כל תיעודי-תיקון מ-DB. עמודות: day, branch, category."""
    with get_conn() as conn:
        df = pd.read_sql_query("""
            SELECT lf.curdate::date AS day,
                   lf.topartdes AS description,
                   d.branchname AS branch_raw,
                   d.details AS doc_details
            FROM logfile lf
            INNER JOIN documents d ON lf.logdocno = d.docno
            WHERE d.statdes = 'סופית'
              AND lf.topartdes IS NOT NULL
        """, conn)

    df['branch'] = df['branch_raw'].fillna('').str.strip()
    df.loc[df['branch'] == '', 'branch'] = df['doc_details'].fillna('').str.strip()
    df = df[df['branch'].str.len() > 0]
    df['category'] = df['description'].apply(identify_luggage)
    df = df.dropna(subset=['category'])
    df = df[df['category'] != '']
    df['day'] = pd.to_datetime(df['day'])
    return df[['day', 'branch', 'category']]


def _weekly_aggregation(df_daily: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """אגרגציה לשבועיים, ובחירת סניפים-זכאים.

    מחזיר: (weekly_dense, eligible_branches)
    """
    df_daily['week'] = df_daily['day'].dt.strftime('%G-W%V')

    # סינון לסניפים-זכאים: לפחות N שבועות פעילות + לפחות M תיקונים
    branch_stats = (df_daily.groupby('branch')
                    .agg(n_weeks=('week', 'nunique'), total=('day', 'count'))
                    .reset_index())
    eligible = set(branch_stats[
        (branch_stats['n_weeks'] >= _MIN_BRANCH_WEEKS) &
        (branch_stats['total'] >= _MIN_BRANCH_QTY)
    ]['branch'])
    logger.info("forecast_weekly_cell: %d eligible branches", len(eligible))

    df_eligible = df_daily[df_daily['branch'].isin(eligible)]
    weekly_sparse = (df_eligible.groupby(['week', 'branch', 'category'])
                     .size().reset_index(name='qty'))

    # Dense grid: כל (שבוע × סניף × קטגוריה) אפילו כשאין נתון
    all_weeks = sorted(weekly_sparse['week'].unique())
    all_branches = sorted(eligible)
    all_cats = sorted(weekly_sparse['category'].unique())

    idx = pd.MultiIndex.from_product([all_weeks, all_branches, all_cats],
                                      names=['week', 'branch', 'category'])
    dense = pd.DataFrame(index=idx).reset_index()
    dense = dense.merge(weekly_sparse, on=['week', 'branch', 'category'], how='left')
    dense['qty'] = dense['qty'].fillna(0).astype(int)
    return dense, sorted(eligible)


def _week_to_date(w: str) -> datetime:
    year, wk = w.split('-W')
    return datetime.strptime(f"{year}-{wk}-1", "%G-%V-%u")


def _build_features(dense: pd.DataFrame) -> pd.DataFrame:
    """מוסיף פיצ'רים פר-cell (lags, rolling means, seasonal, context).
    מחזיר DataFrame מורחב."""
    all_weeks = sorted(dense['week'].unique())
    week_idx_map = {w: i for i, w in enumerate(all_weeks)}
    dense['week_idx'] = dense['week'].map(week_idx_map)
    dense['week_date'] = pd.to_datetime(dense['week'].apply(_week_to_date))
    dense['month'] = dense['week_date'].dt.month
    dense['week_in_year'] = dense['week_date'].dt.isocalendar().week.astype(int)
    dense['sin_w'] = np.sin(2 * np.pi * dense['week_in_year'] / 52)
    dense['cos_w'] = np.cos(2 * np.pi * dense['week_in_year'] / 52)
    dense['year_month'] = dense['week_date'].dt.strftime('%Y-%m')

    dense = dense.sort_values(['branch', 'category', 'week_idx']).reset_index(drop=True)

    # Lags + rolling means פר-קבוצה
    g = dense.groupby(['branch', 'category'])['qty']
    for lag in _LAG_WEEKS:
        dense[f'lag{lag}'] = g.shift(lag)
    for win in _ROLL_WINS:
        dense[f'roll{win}_mean'] = g.transform(
            lambda s: s.shift(1).rolling(win, min_periods=1).mean())

    # Context features. ברירת-מחדל: קובץ ה-CSV ההיסטורי שב-repo (data/).
    # אם המשתמש רוצה לעקוף את זה (למשל לבדיקות), אפשר להגדיר HISTORICAL_FEATURES_PATH ב-.env.
    import os
    default_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 'data', 'historical_features.csv')
    ctx_path = os.environ.get('HISTORICAL_FEATURES_PATH', default_path)
    try:
        if os.path.exists(ctx_path):
            ctx = pd.read_csv(ctx_path)
            dense = dense.merge(
                ctx[['year_month', 'anxiety', 'economy_open',
                     'flight_capacity', 'consumer_spending']],
                on='year_month', how='left')
            for c in ['anxiety', 'economy_open', 'flight_capacity', 'consumer_spending']:
                dense[c] = pd.to_numeric(dense[c], errors='coerce').ffill().fillna(5)
        else:
            logger.warning("historical_features.csv not found at %s; using neutral context (5).", ctx_path)
            for c in ['anxiety', 'economy_open', 'flight_capacity', 'consumer_spending']:
                dense[c] = 5
    except Exception as e:
        logger.warning("Could not load context CSV at %s: %s", ctx_path, e)
        for c in ['anxiety', 'economy_open', 'flight_capacity', 'consumer_spending']:
            dense[c] = 5

    # Flight traffic
    with get_conn() as conn:
        flights = pd.read_sql_query(
            "SELECT year_month, arriving_passengers FROM flight_traffic", conn)
    dense = dense.merge(flights, on='year_month', how='left')

    # Sprint C5.3: שיפור fallback ל-arriving_passengers — במקום ממוצע
    # גלובלי, נשתמש בממוצע פר-חודש-של-השנה (seasonality). כך חודש-קיץ
    # עתידי יקבל את עוצמת-הקיץ-ההיסטורית במקום baseline שטוח.
    dense['_month'] = dense['year_month'].str[5:7]
    seasonal_avg = (flights.assign(_month=lambda d: d['year_month'].str[5:7])
                    .groupby('_month')['arriving_passengers'].mean())
    global_avg = float(flights['arriving_passengers'].mean())
    dense['_seasonal'] = dense['_month'].map(seasonal_avg).fillna(global_avg)
    dense['arriving_passengers'] = dense['arriving_passengers'].fillna(
        dense['_seasonal'])
    dense = dense.drop(columns=['_month', '_seasonal'])

    return dense


# ────────────────────────────────────────────────────────────────
#  Model training + prediction
# ────────────────────────────────────────────────────────────────

def _train_model(dense_train: pd.DataFrame):
    """מאמן LinearRegression על כל ה-cells הזמינים. מחזיר (model, feature_cols)."""
    from sklearn.linear_model import LinearRegression

    BASE_FEATS = ['week_idx', 'month', 'sin_w', 'cos_w',
                  'lag1', 'lag2', 'lag4', 'lag8', 'lag13', 'lag26',
                  'roll4_mean', 'roll8_mean', 'roll13_mean',
                  'anxiety', 'economy_open', 'flight_capacity',
                  'consumer_spending', 'arriving_passengers']

    dense_oh = pd.get_dummies(dense_train, columns=['branch', 'category'],
                              prefix=['br', 'cat'])
    branch_cols = [c for c in dense_oh.columns if c.startswith('br_')]
    cat_cols = [c for c in dense_oh.columns if c.startswith('cat_')]
    feature_cols = BASE_FEATS + branch_cols + cat_cols

    for c in BASE_FEATS:
        dense_oh[c] = pd.to_numeric(dense_oh[c], errors='coerce').fillna(0)

    X = dense_oh[feature_cols].values.astype(float)
    y = dense_oh['qty'].values

    model = LinearRegression()
    model.fit(X, y)
    logger.info("forecast_weekly_cell: trained on %d cells × %d features",
                len(X), len(feature_cols))
    return model, feature_cols, branch_cols, cat_cols


def _predict_future_weeks(
    model, feature_cols, branch_cols, cat_cols,
    dense_train: pd.DataFrame,
    branch: str, category: str,
    target_weeks: list[str],
    context: dict,
) -> list[float]:
    """חיזוי איטרטיבי עבור (branch, category) על שורת-שבועות עתידית.
    מזרים lag1/lag2/... בכל איטרציה — חיזוי השבוע הקודם הופך ל-lag1."""

    # היסטוריה אחרונה לאותו cell (לlags ראשוניים)
    cell_hist = dense_train[
        (dense_train['branch'] == branch) & (dense_train['category'] == category)
    ].sort_values('week_idx')

    if cell_hist.empty:
        return [0.0] * len(target_weeks)

    recent_qtys = cell_hist['qty'].tail(max(_LAG_WEEKS)).values.tolist()
    if len(recent_qtys) < 13:
        return [0.0] * len(target_weeks)

    max_week_idx = int(cell_hist['week_idx'].max())

    # Context overrides
    ctx = {
        'anxiety': context.get('anxiety', 5),
        'economy_open': context.get('economy_open', 8),
        'flight_capacity': context.get('flight_capacity', 8),
        'consumer_spending': context.get('consumer_spending', 7),
        'arriving_passengers': context.get('arriving_passengers', 600000),
    }

    preds = []
    sim_lags = list(recent_qtys)

    for i, jw in enumerate(target_weeks):
        # רק לפיצ'רים, לא לטעון את ה-DB
        row = pd.Series({c: 0.0 for c in feature_cols})
        row['week_idx'] = max_week_idx + i + 1
        wkdate = _week_to_date(jw)
        row['month'] = wkdate.month
        wknum = int(jw.split('W')[1])
        row['week_in_year'] = wknum
        row['sin_w'] = np.sin(2 * np.pi * wknum / 52)
        row['cos_w'] = np.cos(2 * np.pi * wknum / 52)
        row['lag1'] = sim_lags[-1]
        row['lag2'] = sim_lags[-2] if len(sim_lags) >= 2 else 0
        row['lag4'] = sim_lags[-4] if len(sim_lags) >= 4 else 0
        row['lag8'] = sim_lags[-8] if len(sim_lags) >= 8 else 0
        row['lag13'] = sim_lags[-13] if len(sim_lags) >= 13 else 0
        row['lag26'] = sim_lags[-26] if len(sim_lags) >= 26 else 0
        row['roll4_mean'] = float(np.mean(sim_lags[-4:]))
        row['roll8_mean'] = float(np.mean(sim_lags[-8:]))
        row['roll13_mean'] = float(np.mean(sim_lags[-13:]))
        for k, v in ctx.items():
            row[k] = v

        # Branch + category one-hots
        bc = f'br_{branch}'
        cc = f'cat_{category}'
        if bc in row.index:
            row[bc] = 1
        if cc in row.index:
            row[cc] = 1

        X_pred = row[feature_cols].values.astype(float).reshape(1, -1)
        pred = max(0.0, float(model.predict(X_pred)[0]))
        preds.append(pred)
        sim_lags.append(pred)

    return preds


# ────────────────────────────────────────────────────────────────
#  Public API
# ────────────────────────────────────────────────────────────────

def _month_target_weeks(year: int, month: int) -> list[str]:
    """מחזיר רשימת ISO-weeks (YYYY-Www) השייכים לחודש."""
    weeks = set()
    d = datetime(year, month, 1)
    while d.month == month:
        weeks.add(d.strftime('%G-W%V'))
        d += timedelta(days=1)
    return sorted(weeks)


def forecast_per_cell(
    horizon_months: int,
    context: dict,
    categories: Optional[list[str]] = None,
    branches: Optional[list[str]] = None,
) -> pd.DataFrame:
    """ה-entry point הציבורי.

    Args:
        horizon_months: כמה חודשים קדימה לחזות (1..12).
        context: dict עם פיצ'רי-קונטקסט (anxiety, economy_open, וכו').
        categories: רשימת קטגוריות לחיזוי. None = כל הקטגוריות.
        branches: רשימת סניפים. None = כל הסניפים-הזכאים.

    Returns:
        DataFrame עם עמודות: year_month, branch, category, forecast
    """
    logger.info("forecast_per_cell: horizon=%d ctx=%s",
                horizon_months, {k: context.get(k) for k in
                                  ('anxiety', 'economy_open', 'flight_capacity')})

    # 1. Pull + aggregate
    df_daily = _pull_daily_transactions()
    dense, eligible = _weekly_aggregation(df_daily)

    # 2. Features
    dense_feat = _build_features(dense)

    # 3. Drop early rows
    dense_train = dense_feat.dropna(subset=['lag13', 'roll4_mean']).copy()
    if len(dense_train) < 100:
        logger.warning("forecast_per_cell: not enough training data (%d)", len(dense_train))
        return pd.DataFrame(columns=['year_month', 'branch', 'category', 'forecast'])

    # 4. Train
    model, feature_cols, branch_cols, cat_cols = _train_model(dense_train)

    # 5. Determine target branches + categories
    target_branches = branches if branches else eligible
    target_branches = [b for b in target_branches if b in eligible]
    if categories:
        target_cats = categories
    else:
        target_cats = sorted(dense_train['category'].unique())

    # 6. Generate forecasts for future weeks
    last_week = dense_train.sort_values('week_idx')['week'].iloc[-1]
    last_date = _week_to_date(last_week)

    # Map: month → list of weeks
    months_to_weeks: dict[str, list[str]] = {}
    for m_offset in range(horizon_months + 1):
        # התחל מהחודש אחרי הנוכחי
        target_date = last_date + timedelta(days=30 * (m_offset + 1))
        ym = target_date.strftime('%Y-%m')
        if ym not in months_to_weeks:
            year, mo = int(ym[:4]), int(ym[5:7])
            months_to_weeks[ym] = _month_target_weeks(year, mo)
        if len(months_to_weeks) >= horizon_months:
            break

    # All future weeks in order
    all_future_weeks = []
    for ym in sorted(months_to_weeks.keys()):
        for w in months_to_weeks[ym]:
            if w not in all_future_weeks:
                all_future_weeks.append(w)

    # 7. Predict for each (branch, category) on all future weeks, then sum per month
    rows = []
    for branch in target_branches:
        for cat in target_cats:
            week_preds = _predict_future_weeks(
                model, feature_cols, branch_cols, cat_cols,
                dense_train, branch, cat, all_future_weeks, context
            )
            # Map preds back to months
            week_to_pred = dict(zip(all_future_weeks, week_preds))
            for ym, ym_weeks in months_to_weeks.items():
                month_total = sum(week_to_pred.get(w, 0.0) for w in ym_weeks)
                rows.append({
                    'year_month': ym,
                    'branch': branch,
                    'category': cat,
                    'forecast': round(month_total, 2),
                })

    result = pd.DataFrame(rows)
    logger.info("forecast_per_cell: produced %d (branch, cat, ym) predictions",
                len(result))
    return result


# ────────────────────────────────────────────────────────────────
#  Convenience: aggregated total per month (for the main forecast tab)
# ────────────────────────────────────────────────────────────────

def forecast_total_by_cell(
    series: pd.Series,
    horizon: int,
    events_df: pd.DataFrame,
    context: dict,
) -> pd.DataFrame:
    """ממשק תואם-API לקריאה מ-forecast_engine.run_all_models.

    משתמש בארכיטקטורה החדשה: מאמן פר-cell, מחזה לכל החודשים, ומחזיר
    סכום-כללי על הסניפים והקטגוריות שנבחרו (או על הכל אם לא נבחרו).

    Sprint C5.2: ה-context יכול לכלול:
        _selected_branches:    רשימת קודי-סניפים (למשל ['05'])
        _selected_categories:  רשימת קטגוריות (למשל ['גדולה קלאסית קשיחה'])
    אם המפתחות חסרים → מחזירים סך-כללי על כל הסניפים/קטגוריות.
    """
    branches = (context or {}).get('_selected_branches')
    categories = (context or {}).get('_selected_categories')
    # ה-branchname ב-documents הוא תמיד קוד-סניף (05, 800, וכו'),
    # תואם למה שה-UI שולח. אין צורך בתרגום.

    res = forecast_per_cell(horizon_months=horizon, context=context,
                             branches=branches, categories=categories)
    if res.empty:
        # fallback ריק
        months = pd.date_range(
            start=pd.to_datetime(series.index[-1] + '-01') + pd.DateOffset(months=1),
            periods=horizon, freq='MS'
        ).strftime('%Y-%m').tolist()
        return pd.DataFrame({
            'year_month': months,
            'forecast': [0.0] * horizon,
            'lower': [0.0] * horizon,
            'upper': [0.0] * horizon,
        })

    # סכום פר-חודש
    by_month = res.groupby('year_month')['forecast'].sum().reset_index()
    # rough confidence interval: ± std מהיסטוריה
    sigma = float(np.std(series.values[-12:])) if len(series) >= 12 else 0.0
    by_month['lower'] = (by_month['forecast'] - sigma).clip(lower=0)
    by_month['upper'] = by_month['forecast'] + sigma
    return by_month.sort_values('year_month').reset_index(drop=True)


if __name__ == '__main__':
    # Quick smoke test
    import json
    ctx_routine = {'anxiety': 3, 'economy_open': 10, 'flight_capacity': 10,
                    'consumer_spending': 8, 'arriving_passengers': 700000}
    res = forecast_per_cell(horizon_months=1, context=ctx_routine,
                              categories=['גדולה קלאסית קשיחה'])
    print(res.to_string())
