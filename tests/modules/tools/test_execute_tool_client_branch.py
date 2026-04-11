import json
from unittest.mock import AsyncMock

import pytest

from backend.modules.tools import execute_tool, get_client_dispatcher

pytestmark = pytest.mark.asyncio


async def test_client_side_tool_routes_to_dispatcher(monkeypatch):
    from backend.modules.tools._registry import ToolGroup

    fake_group = ToolGroup(
        id="code_execution",
        display_name="Code Execution",
        description="test",
        side="client",
        toggleable=True,
        tool_names=["calculate_js"],
        definitions=[],
        executor=None,
    )

    import backend.modules.tools._registry as registry_mod
    monkeypatch.setattr(
        registry_mod, "get_groups",
        lambda: {"code_execution": fake_group},
    )
    # also patch the re-export in the tools package
    import backend.modules.tools as tools_mod
    monkeypatch.setattr(tools_mod, "get_groups", registry_mod.get_groups)

    fake_dispatcher = AsyncMock()
    fake_dispatcher.dispatch = AsyncMock(return_value='{"stdout": "ok", "error": null}')
    monkeypatch.setattr(
        tools_mod, "_dispatcher_singleton", fake_dispatcher, raising=False,
    )
    monkeypatch.setattr(
        tools_mod, "get_client_dispatcher", lambda: fake_dispatcher,
    )

    result = await execute_tool(
        user_id="user-a",
        tool_name="calculate_js",
        arguments_json='{"code": "console.log(1)"}',
        tool_call_id="tc-1",
        session_id="sess-1",
        originating_connection_id="conn-1",
    )

    assert result == '{"stdout": "ok", "error": null}'
    fake_dispatcher.dispatch.assert_awaited_once()
    kwargs = fake_dispatcher.dispatch.await_args.kwargs
    assert kwargs["tool_call_id"] == "tc-1"
    assert kwargs["tool_name"] == "calculate_js"
    assert kwargs["arguments"] == {"code": "console.log(1)"}
    assert kwargs["target_connection_id"] == "conn-1"
    assert kwargs["server_timeout_ms"] == 10_000
    assert kwargs["client_timeout_ms"] == 5_000


async def test_server_side_tool_still_uses_executor(monkeypatch):
    # web_search is a server-side tool; its executor must still be called.
    from backend.modules.tools._executors import WebSearchExecutor

    mock_execute = AsyncMock(return_value='[{"title":"hi"}]')
    monkeypatch.setattr(WebSearchExecutor, "execute", mock_execute)

    result = await execute_tool(
        user_id="user-a",
        tool_name="web_search",
        arguments_json='{"query": "hi"}',
        tool_call_id="tc-2",
        session_id="sess-1",
        originating_connection_id="conn-1",
    )

    assert result == '[{"title":"hi"}]'
    mock_execute.assert_awaited_once()
