from datetime import UTC, datetime
from uuid import uuid4

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
    # list_sessions() only returns sessions with at least one message
    # (empty ghost sessions are hidden, like on Claude.ai).
    s1 = await repo.create_session("user-1", "p-1", "ollama_cloud:m")
    s2 = await repo.create_session("user-1", "p-2", "ollama_cloud:m")
    s3 = await repo.create_session("user-2", "p-3", "ollama_cloud:m")
    await repo.save_message(session_id=s1["_id"], role="user", content="hi", token_count=1)
    await repo.save_message(session_id=s2["_id"], role="user", content="hi", token_count=1)
    await repo.save_message(session_id=s3["_id"], role="user", content="hi", token_count=1)
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


async def test_soft_delete_session_hides_it(repo):
    # Sessions are soft-deleted: get_session no longer returns them,
    # but messages remain until hard_delete_expired_sessions runs.
    session = await repo.create_session("user-1", "p-1", "ollama_cloud:m")
    sid = session["_id"]
    await repo.save_message(session_id=sid, role="user", content="hi", token_count=1)
    deleted = await repo.soft_delete_session(sid, "user-1")
    assert deleted is True
    assert await repo.get_session(sid, "user-1") is None


async def test_save_message_with_aborted_status(repo):
    session = await repo.create_session("user-1", "p-1", "ollama_cloud:m")
    sid = session["_id"]
    await repo.save_message(
        session_id=sid, role="assistant", content="partial", token_count=1,
        status="aborted",
    )
    msgs = await repo.list_messages(sid)
    assert len(msgs) == 1
    assert msgs[0]["status"] == "aborted"
    dto = repo.message_to_dto(msgs[0])
    assert dto.status == "aborted"


async def test_legacy_message_without_status_defaults_to_completed(repo):
    session = await repo.create_session("user-1", "p-1", "ollama_cloud:m")
    sid = session["_id"]
    # Simulate a legacy document: insert directly into MongoDB without
    # going through save_message, so we bypass the new default kwarg.
    await repo._messages.insert_one({
        "_id": str(uuid4()),
        "session_id": sid,
        "role": "assistant",
        "content": "legacy",
        "thinking": None,
        "token_count": 1,
        "created_at": datetime.now(UTC),
    })
    msgs = await repo.list_messages(sid)
    assert len(msgs) == 1
    # Repo returns raw dicts from MongoDB; DTO conversion must default.
    dto = repo.message_to_dto(msgs[0])
    assert dto.status == "completed"
