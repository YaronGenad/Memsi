# -*- coding: utf-8 -*-
"""
Imports staff work schedules from Excel files sent by branch managers.
Flexible parser that handles common Hebrew schedule formats.
"""
import sys
sys.path.insert(0, '/home/user/Memsi')

import pandas as pd
from datetime import date, datetime
import logging
from db_config import get_conn

logger = logging.getLogger(__name__)

# ── Shift code mappings ──────────────────────────────────────────────────────

_MORNING_CODES = {'ב', 'בוקר', 'morning', 'm', 'b'}
_EVENING_CODES = {'ע', 'ערב', 'evening', 'e'}
_FULL_CODES    = {'מ', 'מלא', 'full', 'f'}
_OFF_CODES     = {'ח', 'חופש', 'off', '-', '', 'x', 'חה'}


def _parse_shift_code(cell_value) -> str:
    """Maps Hebrew/common codes to shift_type values.

    'ב', 'בוקר', 'morning', 'M' → 'morning'
    'ע', 'ערב', 'evening', 'E'  → 'evening'
    'מ', 'מלא', 'full', 'F'     → 'full'
    anything else (empty, '-', 'ח', 'חופש') → 'off'
    """
    if cell_value is None or (isinstance(cell_value, float) and pd.isna(cell_value)):
        return 'off'
    normalized = str(cell_value).strip().lower()
    if normalized in _MORNING_CODES:
        return 'morning'
    if normalized in _EVENING_CODES:
        return 'evening'
    if normalized in _FULL_CODES:
        return 'full'
    return 'off'


# ── Date detection helpers ───────────────────────────────────────────────────

def _try_parse_date(value) -> date | None:
    """Try to parse a value as a date. Returns date or None."""
    if isinstance(value, (datetime,)):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d/%m/%y', '%d.%m.%Y', '%d.%m.%y',
                '%Y/%m/%d', '%m/%d/%Y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _find_date_columns(df: pd.DataFrame) -> list[tuple[int, date]]:
    """
    Scans the header row (columns) for date-like values.
    Returns list of (col_index, date) for columns that look like dates.
    """
    date_cols = []
    for i, col in enumerate(df.columns):
        parsed = _try_parse_date(col)
        if parsed is not None:
            date_cols.append((i, parsed))
    return date_cols


def _find_name_column(df: pd.DataFrame, date_col_indices: set[int]) -> int:
    """Returns the index of the first non-date column (employee name column)."""
    for i in range(len(df.columns)):
        if i not in date_col_indices:
            return i
    return 0


# ── Employee lookup / auto-create ─────────────────────────────────────────────

def _get_or_create_employee(conn, name: str, branch_code: str,
                             cache: dict) -> tuple[int, bool]:
    """
    Returns (employee_id, was_created).
    cache is a dict of {name_lower: id} to avoid repeated DB hits.
    """
    key = name.strip().lower()
    if key in cache:
        return cache[key], False

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM employees WHERE LOWER(name) = %s AND branch_code = %s",
            (key, branch_code)
        )
        row = cur.fetchone()
        if row:
            cache[key] = row[0]
            return row[0], False

        # Auto-create
        cur.execute(
            """INSERT INTO employees (name, branch_code, roles, is_active)
               VALUES (%s, %s, '{}', TRUE) RETURNING id""",
            (name.strip(), branch_code)
        )
        new_id = cur.fetchone()[0]
        cache[key] = new_id
        return new_id, True


# ── Public API ────────────────────────────────────────────────────────────────

def import_schedule(file_path: str, branch_code: str) -> dict:
    """
    Parses an Excel file and imports shifts into the DB.

    Expected Excel format (flexible):
    - First column: employee name (TEXT)
    - Remaining columns: dates (as column headers, various formats)
    - Cell values: shift codes like 'ב' (morning/בוקר), 'ע' (evening/ערב),
                   'מ' (full/מלא), 'ח' (off/חופש), '-' or empty (off)

    Strategy:
    1. Read the file with pandas
    2. Find the row/column that contains dates (look for date-like headers)
    3. Map employee names to employees table (by name match, case-insensitive)
    4. Insert/upsert shifts for each (employee, date) cell
    5. Unknown employees: auto-create with branch_code and empty roles

    Returns: {imported: N, skipped: N, created_employees: N, errors: [str]}
    """
    result = {'imported': 0, 'skipped': 0, 'created_employees': 0, 'errors': []}

    # ── 1. Read file ──────────────────────────────────────────────────────────
    try:
        df = pd.read_excel(file_path, header=0)
    except Exception as e:
        result['errors'].append(f"Failed to read Excel file: {e}")
        logger.error("import_schedule: could not read %s: %s", file_path, e)
        return result

    if df.empty:
        result['errors'].append("Excel file is empty")
        return result

    # ── 2. Identify date columns ──────────────────────────────────────────────
    date_cols = _find_date_columns(df)
    if not date_cols:
        result['errors'].append(
            "No date columns found in header row. "
            "Expected dates as column headers (e.g. 2026-06-01 or 01/06/2026)."
        )
        return result

    date_col_indices = {i for i, _ in date_cols}
    name_col_idx = _find_name_column(df, date_col_indices)

    logger.info(
        "import_schedule: %s — found %d date columns, name column index=%d",
        file_path, len(date_cols), name_col_idx
    )

    # ── 3–5. Iterate rows, upsert shifts ─────────────────────────────────────
    employee_cache: dict[str, int] = {}

    try:
        with get_conn() as conn:
            for row_idx, row in df.iterrows():
                # Get employee name
                raw_name = row.iloc[name_col_idx]
                if raw_name is None or (isinstance(raw_name, float) and pd.isna(raw_name)):
                    result['skipped'] += 1
                    continue
                name = str(raw_name).strip()
                if not name:
                    result['skipped'] += 1
                    continue

                try:
                    emp_id, was_created = _get_or_create_employee(
                        conn, name, branch_code, employee_cache
                    )
                    if was_created:
                        result['created_employees'] += 1
                        logger.info("import_schedule: created employee %r in branch %s", name, branch_code)
                except Exception as e:
                    msg = f"Row {row_idx}: could not get/create employee {name!r}: {e}"
                    result['errors'].append(msg)
                    logger.warning("import_schedule: %s", msg)
                    result['skipped'] += 1
                    continue

                # Process each date column
                for col_idx, shift_date in date_cols:
                    cell = row.iloc[col_idx]
                    shift_type = _parse_shift_code(cell)

                    try:
                        with conn.cursor() as cur:
                            cur.execute("""
                                INSERT INTO shifts
                                    (employee_id, shift_date, shift_type, branch_code, source)
                                VALUES (%s, %s, %s, %s, 'excel')
                                ON CONFLICT (employee_id, shift_date, branch_code)
                                DO UPDATE SET
                                    shift_type = EXCLUDED.shift_type,
                                    source     = 'excel'
                            """, (emp_id, shift_date, shift_type, branch_code))
                        result['imported'] += 1
                    except Exception as e:
                        msg = f"Row {row_idx}, date {shift_date}: insert failed: {e}"
                        result['errors'].append(msg)
                        logger.warning("import_schedule: %s", msg)
                        result['skipped'] += 1

    except Exception as e:
        result['errors'].append(f"DB error during import: {e}")
        logger.error("import_schedule: DB error: %s", e)

    logger.info(
        "import_schedule: done — imported=%d skipped=%d created_employees=%d errors=%d",
        result['imported'], result['skipped'], result['created_employees'], len(result['errors'])
    )
    return result
