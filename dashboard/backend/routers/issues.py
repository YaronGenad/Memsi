import sys
import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

sys.path.insert(0, '/home/user/Memsi')

try:
    import issue_engine
    _engine_available = True
except Exception:
    _engine_available = False

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class IssueResponse(BaseModel):
    id: int
    issue_date: str
    branch_code: str
    category: str
    issue_type: str
    severity: float
    status: str
    gap: Optional[float]
    min_quantity: Optional[float]
    current_quantity: Optional[float]
    resolution_note: Optional[str]
    predicted: bool
    confidence: Optional[float]
    resolved_at: Optional[str]
    created_at: str


class IssueStatusUpdate(BaseModel):
    status: str
    resolution_note: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_issue(row: dict) -> IssueResponse:
    """Convert a raw dict from issue_engine into an IssueResponse."""

    def _iso(val):
        if val is None:
            return None
        if hasattr(val, 'isoformat'):
            return val.isoformat()
        return str(val)

    return IssueResponse(
        id=row['id'],
        issue_date=_iso(row['issue_date']),
        branch_code=row['branch_code'],
        category=row['category'],
        issue_type=row['issue_type'],
        severity=float(row['severity']) if row.get('severity') is not None else 0.0,
        status=row['status'],
        gap=float(row['gap']) if row.get('gap') is not None else None,
        min_quantity=float(row['min_quantity']) if row.get('min_quantity') is not None else None,
        current_quantity=float(row['current_quantity']) if row.get('current_quantity') is not None else None,
        resolution_note=row.get('resolution_note'),
        predicted=bool(row.get('predicted', False)),
        confidence=float(row['confidence']) if row.get('confidence') is not None else None,
        resolved_at=_iso(row.get('resolved_at')),
        created_at=_iso(row.get('created_at')) or '',
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/issues/dates")
def get_dates_with_issues(days_ahead: int = Query(default=30)):
    """Return dates that have issues within the next N days."""
    if not _engine_available:
        return {"dates": []}
    try:
        dates = issue_engine.get_dates_with_issues(days_ahead)
        return {"dates": dates}
    except Exception:
        return {"dates": []}


@router.get("/issues", response_model=list[IssueResponse])
def list_issues(
    date: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    branch_code: Optional[str] = Query(default=None),
):
    """List issues, optionally filtered by date, status, and branch_code."""
    if not _engine_available:
        return []

    if date is not None:
        try:
            target_date = datetime.date.fromisoformat(date)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid date format: {date!r}")
    else:
        target_date = datetime.date.today()

    try:
        rows = issue_engine.get_issues(
            target_date=target_date,
            status=status,
            branch_code=branch_code,
        )
        return [_serialize_issue(r) for r in rows]
    except Exception:
        return []


@router.get("/issues/{issue_id}", response_model=IssueResponse)
def get_issue(issue_id: int):
    """Return a single issue by id."""
    if not _engine_available:
        raise HTTPException(status_code=503, detail="Issue engine not available")

    try:
        rows = issue_engine.get_issues(target_date=None, status=None, branch_code=None)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    for row in rows:
        if row.get('id') == issue_id:
            return _serialize_issue(row)

    raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")


@router.patch("/issues/{issue_id}/status", response_model=IssueResponse)
def update_issue_status(issue_id: int, body: IssueStatusUpdate):
    """Update the status (and optional resolution note) of an issue."""
    if not _engine_available:
        raise HTTPException(status_code=503, detail="Issue engine not available")

    valid_statuses = {"OPEN", "PENDING", "RESOLVED"}
    if body.status not in valid_statuses:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status {body.status!r}. Must be one of {sorted(valid_statuses)}",
        )

    try:
        updated = issue_engine.update_issue_status(
            issue_id=issue_id,
            status=body.status,
            resolution_note=body.resolution_note,
        )
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if updated is None:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")

    return _serialize_issue(updated)


class AssetAssignment(BaseModel):
    asset_type: str        # 'staff' | 'inventory'
    asset_id: Optional[int] = None   # employee id (for staff)
    branch_code: Optional[str] = None  # source branch (for inventory)
    category: Optional[str] = None   # for inventory
    quantity: Optional[int] = None   # for inventory
    note: Optional[str] = None


@router.post("/issues/{issue_id}/assign", response_model=IssueResponse)
def assign_asset(issue_id: int, assignment: AssetAssignment):
    """
    Records that an asset (staff member or inventory) has been assigned to resolve an issue.
    - Updates issue status to PENDING
    - Appends assignment info to resolution_note
    - Returns updated issue
    """
    if not _engine_available:
        raise HTTPException(status_code=503, detail="Issue engine not available")

    if assignment.asset_type == 'staff':
        formatted_note = f"staff:employee_id={assignment.asset_id}"
    else:
        formatted_note = (
            f"inventory:branch={assignment.branch_code},"
            f"category={assignment.category},"
            f"qty={assignment.quantity}"
        )
    if assignment.note:
        formatted_note += f" | {assignment.note}"

    try:
        updated = issue_engine.update_issue_status(
            issue_id=issue_id,
            status='PENDING',
            resolution_note=formatted_note,
        )
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if updated is None:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")

    return _serialize_issue(updated)


class AssetAssignment(BaseModel):
    asset_type: str        # 'staff' | 'inventory'
    asset_id: Optional[int] = None   # employee id (for staff)
    branch_code: Optional[str] = None  # source branch (for inventory)
    category: Optional[str] = None   # for inventory
    quantity: Optional[int] = None   # for inventory
    note: Optional[str] = None


@router.post("/issues/{issue_id}/assign", response_model=IssueResponse)
def assign_asset(issue_id: int, assignment: AssetAssignment):
    """
    Records that an asset (staff member or inventory) has been assigned to resolve an issue.
    - Updates issue status to PENDING
    - Appends assignment info to resolution_note
    - Returns updated issue
    """
    if not _engine_available:
        raise HTTPException(status_code=503, detail="Issue engine not available")

    if assignment.asset_type == 'staff':
        resolution_note = f"staff:employee_id={assignment.asset_id}"
    else:
        resolution_note = (
            f"inventory:branch={assignment.branch_code},"
            f"category={assignment.category},"
            f"qty={assignment.quantity}"
        )

    if assignment.note:
        resolution_note += f" | {assignment.note}"

    try:
        updated = issue_engine.update_issue_status(
            issue_id=issue_id,
            status='PENDING',
            resolution_note=resolution_note,
        )
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if updated is None:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")

    return _serialize_issue(updated)


@router.post("/issues/refresh")
def refresh_issues(date: Optional[str] = Query(default=None)):
    """Trigger compute_inventory_issues for the given date (default today)."""
    if not _engine_available:
        raise HTTPException(status_code=503, detail="Issue engine not available")

    if date is not None:
        try:
            target_date = datetime.date.fromisoformat(date)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid date format: {date!r}")
    else:
        target_date = datetime.date.today()

    try:
        result = issue_engine.compute_inventory_issues(target_date)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    # result may be a list of dicts or a summary dict — normalise to summary
    if isinstance(result, list):
        return {"created": len(result), "resolved": 0, "updated": 0}
    return result
