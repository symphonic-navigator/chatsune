from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.database import connect_db, disconnect_db, get_db, get_redis
from backend.modules.user import router as user_router, init_indexes
from backend.ws.event_bus import EventBus, set_event_bus
from backend.ws.manager import ConnectionManager, set_manager
from backend.ws.router import ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    await init_indexes(get_db())
    manager = ConnectionManager()
    set_manager(manager)
    set_event_bus(EventBus(redis=get_redis(), manager=manager))
    yield
    await disconnect_db()


app = FastAPI(title="Chatsune", version="0.1.0", lifespan=lifespan)
app.include_router(user_router)
app.include_router(ws_router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
