# -*- coding: utf-8 -*-
"""
Staff availability computation.
Returns AVAILABLE / ASSIGNED / UNAVAILABLE per (employee, date).
"""
import sys
sys.path.insert(0, '/home/user/Memsi')

from datetime import date
import logging
import psycopg2.extras
from db_config import get_conn

logger = logging.getLogger(__name__)


def get_availability(target_date: date = None, branch_code: str = None) -> list[dict]:
    """
    Returns availability for all active employees on target_date.
    Each dict: {id, name, branch_code, roles, shift_type, status, exception_type}

    Status logic:
    - If employee has exception covering target_date → UNAVAILABLE (exception_type filled)
    - If employee has shift on target_date → ASSIGNED
    - If employee is active but no shift → AVAILABLE

    Filter by branch_code if provided.
    """
    if target_date is None:
        target_date = date.today()

    sql = """
        SELECT
            e.id,
            e.name,
            e.branch_code,
            e.roles,
            s.shift_type,
            s.branch_code AS shift_branch,
            ex.exception_type,
            CASE
                WHEN ex.id IS NOT NULL THEN 'UNAVAILABLE'
                WHEN s.id IS NOT NULL  THEN 'ASSIGNED'
                ELSE 'AVAILABLE'
            END AS status
        FROM employees e
        LEFT JOIN shifts s
            ON s.employee_id = e.id
           AND s.shift_date = %(target_date)s
        LEFT JOIN staff_exceptions ex
            ON ex.employee_id = e.id
           AND %(target_date)s BETWEEN ex.from_date AND ex.to_date
        WHERE e.is_active = TRUE
    """
    params: dict = {'target_date': target_date}

    if branch_code:
        sql += " AND e.branch_code = %(branch_code)s"
        params['branch_code'] = branch_code

    sql += " ORDER BY e.branch_code, e.name"

    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
                result = []
                for r in rows:
                    result.append({
                        'id':             r['id'],
                        'name':           r['name'],
                        'branch_code':    r['branch_code'],
                        'roles':          r['roles'],
                        'shift_type':     r['shift_type'],
                        'shift_branch':   r['shift_branch'],
                        'status':         r['status'],
                        'exception_type': r['exception_type'],
                    })
                return result
    except Exception as e:
        logger.error("get_availability failed: %s", e)
        return []


def get_employees(branch_code: str = None, active_only: bool = True) -> list[dict]:
    """Returns employees, optionally filtered by branch."""
    sql = "SELECT id, name, branch_code, roles, is_active, created_at, updated_at FROM employees WHERE 1=1"
    params: list = []

    if active_only:
        sql += " AND is_active = TRUE"
    if branch_code:
        sql += " AND branch_code = %s"
        params.append(branch_code)

    sql += " ORDER BY branch_code, name"

    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error("get_employees failed: %s", e)
        return []


def add_exception(employee_id: int, from_date: date, to_date: date,
                  exception_type: str, notes: str = None) -> dict:
    """Inserts a staff_exception. Returns the created record."""
    valid_types = {'SICK', 'VACATION', 'TRAINING', 'OTHER'}
    if exception_type not in valid_types:
        raise ValueError(f"Invalid exception_type: {exception_type!r}. Must be one of {valid_types}")
    if from_date > to_date:
        raise ValueError(f"from_date ({from_date}) must be <= to_date ({to_date})")

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO staff_exceptions (employee_id, from_date, to_date, exception_type, notes)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
            """, (employee_id, from_date, to_date, exception_type, notes))
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("Failed to insert staff_exception")
            return dict(row)


def remove_exception(exception_id: int) -> bool:
    """Deletes a staff_exception. Returns True if deleted."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM staff_exceptions WHERE id = %s",
                (exception_id,)
            )
            return cur.rowcount > 0


def get_exceptions(employee_id: int = None, from_date: date = None) -> list[dict]:
    """Returns exceptions, optionally filtered."""
    sql = "SELECT * FROM staff_exceptions WHERE 1=1"
    params: list = []

    if employee_id is not None:
        sql += " AND employee_id = %s"
        params.append(employee_id)
    if from_date is not None:
        sql += " AND to_date >= %s"
        params.append(from_date)

    sql += " ORDER BY from_date, employee_id"

    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error("get_exceptions failed: %s", e)
        return []
