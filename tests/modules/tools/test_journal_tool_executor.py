import json
from unittest.mock import AsyncMock

import pytest

from backend.modules.tools._executors import JournalToolExecutor
from shared.dtos.memory import JournalEntryDto

pytestmark = pytest.mark.asyncio


def _base_args(**overrides) -> dict:
    args = {
        "content": "Chris values the principle of least astonishment.",
        "category": "value",
        "_session_id": "session-1",
        "_persona_id": "persona-1",
        "_persona_name": "Aria",
        "_correlation_id": "corr-1",
    }
    args.update(overrides)
    return args


async def test_happy_path_calls_memory_api_and_returns_entry_id(monkeypatch):
    from datetime import datetime, timezone

    dto = JournalEntryDto(
        id="entry-123",
        persona_id="persona-1",
        content="Chris values the principle of least astonishment.",
        category="value",
        state="uncommitted",
        is_correction=False,
        created_at=datetime.now(timezone.utc),
    )
    write_mock = AsyncMock(return_value=dto)

    import backend.modules.memory as memory_mod
    monkeypatch.setattr(
        memory_mod, "write_persona_authored_entry", write_mock,
    )

    executor = JournalToolExecutor()
    result_str = await executor.execute(
        user_id="user-1",
        tool_name="write_journal_entry",
        arguments=_base_args(),
    )
    result = json.loads(result_str)

    assert result == {"status": "recorded", "entry_id": "entry-123"}
    write_mock.assert_awaited_once_with(
        user_id="user-1",
        persona_id="persona-1",
        persona_name="Aria",
        content="Chris values the principle of least astonishment.",
        category="value",
        source_session_id="session-1",
        correlation_id="corr-1",
    )


@pytest.mark.parametrize(
    "overrides,expected_error_substring",
    [
        ({"content": ""}, "content"),
        ({"content": None}, "content"),
        ({"category": ""}, "category"),
        ({"category": "nonsense"}, "category"),
        ({"content": "x" * 2001}, "2000"),
    ],
)
async def test_validation_errors_do_not_call_memory(
    monkeypatch, overrides, expected_error_substring,
):
    write_mock = AsyncMock()
    import backend.modules.memory as memory_mod
    monkeypatch.setattr(
        memory_mod, "write_persona_authored_entry", write_mock,
    )

    executor = JournalToolExecutor()
    result_str = await executor.execute(
        user_id="user-1",
        tool_name="write_journal_entry",
        arguments=_base_args(**overrides),
    )
    result = json.loads(result_str)

    assert "error" in result
    assert expected_error_substring in result["error"]
    write_mock.assert_not_awaited()


async def test_missing_session_context_is_internal_error(monkeypatch):
    write_mock = AsyncMock()
    import backend.modules.memory as memory_mod
    monkeypatch.setattr(
        memory_mod, "write_persona_authored_entry", write_mock,
    )

    args = _base_args()
    del args["_persona_id"]

    executor = JournalToolExecutor()
    result_str = await executor.execute(
        user_id="user-1",
        tool_name="write_journal_entry",
        arguments=args,
    )
    result = json.loads(result_str)

    assert "internal" in result["error"]
    write_mock.assert_not_awaited()


async def test_memory_api_exception_returns_error_string(monkeypatch):
    write_mock = AsyncMock(side_effect=RuntimeError("db down"))
    import backend.modules.memory as memory_mod
    monkeypatch.setattr(
        memory_mod, "write_persona_authored_entry", write_mock,
    )

    executor = JournalToolExecutor()
    result_str = await executor.execute(
        user_id="user-1",
        tool_name="write_journal_entry",
        arguments=_base_args(),
    )
    result = json.loads(result_str)

    assert "failed to record entry" in result["error"]
