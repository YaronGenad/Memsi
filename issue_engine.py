# -*- coding: utf-8 -*-
# issue_engine.py
# Computes inventory shortage issues by comparing current stock vs min_stock.
# Called by nightly_sync and on-demand via FastAPI.

import sys
sys.path.insert(0, '/home/user/Memsi')

import math
import logging
from datetime import date, timedelta

import psycopg2.extras

from db_config import get_conn

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────
#  Internal helpers
# ────────────────────────────────────────────────

def _get_category_weights() -> dict[str, float]:
    """Returns {category: weight} from category_priority table. Default 5.0."""
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT category, weight FROM category_priority")
            return {row[0]: float(row[1]) for row in cur.fetchall()}
    except Exception as e:
        logger.warning("Could not load category_priority: %s", e)
        return {}


def _compute_severity(gap: float, min_quantity: float, category: str,
                      weights: dict[str, float]) -> float:
    """Rule-based severity: gap/min * 10, multiplied by category weight ratio, capped 1–10."""
    if not min_quantity or min_quantity <= 0:
        return 5.0
    base = min(abs(gap) / min_quantity * 10.0, 10.0)
    weight = weights.get(category, 5.0)
    severity = base * (weight / 5.0)
    return round(max(1.0, min(10.0, severity)), 1)


