from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.database import connect_db, disconnect_db, get_db
from backend.modules.user._handlers import router as user_router
from backend.modules.user._repository import UserRepository
from backend.modules.user._audit import AuditRepository


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    db = get_db()
    await UserRepository(db).create_indexes()
    await AuditRepository(db).create_indexes()
    yield
    await disconnect_db()


app = FastAPI(title="Chatsune", version="0.1.0", lifespan=lifespan)
app.include_router(user_router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
