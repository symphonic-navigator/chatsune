import json
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.asyncio


async def test_make_tool_executor_injects_persona_context_for_write_journal_entry(
    monkeypatch,
):
    """_make_tool_executor must inject _session_id, _persona_id, _persona_name
    and _correlation_id into the arguments JSON for the write_journal_entry
    tool, so the JournalToolExecutor downstream can dispatch correctly."""
    import backend.modules.chat._orchestrator as orchestrator_mod

    captured: dict = {}

    async def _fake_execute_tool(user_id, tool_name, arguments_json, **kwargs):
        captured["user_id"] = user_id
        captured["tool_name"] = tool_name
        captured["arguments_json"] = arguments_json
        captured["kwargs"] = kwargs
        return "ok"

    monkeypatch.setattr(orchestrator_mod, "execute_tool", _fake_execute_tool)

    session = {"_id": "session-xyz", "knowledge_library_ids": []}
    persona = {"_id": "persona-abc", "name": "Aria", "knowledge_library_ids": []}

    wrapped = orchestrator_mod._make_tool_executor(
        session=session,
        persona=persona,
        correlation_id="corr-42",
        connection_id="conn-1",
    )

    result = await wrapped(
        user_id="user-1",
        tool_name="write_journal_entry",
        arguments_json=json.dumps({
            "content": "Chris values the principle of least astonishment.",
            "category": "value",
        }),
        tool_call_id="tc-1",
    )

    assert result == "ok"
    assert captured["user_id"] == "user-1"
    assert captured["tool_name"] == "write_journal_entry"
    enriched = json.loads(captured["arguments_json"])
    assert enriched["content"] == "Chris values the principle of least astonishment."
    assert enriched["category"] == "value"
    # The four injected dispatch-context keys - contract with JournalToolExecutor
    assert enriched["_session_id"] == "session-xyz"
    assert enriched["_persona_id"] == "persona-abc"
    assert enriched["_persona_name"] == "Aria"
    assert enriched["_correlation_id"] == "corr-42"


async def test_make_tool_executor_handles_missing_persona_for_write_journal_entry(
    monkeypatch,
):
    """When persona is None (defensive branch), injection still happens with
    empty string fallbacks - the JournalToolExecutor will then return
    'internal: missing session context' to the LLM. This locks in the
    contract that the orchestrator does NOT crash when persona is unset."""
    import backend.modules.chat._orchestrator as orchestrator_mod

    captured: dict = {}

    async def _fake_execute_tool(user_id, tool_name, arguments_json, **kwargs):
        captured["arguments_json"] = arguments_json
        return "ok"

    monkeypatch.setattr(orchestrator_mod, "execute_tool", _fake_execute_tool)

    session = {"_id": "session-xyz", "knowledge_library_ids": []}

    wrapped = orchestrator_mod._make_tool_executor(
        session=session,
        persona=None,
        correlation_id="corr-42",
        connection_id=None,
    )

    await wrapped(
        user_id="user-1",
        tool_name="write_journal_entry",
        arguments_json=json.dumps({"content": "x", "category": "value"}),
        tool_call_id="tc-1",
    )

    enriched = json.loads(captured["arguments_json"])
    assert enriched["_session_id"] == "session-xyz"
    assert enriched["_persona_id"] == ""
    assert enriched["_persona_name"] == ""
    assert enriched["_correlation_id"] == "corr-42"