def _get_min_stock_data() -> list[dict]:
    """
    Returns list of {branch, category, current_stock, recommended_min, gap} dicts.
    First tries the min_stock DB table, falls back to computing via min_stock_calculator.
    """
    # Try min_stock table first
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT branch_code, category, current_quantity, min_quantity,
                       (current_quantity - min_quantity) AS gap
                FROM min_stock
            """)
            rows = cur.fetchall()
            if rows:
                return [
                    {
                        'branch': r[0],
                        'category': r[1],
                        'current_stock': float(r[2]) if r[2] is not None else 0.0,
                        'recommended_min': float(r[3]) if r[3] is not None else 0.0,
                        'gap': float(r[4]) if r[4] is not None else 0.0,
                    }
                    for r in rows
                ]
    except Exception:
        pass  # table doesn't exist, fall through

    # Fall back to calculator
    try:
        from min_stock_calculator import compute_min_stock
        df = compute_min_stock()
        if df is None or df.empty:
            return []
        return [
            {
                'branch': row['branch'],
                'category': row['category'],
                'current_stock': float(row['current_stock']),
                'recommended_min': float(row['recommended_min']),
                'gap': float(row['gap']),
            }
            for _, row in df.iterrows()
        ]
    except Exception as e:
        logger.warning("Could not compute min_stock: %s", e)
        return []


# ────────────────────────────────────────────────
#  Public API
# ────────────────────────────────────────────────

def compute_inventory_issues(target_date: date = None) -> list[dict]:
    """
    For each (branch, category): if current_stock < min_stock → upsert OPEN issue.
    If gap closed → resolve existing issue.
    Returns list of issues created/updated.
    """
    if target_date is None:
        target_date = date.today()

    stock_data = _get_min_stock_data()
    if not stock_data:
        logger.warning("compute_inventory_issues: no stock data available")
        return []

    weights = _get_category_weights()
    results = []

    try:
        with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            for row in stock_data:
                branch = row['branch']
                category = row['category']
                current = row['current_stock']
                min_qty = row['recommended_min']
                gap = row['gap']  # current - min; negative = shortage

                if current < min_qty:
                    # Shortage: upsert OPEN issue
                    shortage_gap = gap  # negative value
                    severity = _compute_severity(shortage_gap, min_qty, category, weights)

                    cur.execute("""
                        INSERT INTO issues
                            (issue_date, branch_code, category, issue_type,
                             severity, status, gap, min_quantity, current_quantity,
                             predicted, updated_at)
                        VALUES (%s, %s, %s, 'INVENTORY_SHORTAGE',
                                %s, 'OPEN', %s, %s, %s,
                                FALSE, NOW())
                        ON CONFLICT (issue_date, branch_code, category, issue_type)
                        WHERE status != 'RESOLVED'
                        DO UPDATE SET
                            severity         = EXCLUDED.severity,
                            gap              = EXCLUDED.gap,
                            min_quantity     = EXCLUDED.min_quantity,
                            current_quantity = EXCLUDED.current_quantity,
                            updated_at       = NOW()
                        RETURNING *
                    """, (target_date, branch, category, severity,
                          shortage_gap, min_qty, current))
                    issue_row = cur.fetchone()
                    if issue_row:
                        results.append(dict(issue_row))
                else:
                    # Gap closed: resolve any OPEN issues for this (branch, category)
                    cur.execute("""
                        UPDATE issues
                           SET status      = 'RESOLVED',
                               resolved_at = NOW(),
                               updated_at  = NOW()
                         WHERE branch_code = %s
                           AND category    = %s
                           AND issue_type  = 'INVENTORY_SHORTAGE'
                           AND status      = 'OPEN'
                        RETURNING *
                    """, (branch, category))
                    for resolved in cur.fetchall():
                        results.append(dict(resolved))

    except Exception as e:
        logger.error("compute_inventory_issues failed: %s", e)
        raise

    logger.info("compute_inventory_issues: processed %d rows for %s", len(results), target_date)
    return results


def compute_forecast_issues(from_date: date, to_date: date) -> list[dict]:
    """
    Uses forecast_predictions + min_stock to find future shortfalls.
    Creates predicted=True issues for future dates.
    Returns list of issues created/updated.
    """
    weights = _get_category_weights()
    results = []

    try:
        # Get the latest forecast run with per-branch/cell predictions
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT fp.branch, fp.cell AS category, fp.year_month,
                       fp.forecast, fp.lower
                FROM forecast_predictions fp
                INNER JOIN forecast_runs fr ON fp.run_id = fr.run_id
                WHERE fp.branch IS NOT NULL
                  AND fp.cell IS NOT NULL
                  AND fr.run_id = (
                      SELECT MAX(run_id) FROM forecast_runs
                  )
                ORDER BY fp.branch, fp.cell, fp.year_month
            """)
            predictions = cur.fetchall()
    except Exception as e:
        logger.warning("compute_forecast_issues: could not load forecast_predictions: %s", e)
        return []

    if not predictions:
        logger.info("compute_forecast_issues: no per-branch forecasts available")
        return []

    # Build min_stock lookup: {(branch, category): min_qty}
    stock_data = _get_min_stock_data()
    min_lookup: dict[tuple[str, str], float] = {
        (r['branch'], r['category']): r['recommended_min']
        for r in stock_data
    }

    try:
        with get_conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            for branch, category, year_month, forecast_qty, lower in predictions:
                if not branch or not category:
                    continue

                # Convert year_month (e.g. '2026-07') to a representative date
                try:
                    pred_date = date.fromisoformat(year_month + '-01')
                except ValueError:
                    continue

                if not (from_date <= pred_date <= to_date):
                    continue

                min_qty = min_lookup.get((branch, category), 0.0)
                if min_qty <= 0:
                    continue

                forecast_val = float(forecast_qty) if forecast_qty is not None else 0.0
                lower_val = float(lower) if lower is not None else forecast_val

                # Confidence: how likely lower bound still meets min_stock
                # Simple proxy: if even lower bound < min_qty → high concern
                if lower_val < min_qty:
                    gap = lower_val - min_qty
                    confidence = round(max(0.0, min(1.0, forecast_val / min_qty)), 2)
                    severity = _compute_severity(gap, min_qty, category, weights)

                    cur.execute("""
                        INSERT INTO issues
                            (issue_date, branch_code, category, issue_type,
                             severity, status, gap, min_quantity, current_quantity,
                             predicted, confidence, updated_at)
                        VALUES (%s, %s, %s, 'INVENTORY_SHORTAGE',
                                %s, 'OPEN', %s, %s, %s,
                                TRUE, %s, NOW())
                        ON CONFLICT (issue_date, branch_code, category, issue_type)
                        WHERE status != 'RESOLVED'
                        DO UPDATE SET
                            severity         = EXCLUDED.severity,
                            gap              = EXCLUDED.gap,
                            min_quantity     = EXCLUDED.min_quantity,
                            current_quantity = EXCLUDED.current_quantity,
                            confidence       = EXCLUDED.confidence,
                            predicted        = TRUE,
                            updated_at       = NOW()
                        RETURNING *
                    """, (pred_date, branch, category, severity,
                          gap, min_qty, forecast_val, confidence))
                    issue_row = cur.fetchone()
                    if issue_row:
                        results.append(dict(issue_row))

    except Exception as e:
        logger.error("compute_forecast_issues failed: %s", e)
        raise

    logger.info("compute_forecast_issues: created/updated %d predicted issues", len(results))
    return results


