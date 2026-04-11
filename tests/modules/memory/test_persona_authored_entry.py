import pytest
import pytest_asyncio

from backend.database import connect_db, disconnect_db, get_db, get_redis
from backend.modules.memory import (
    MemoryRepository,
    write_persona_authored_entry,
)
from backend.ws.event_bus import EventBus, set_event_bus
from backend.ws.manager import ConnectionManager, set_manager
from shared.topics import Topics

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def wired_bus(clean_db):
    await connect_db()
    manager = ConnectionManager()
    set_manager(manager)
    bus = EventBus(redis=get_redis(), manager=manager)
    set_event_bus(bus)
    try:
        yield bus
    finally:
        await disconnect_db()


async def test_write_persona_authored_entry_persists_and_publishes(wired_bus):
    captured: list[dict] = []
    wired_bus.subscribe(
        Topics.MEMORY_ENTRY_AUTHORED_BY_PERSONA,
        lambda payload: captured.append(payload),
    )

    dto = await write_persona_authored_entry(
        user_id="user-1",
        persona_id="persona-1",
        persona_name="Aria",
        content="Chris values the principle of least astonishment.",
        category="value",
        source_session_id="session-1",
        correlation_id="corr-1",
    )

    # DTO is correctly shaped
    assert dto.persona_id == "persona-1"
    assert dto.content == "Chris values the principle of least astonishment."
    assert dto.category == "value"
    assert dto.state == "uncommitted"
    assert dto.is_correction is False
    assert dto.auto_committed is False

    # Entry actually exists in Mongo with state "uncommitted"
    repo = MemoryRepository(get_db())
    entries = await repo.list_journal_entries(
        "user-1", "persona-1", state="uncommitted",
    )
    assert len(entries) == 1
    assert entries[0]["content"] == (
        "Chris values the principle of least astonishment."
    )
    assert entries[0]["source_session_id"] == "session-1"

    # Event was published with persona_name and entry DTO
    assert len(captured) == 1
    payload = captured[0]
    assert payload["persona_name"] == "Aria"
    assert payload["correlation_id"] == "corr-1"
    assert payload["entry"]["id"] == dto.id
    assert payload["entry"]["content"] == dto.content
    assert payload["entry"]["state"] == "uncommitted"
