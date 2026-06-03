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


@router.get("/inventory/available")
def get_available_inventory(category: str = None, exclude_branch: str = None):
    """
    Returns available stock for a category across all locations.
    'Available' = current_quantity > min_quantity (surplus).
    'Assigned' = also in transit / PENDING issues (predicted=false).
    Marlug = branch_code '800' or '08'.
    """
    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # Detect marlug branch code (try '800' and '08')
                params: list = []
                cat_filter = ""
                excl_filter = ""
                if category:
                    cat_filter = " AND ms.category = %s"
                    params.append(category)
                if exclude_branch:
                    excl_filter = " AND li.warehouse_code != %s"
                    params.append(exclude_branch)

                cur.execute(f"""
                    SELECT
                        li.warehouse_code                          AS branch_code,
                        ms.category                               AS category,
                        CAST(li.quantity AS FLOAT)                AS current_quantity,
                        CAST(ms.min_quantity AS FLOAT)            AS min_quantity,
                        CAST(li.quantity - ms.min_quantity AS FLOAT) AS available_quantity,
                        CASE
                            WHEN li.warehouse_code IN ('800', '08') THEN 'marlug'
                            ELSE 'branch'
                        END                                       AS location_type
                    FROM local_inventory li
                    JOIN min_stock ms
                      ON ms.branch_code = li.warehouse_code
                     AND ms.category    = li.sku
                    WHERE li.quantity > ms.min_quantity
                    {cat_filter}
                    {excl_filter}
                    ORDER BY
                        CASE WHEN li.warehouse_code IN ('800', '08') THEN 0 ELSE 1 END,
                        (li.quantity - ms.min_quantity) DESC
                """, params)
                rows = cur.fetchall()

        # Fetch PENDING assigned issues (predicted=false) to mark as ASSIGNED
        assigned_keys: set = set()
        try:
            with get_conn() as conn2:
                with conn2.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur2:
                    a_params: list = []
                    a_cat = ""
                    if category:
                        a_cat = " AND category = %s"
                        a_params.append(category)
                    cur2.execute(f"""
                        SELECT branch_code, category
                        FROM issues
                        WHERE predicted = false
                          AND status = 'PENDING'
                        {a_cat}
                    """, a_params)
                    for r in cur2.fetchall():
                        assigned_keys.add((r["branch_code"], r["category"]))
        except Exception:
            pass

        result = []
        for r in rows:
            key = (r["branch_code"], r["category"])
            result.append({
                "location_type": r["location_type"],
                "branch_code": r["branch_code"],
                "category": r["category"],
                "current_quantity": int(r["current_quantity"]) if r["current_quantity"] is not None else 0,
                "min_quantity": int(r["min_quantity"]) if r["min_quantity"] is not None else 0,
                "available_quantity": int(r["available_quantity"]) if r["available_quantity"] is not None else 0,
                "status": "ASSIGNED" if key in assigned_keys else "AVAILABLE",
            })
        return result
    except Exception:
        return []
