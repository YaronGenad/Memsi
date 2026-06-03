from fastapi import APIRouter

router = APIRouter()


@router.get("/issues")
def get_issues():
    return {"status": "not implemented yet"}
