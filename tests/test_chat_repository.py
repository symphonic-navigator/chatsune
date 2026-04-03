import pytest
from backend.database import connect_db, disconnect_db, get_db
from backend.modules.chat._repository import ChatRepository


@pytest.fixture
async def repo(clean_db):
    await connect_db()
    r = ChatRepository(get_db())
    await r.create_indexes()
    yield r
    await disconnect_db()


async def test_create_session(repo):
    doc = await repo.create_session(user_id="user-1", persona_id="persona-1", model_unique_id="ollama_cloud:qwen3:32b")
    assert doc["user_id"] == "user-1"
    assert doc["state"] == "idle"
    assert doc["persona_id"] == "persona-1"
    assert doc["model_unique_id"] == "ollama_cloud:qwen3:32b"


async def test_get_session(repo):
    created = await repo.create_session("user-1", "p-1", "ollama_cloud:m")
    found = await repo.get_session(created["_id"], "user-1")
    assert found is not None
    assert found["_id"] == created["_id"]


async def test_get_session_wrong_user(repo):
    created = await repo.create_session("user-1", "p-1", "ollama_cloud:m")
    found = await repo.get_session(created["_id"], "other-user")
    assert found is None


async def test_list_sessions_for_user(repo):
    await repo.create_session("user-1", "p-1", "ollama_cloud:m")
    await repo.create_session("user-1", "p-2", "ollama_cloud:m")
    await repo.create_session("user-2", "p-3", "ollama_cloud:m")
    sessions = await repo.list_sessions("user-1")
    assert len(sessions) == 2


async def test_update_session_state(repo):
    doc = await repo.create_session("user-1", "p-1", "ollama_cloud:m")
    updated = await repo.update_session_state(doc["_id"], "streaming")
    assert updated["state"] == "streaming"


async def test_save_and_list_messages(repo):
    session = await repo.create_session("user-1", "p-1", "ollama_cloud:m")
    sid = session["_id"]
    await repo.save_message(session_id=sid, role="user", content="Hello!", token_count=3)
    await repo.save_message(session_id=sid, role="assistant", content="Hi there!", thinking="Let me respond naturally.", token_count=5)
    messages = await repo.list_messages(sid)
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["thinking"] is None
    assert messages[1]["role"] == "assistant"
    assert messages[1]["thinking"] == "Let me respond naturally."


async def test_delete_session_cascades_messages(repo):
    session = await repo.create_session("user-1", "p-1", "ollama_cloud:m")
    sid = session["_id"]
    await repo.save_message(session_id=sid, role="user", content="hi", token_count=1)
    deleted = await repo.delete_session(sid, "user-1")
    assert deleted is True
    messages = await repo.list_messages(sid)
    assert len(messages) == 0
