import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_db():
    db = MagicMock()
    db["chat_sessions"] = AsyncMock()
    db["chat_messages"] = AsyncMock()
    return db


def _make_message(msg_id: str, session_id: str, role: str, content: str, minutes_ago: int = 0):
    return {
        "_id": msg_id,
        "session_id": session_id,
        "role": role,
        "content": content,
        "token_count": len(content),
        "created_at": datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    }


async def test_delete_messages_after(mock_db):
    from backend.modules.chat._repository import ChatRepository

    target_msg = _make_message("msg-3", "sess-1", "user", "target", minutes_ago=5)
    mock_db["chat_messages"].find_one = AsyncMock(return_value=target_msg)
    mock_db["chat_messages"].delete_many = AsyncMock()

    repo = ChatRepository(mock_db)
    result = await repo.delete_messages_after("sess-1", "msg-3")

    assert result is True
    mock_db["chat_messages"].delete_many.assert_awaited_once()
    call_filter = mock_db["chat_messages"].delete_many.call_args[0][0]
    assert call_filter["session_id"] == "sess-1"
    assert "$gt" in str(call_filter["created_at"])


async def test_delete_messages_after_not_found(mock_db):
    from backend.modules.chat._repository import ChatRepository

    mock_db["chat_messages"].find_one = AsyncMock(return_value=None)

    repo = ChatRepository(mock_db)
    result = await repo.delete_messages_after("sess-1", "nonexistent")
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
