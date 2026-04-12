from datetime import UTC, datetime
from uuid import uuid4

import pytest
from backend.database import connect_db, disconnect_db, get_db
from backend.modules.chat._repository import ChatRepository
from shared.dtos.chat import ArtefactRefDto


@pytest.fixture
async def repo(clean_db):
    await connect_db()
    r = ChatRepository(get_db())
    await r.create_indexes()
    yield r
    await disconnect_db()


async def test_create_session(repo):
    doc = await repo.create_session(user_id="user-1", persona_id="persona-1")
    assert doc["user_id"] == "user-1"
    assert doc["state"] == "idle"
    assert doc["persona_id"] == "persona-1"


async def test_get_session(repo):
    created = await repo.create_session("user-1", "p-1")
    found = await repo.get_session(created["_id"], "user-1")
    assert found is not None
    assert found["_id"] == created["_id"]


async def test_get_session_wrong_user(repo):
    created = await repo.create_session("user-1", "p-1")
    found = await repo.get_session(created["_id"], "other-user")
    assert found is None


async def test_list_sessions_for_user(repo):
    # list_sessions() only returns sessions with at least one message
    # (empty ghost sessions are hidden, like on Claude.ai).
    s1 = await repo.create_session("user-1", "p-1")
    s2 = await repo.create_session("user-1", "p-2")
    s3 = await repo.create_session("user-2", "p-3")
    await repo.save_message(session_id=s1["_id"], role="user", content="hi", token_count=1)
    await repo.save_message(session_id=s2["_id"], role="user", content="hi", token_count=1)
    await repo.save_message(session_id=s3["_id"], role="user", content="hi", token_count=1)
    sessions = await repo.list_sessions("user-1")
    assert len(sessions) == 2


async def test_update_session_state(repo):
    doc = await repo.create_session("user-1", "p-1")
    updated = await repo.update_session_state(doc["_id"], "streaming")
    assert updated["state"] == "streaming"


async def test_save_and_list_messages(repo):
    session = await repo.create_session("user-1", "p-1")
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
    session = await repo.create_session("user-1", "p-1")
    sid = session["_id"]
    await repo.save_message(session_id=sid, role="user", content="hi", token_count=1)
    deleted = await repo.soft_delete_session(sid, "user-1")
    assert deleted is True
    assert await repo.get_session(sid, "user-1") is None


async def test_save_message_with_aborted_status(repo):
    session = await repo.create_session("user-1", "p-1")
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
    session = await repo.create_session("user-1", "p-1")
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


async def test_save_message_persists_new_fields_and_roundtrip(repo):
    doc = await repo.save_message(
        session_id="s1",
        role="assistant",
        content="",
        token_count=0,
        thinking=None,
        usage={"input_tokens": 10, "output_tokens": 5},
        artefact_refs=[{
            "artefact_id": "a1",
            "handle": "h1",
            "title": "Snippet",
            "artefact_type": "code",
            "operation": "create",
        }],
        refusal_text="The model declined this request.",
        status="refused",
    )
    assert doc["status"] == "refused"
    assert doc["refusal_text"] == "The model declined this request."
    assert doc["usage"] == {"input_tokens": 10, "output_tokens": 5}
    assert doc["artefact_refs"][0]["handle"] == "h1"

    # Roundtrip through message_to_dto
    dto = repo.message_to_dto(doc)
    assert dto.status == "refused"
    assert dto.refusal_text == "The model declined this request."
    assert dto.usage == {"input_tokens": 10, "output_tokens": 5}
    assert dto.artefact_refs and dto.artefact_refs[0].handle == "h1"
    assert isinstance(dto.artefact_refs[0], ArtefactRefDto)


async def test_save_message_legacy_document_reads_with_defaults(repo):
    doc = {
        "_id": str(uuid4()),
        "session_id": "s1",
        "role": "assistant",
        "content": "hi",
        "thinking": None,
        "token_count": 1,
        "created_at": datetime.now(UTC),
    }
    dto = repo.message_to_dto(doc)
    assert dto.status == "completed"
    assert dto.refusal_text is None
    assert dto.artefact_refs is None
    assert dto.usage is None


async def test_save_message_empty_artefact_refs_not_written(repo):
    doc = await repo.save_message(
        session_id="s1",
        role="assistant",
        content="ok",
        token_count=1,
        artefact_refs=[],
    )
    assert "artefact_refs" not in doc
