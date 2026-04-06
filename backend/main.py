import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.database import connect_db, disconnect_db, get_db, get_redis
from backend.modules.user import router as user_router, init_indexes as user_init_indexes
from backend.modules.llm import router as llm_router, init_indexes as llm_init_indexes
from backend.modules.persona import router as persona_router, init_indexes as persona_init_indexes
from backend.modules.settings import router as settings_router, init_indexes as settings_init_indexes
from backend.modules.chat import router as chat_router, init_indexes as chat_init_indexes, cleanup_stale_empty_sessions
from backend.modules.bookmark import bookmark_router, init_indexes as bookmark_init_indexes
from backend.modules.storage import router as storage_router, init_indexes as storage_init_indexes
from backend.ws.event_bus import EventBus, set_event_bus
from backend.ws.manager import ConnectionManager, set_manager
from backend.ws.router import ws_router, get_background_tasks
from backend.jobs import consumer_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    db = get_db()
    redis = get_redis()
    await user_init_indexes(db)
    await llm_init_indexes(db)
    await persona_init_indexes(db)
    await settings_init_indexes(db)
    await chat_init_indexes(db)
    await bookmark_init_indexes(db)
    await storage_init_indexes(db)
    manager = ConnectionManager()
    set_manager(manager)
    event_bus = EventBus(redis=redis, manager=manager)
    set_event_bus(event_bus)

    # Start background job consumer
    consumer_task = asyncio.create_task(consumer_loop(redis, event_bus))

    # Start periodic Redis Stream trimming (BD-024)
    trim_task = await event_bus.start_periodic_trim()

    # Start periodic cleanup of stale empty chat sessions (every hour)
    async def _session_cleanup_loop() -> None:
        while True:
            await asyncio.sleep(3600)
            try:
                await cleanup_stale_empty_sessions()
            except Exception:
                pass  # Non-critical — retry next cycle

    cleanup_task = asyncio.create_task(_session_cleanup_loop())

    yield

    # Cancel in-flight WebSocket tasks
    ws_tasks = get_background_tasks()
    for task in ws_tasks:
        task.cancel()
    if ws_tasks:
        await asyncio.gather(*ws_tasks, return_exceptions=True)
    ws_tasks.clear()

    # Shut down background tasks
    cleanup_task.cancel()
    consumer_task.cancel()
    trim_task.cancel()
    for task in (cleanup_task, consumer_task, trim_task):
        try:
            await task
        except asyncio.CancelledError:
            pass

    await disconnect_db()


app = FastAPI(title="Chatsune", version="0.1.0", lifespan=lifespan)
app.include_router(user_router)
app.include_router(llm_router)
app.include_router(persona_router)
app.include_router(settings_router)
app.include_router(chat_router)
app.include_router(bookmark_router)
app.include_router(storage_router)
app.include_router(ws_router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