def get_issues(target_date: date = None, status: str = None,
               branch_code: str = None) -> list[dict]:
    """
    Returns issues for a given date (default: today).
    Optionally filter by status and/or branch_code.
    """
    if target_date is None:
        target_date = date.today()

    sql = "SELECT * FROM issues WHERE issue_date = %s"
    params: list = [target_date]

    if status:
        sql += " AND status = %s"
        params.append(status)
    if branch_code:
        sql += " AND branch_code = %s"
        params.append(branch_code)

    sql += " ORDER BY severity DESC, branch_code, category"

    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error("get_issues failed: %s", e)
        return []


def update_issue_status(issue_id: int, status: str,
                        resolution_note: str = None) -> dict:
    """
    Updates issue status. Returns updated issue dict.
    """
    valid_statuses = {'OPEN', 'PENDING', 'RESOLVED'}
    if status not in valid_statuses:
        raise ValueError(f"Invalid status: {status!r}. Must be one of {valid_statuses}")

    resolved_at_expr = "NOW()" if status == 'RESOLVED' else "NULL"

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"""
                UPDATE issues
                   SET status          = %s,
                       resolution_note = COALESCE(%s, resolution_note),
                       resolved_at     = CASE WHEN %s = 'RESOLVED' THEN NOW()
                                              ELSE resolved_at END,
                       updated_at      = NOW()
                 WHERE id = %s
                RETURNING *
            """, (status, resolution_note, status, issue_id))
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"Issue id={issue_id} not found")
            return dict(row)


def get_dates_with_issues(days_ahead: int = 30) -> list[str]:
    """
    Returns list of ISO date strings (today through today+days_ahead) that have
    open/pending issues. Used by frontend to mark calendar dots.
    """
    today = date.today()
    end_date = today + timedelta(days=days_ahead)

    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT issue_date
                FROM issues
                WHERE issue_date BETWEEN %s AND %s
                  AND status IN ('OPEN', 'PENDING')
                ORDER BY issue_date
            """, (today, end_date))
            return [row[0].isoformat() for row in cur.fetchall()]
    except Exception as e:
        logger.error("get_dates_with_issues failed: %s", e)
        return []


def run_full_refresh(target_date: date = None):
    """
    Entry point for nightly_sync: runs compute_inventory_issues + compute_forecast_issues.
    """
    if target_date is None:
        target_date = date.today()

    logger.info("run_full_refresh: starting for %s", target_date)

    inventory_issues = compute_inventory_issues(target_date)
    logger.info("run_full_refresh: inventory issues=%d", len(inventory_issues))

    forecast_from = target_date + timedelta(days=1)
    forecast_to = target_date + timedelta(days=90)
    try:
        forecast_issues = compute_forecast_issues(forecast_from, forecast_to)
        logger.info("run_full_refresh: forecast issues=%d", len(forecast_issues))
    except Exception as e:
        logger.warning("run_full_refresh: forecast issues skipped: %s", e)
        forecast_issues = []

    total = len(inventory_issues) + len(forecast_issues)
    logger.info("run_full_refresh: done. total issues=%d", total)
    return inventory_issues + forecast_issues
