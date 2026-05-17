import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_db():
    db = MagicMock()
    db["chat_sessions"] = AsyncMock()
    db["chat_messages"] = AsyncMock()
    return db


def _make_message(msg_id: str, session_id: str, role: str, content: str, minutes_ago: int = 0, session_seq: int = 1):
    return {
        "_id": msg_id,
        "session_id": session_id,
        "role": role,
        "content": content,
        "token_count": len(content),
        "created_at": datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        "session_seq": session_seq,
    }


async def test_delete_messages_from(mock_db):
    from backend.modules.chat._repository import ChatRepository

    target_msg = _make_message("msg-3", "sess-1", "user", "target", minutes_ago=5, session_seq=3)
    mock_db["chat_messages"].find_one = AsyncMock(return_value=target_msg)
    mock_db["chat_messages"].delete_many = AsyncMock()

    repo = ChatRepository(mock_db)
    result = await repo.delete_messages_from("sess-1", "msg-3")

    assert result is True
    mock_db["chat_messages"].delete_many.assert_awaited_once()
    call_filter = mock_db["chat_messages"].delete_many.call_args[0][0]
    assert call_filter["session_id"] == "sess-1"
    # After the session_seq migration the filter switched from
    # created_at to session_seq with $gte (deletes target + after).
    assert call_filter["session_seq"] == {"$gte": 3}


async def test_delete_messages_from_not_found(mock_db):
    from backend.modules.chat._repository import ChatRepository

    mock_db["chat_messages"].find_one = AsyncMock(return_value=None)

    repo = ChatRepository(mock_db)
    result = await repo.delete_messages_from("sess-1", "nonexistent")
    assert result is False


async def test_update_message_content(mock_db):
    from backend.modules.chat._repository import ChatRepository

    updated_doc = _make_message("msg-3", "sess-1", "user", "edited content")
    mock_db["chat_messages"].update_one = AsyncMock()
    mock_db["chat_messages"].find_one = AsyncMock(return_value=updated_doc)

    repo = ChatRepository(mock_db)
    result = await repo.update_message_content("msg-3", "edited content", 15)

    assert result is not None
    assert result["content"] == "edited content"
    mock_db["chat_messages"].update_one.assert_awaited_once()


async def test_get_last_message(mock_db):
    from backend.modules.chat._repository import ChatRepository

    last_msg = _make_message("msg-10", "sess-1", "assistant", "last reply")

    cursor_mock = MagicMock()
    cursor_mock.sort = MagicMock(return_value=cursor_mock)
    cursor_mock.limit = MagicMock(return_value=cursor_mock)
    cursor_mock.to_list = AsyncMock(return_value=[last_msg])
    mock_db["chat_messages"].find = MagicMock(return_value=cursor_mock)

    repo = ChatRepository(mock_db)
    result = await repo.get_last_message("sess-1")

    assert result is not None
    assert result["_id"] == "msg-10"


async def test_get_last_message_empty_session(mock_db):
    from backend.modules.chat._repository import ChatRepository

    cursor_mock = MagicMock()
    cursor_mock.sort = MagicMock(return_value=cursor_mock)
    cursor_mock.limit = MagicMock(return_value=cursor_mock)
    cursor_mock.to_list = AsyncMock(return_value=[])
    mock_db["chat_messages"].find = MagicMock(return_value=cursor_mock)

    repo = ChatRepository(mock_db)
    result = await repo.get_last_message("sess-1")
    assert result is None


async def test_delete_message(mock_db):
    from backend.modules.chat._repository import ChatRepository

    mock_result = MagicMock()
    mock_result.deleted_count = 1
    mock_db["chat_messages"].delete_one = AsyncMock(return_value=mock_result)

    repo = ChatRepository(mock_db)
    result = await repo.delete_message("msg-5")
    assert result is True


async def test_delete_message_not_found(mock_db):
    from backend.modules.chat._repository import ChatRepository

    mock_result = MagicMock()
    mock_result.deleted_count = 0
    mock_db["chat_messages"].delete_one = AsyncMock(return_value=mock_result)

    repo = ChatRepository(mock_db)
    result = await repo.delete_message("nonexistent")
    assert result is False


async def test_save_message_persists_correlation_id_on_assistant(mock_db):
    """Forward-fix smoke test: assistant writes carry correlation_id.

    Until 2026-05-17 the orchestrator's ``save_fn`` dropped the
    user's correlation_id when persisting the assistant doc. The
    new pair-builder (``select_message_pairs``) keys off
    ``correlation_id`` and skips any doc without one — so without
    this fix the entire prior history would silently fall out of
    the LLM context. See spec
    ``devdocs/specs/2026-05-17-pair-by-correlation-design.md``.
    """
    from backend.modules.chat._repository import ChatRepository

    # ReturnDocument.AFTER on the session counter — return a synthetic
    # session doc so the repo can stamp ``session_seq``.
    mock_db["chat_sessions"].find_one_and_update = AsyncMock(
        return_value={"_id": "sess-1", "last_message_seq": 5},
    )
    mock_db["chat_messages"].insert_one = AsyncMock()

    repo = ChatRepository(mock_db)
    doc = await repo.save_message(
        session_id="sess-1",
        role="assistant",
        content="hello",
        token_count=2,
        correlation_id="cid-fwd-fix",
        user_id="user-1",
    )
    assert doc["correlation_id"] == "cid-fwd-fix"
    assert doc["user_id"] == "user-1"
    assert doc["role"] == "assistant"


async def test_save_message_persists_tool_replay_flag_when_provided(mock_db):
    """Smoke test for the per-turn replay snapshot.

    Spec: devdocs/specs/2026-05-17-replay-tool-history-per-turn-flag-design.md.
    The orchestrator threads ``tool_replay_at_save`` into the assistant
    write so each turn records the policy that was active when it
    began. Omitting the kwarg must leave the field absent on the
    document — legacy callers (and user-message writes) rely on that.
    """
    from backend.modules.chat._repository import ChatRepository

    mock_db["chat_sessions"].find_one_and_update = AsyncMock(
        return_value={"_id": "sess-1", "last_message_seq": 1},
    )
    mock_db["chat_messages"].insert_one = AsyncMock()

    repo = ChatRepository(mock_db)

    # Explicit False — written verbatim.
    doc_off = await repo.save_message(
        session_id="sess-1",
        role="assistant",
        content="off",
        token_count=1,
        correlation_id="cid-off",
        user_id="user-1",
        tool_replay_at_save=False,
    )
    assert doc_off["tool_replay_at_save"] is False

    # Omitted — field stays absent, reader defaults to True via the
    # ``ChatMessageDocument`` Pydantic default.
    doc_default = await repo.save_message(
        session_id="sess-1",
        role="assistant",
        content="default",
        token_count=1,
        correlation_id="cid-default",
        user_id="user-1",
    )
    assert "tool_replay_at_save" not in doc_default

    # User-role writes never carry the field, even if the kwarg is
    # supplied — the flag is only meaningful on assistant docs.
    doc_user = await repo.save_message(
        session_id="sess-1",
        role="user",
        content="hi",
        token_count=1,
        correlation_id="cid-user",
        user_id="user-1",
        tool_replay_at_save=False,
    )
    assert "tool_replay_at_save" not in doc_user
