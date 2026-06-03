from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
import tempfile
import os

router = APIRouter()

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class Employee(BaseModel):
    id: int
    name: str
    branch_code: str
    roles: list[str]
    is_active: bool


class StaffAvailability(BaseModel):
    id: int
    name: str
    branch_code: str
    roles: list[str]
    shift_type: str | None
    status: str           # AVAILABLE | ASSIGNED | UNAVAILABLE
    exception_type: str | None


class ExceptionCreate(BaseModel):
    employee_id: int
    from_date: str        # ISO date
    to_date: str          # ISO date
    exception_type: str   # SICK | VACATION | TRAINING | OTHER
    notes: str | None = None


class ImportResult(BaseModel):
    imported: int
    skipped: int
    created_employees: int
    errors: list[str]


# ---------------------------------------------------------------------------
# Guarded imports
# ---------------------------------------------------------------------------

try:
    from staff_availability import (
        get_availability as _get_availability,
        get_employees as _get_employees,
        add_exception as _add_exception,
        remove_exception as _remove_exception,
    )
    _availability_available = True
except ImportError:
    _availability_available = False

try:
    from staff_excel_importer import import_schedule as _import_schedule
    _importer_available = True
except ImportError:
    _importer_available = False


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/staff/availability", response_model=list[StaffAvailability])
def get_staff_availability(date: str = "", branch_code: str = ""):
    if not _availability_available:
        return []
    rows = _get_availability(target_date=date, branch_code=branch_code)
    return rows


@router.get("/staff/employees", response_model=list[Employee])
def get_employees(branch_code: str = "", active_only: bool = True):
    if not _availability_available:
        return []
    rows = _get_employees(branch_code=branch_code, active_only=active_only)
    return rows


@router.post("/staff/exceptions")
def create_exception(body: ExceptionCreate):
    if not _availability_available:
        raise HTTPException(status_code=503, detail="staff_availability module not available")
    result = _add_exception(
        employee_id=body.employee_id,
        from_date=body.from_date,
        to_date=body.to_date,
        exception_type=body.exception_type,
        notes=body.notes,
    )
    return result


@router.delete("/staff/exceptions/{exception_id}")
def delete_exception(exception_id: int):
    if not _availability_available:
        raise HTTPException(status_code=503, detail="staff_availability module not available")
    success = _remove_exception(exception_id=exception_id)
    if not success:
        raise HTTPException(status_code=404, detail="Exception not found")
    return {"deleted": True}


@router.post("/staff/import-excel", response_model=ImportResult)
async def import_excel(branch_code: str, file: UploadFile = File(...)):
    if not _importer_available:
        return ImportResult(
            imported=0,
            skipped=0,
            created_employees=0,
            errors=["staff_excel_importer module not available"],
        )

    suffix = os.path.splitext(file.filename or "upload.xlsx")[1] or ".xlsx"
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    try:
        contents = await file.read()
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(contents)
        result = _import_schedule(file_path=tmp_path, branch_code=branch_code)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    return ImportResult(**result) if isinstance(result, dict) else result
