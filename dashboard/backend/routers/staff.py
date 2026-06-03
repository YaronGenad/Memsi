from fastapi import APIRouter

router = APIRouter()


@router.get("/staff/availability")
def get_staff_availability():
    return {"status": "not implemented yet"}
