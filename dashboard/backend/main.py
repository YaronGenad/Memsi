import sys
sys.path.insert(0, '/home/user/Memsi')

from dotenv import load_dotenv
load_dotenv('/home/user/Memsi/.env')

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import branches, inventory, issues, staff
from db_config import get_conn

app = FastAPI(title="Memsi Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(branches.router)
app.include_router(inventory.router)
app.include_router(issues.router)
app.include_router(staff.router)


@app.get("/health")
def health():
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        return {"status": "error", "db": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8765, reload=True)
