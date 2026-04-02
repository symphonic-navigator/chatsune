from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.database import connect_db, disconnect_db, get_db
from backend.modules.user import router as user_router, init_indexes


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    await init_indexes(get_db())
    yield
    await disconnect_db()


app = FastAPI(title="Chatsune", version="0.1.0", lifespan=lifespan)
app.include_router(user_router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
