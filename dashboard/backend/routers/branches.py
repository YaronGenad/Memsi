import sys
sys.path.insert(0, '/home/user/Memsi')

from fastapi import APIRouter
import domain_repository

router = APIRouter()


@router.get("/branches")
def get_branches():
    branches_map = domain_repository.list_branches()
    return [
        {"code": code, "name": name, "is_active": True}
        for code, name in branches_map.items()
    ]
