import sys
sys.path.insert(0, '/home/user/Memsi')

from fastapi import APIRouter
from decimal import Decimal
import psycopg2.extras
from db_config import get_conn

router = APIRouter()


def _serialize(v):
    if isinstance(v, Decimal):
        return float(v)
    return v


@router.get("/inventory/current")
def get_current_inventory():
    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        warehouse_code AS branch_code,
                        sku             AS category,
                        quantity,
                        last_calculated AS last_updated
                    FROM local_inventory
                    ORDER BY warehouse_code, sku
                """)
                rows = cur.fetchall()
        return [
            {
                "branch_code": r["branch_code"],
                "category": r["category"],
                "quantity": _serialize(r["quantity"]),
                "last_updated": r["last_updated"].isoformat() if r["last_updated"] else None,
            }
            for r in rows
        ]
    except Exception:
        return []


@router.get("/inventory/min-stock")
def get_min_stock():
    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        branch_code,
                        category,
                        min_quantity
                    FROM min_stock
                    ORDER BY branch_code, category
                """)
                rows = cur.fetchall()
        return [
            {
                "branch_code": r["branch_code"],
                "category": r["category"],
                "min_quantity": _serialize(r["min_quantity"]),
            }
            for r in rows
        ]
    except Exception:
        return []


@router.get("/forecast/shortfalls")
def get_forecast_shortfalls(from_date: str = None, to_date: str = None):
    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                params = []
                date_filter = ""
                if from_date:
                    date_filter += " AND fp.year_month >= %s"
                    params.append(from_date[:7])
                if to_date:
                    date_filter += " AND fp.year_month <= %s"
                    params.append(to_date[:7])

                cur.execute(f"""
                    SELECT
                        fp.branch        AS branch_code,
                        fp.cell          AS category,
                        fp.year_month    AS date,
                        fp.forecast      AS predicted_quantity,
                        ms.min_quantity,
                        (ms.min_quantity - fp.forecast) AS gap
                    FROM forecast_predictions fp
                    JOIN forecast_runs fr ON fr.run_id = fp.run_id
                    JOIN min_stock ms
                      ON ms.branch_code = fp.branch
                     AND ms.category    = fp.cell
                    WHERE fr.run_id = (
                        SELECT MAX(run_id) FROM forecast_runs
                    )
                      AND fp.model = 'avg'
                      AND ms.min_quantity > fp.forecast
                    {date_filter}
                    ORDER BY gap DESC
                """, params)
                rows = cur.fetchall()
        return [
            {
                "branch_code": r["branch_code"],
                "category": r["category"],
                "date": r["date"],
                "predicted_quantity": _serialize(r["predicted_quantity"]),
                "min_quantity": _serialize(r["min_quantity"]),
                "gap": _serialize(r["gap"]),
            }
            for r in rows
        ]
    except Exception:
        return []
