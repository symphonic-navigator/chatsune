"""Unit tests for chutes_http build_request_body and message translation."""
from __future__ import annotations

from backend.modules.llm._adapters._chutes_http import (
    _translate_message,
    build_request_body,
)
from shared.dtos.chat import ChatSessionExtras
from shared.dtos.inference import (
    CompletionMessage,
    CompletionRequest,
    ContentPart,
    ToolDefinition,
)
from shared.dtos.llm import ReasoningCapability, ToolCapability


def _user_msg(text: str) -> CompletionMessage:
    return CompletionMessage(role="user", content=[ContentPart(type="text", text=text)])


def _request(
    *,
    reasoning: ReasoningCapability | None = None,
    tools: list[ToolDefinition] | None = None,
    extras: ChatSessionExtras | None = None,
    temperature: float | None = None,
) -> CompletionRequest:
    return CompletionRequest(
        model="deepseek-ai/DeepSeek-V3.2-TEE",
        messages=[_user_msg("hi")],
        temperature=temperature,
        tools=tools,
        reasoning=reasoning or ReasoningCapability(kind="no_reasoning"),
        tools_capability=ToolCapability(supported=bool(tools)),
        extras=extras or ChatSessionExtras(
            tools_enabled=False, reasoning_mode="off", reasoning_effort=None,
        ),
    )


def test_minimal_body_has_only_required_keys():
    body = build_request_body(_request())
    assert body["model"] == "deepseek-ai/DeepSeek-V3.2-TEE"
    assert body["stream"] is True
    assert body["stream_options"] == {"include_usage": True}
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert "temperature" not in body
    assert "tools" not in body
    assert "reasoning_effort" not in body


def test_temperature_when_set():
    body = build_request_body(_request(temperature=0.4))
    assert body["temperature"] == 0.4


def test_tools_omitted_when_session_disables_them():
    tool = ToolDefinition(name="t", description="d", parameters={})
    body = build_request_body(_request(
        tools=[tool],
        extras=ChatSessionExtras(
            tools_enabled=False, reasoning_mode="off", reasoning_effort=None,
        ),
    ))
    assert "tools" not in body


def test_tools_present_when_session_enables_them():
    tool = ToolDefinition(name="search", description="search the web", parameters={"type": "object"})
    body = build_request_body(_request(
        tools=[tool],
        extras=ChatSessionExtras(
            tools_enabled=True, reasoning_mode="off", reasoning_effort=None,
        ),
    ))
    assert body["tools"] == [{
        "type": "function",
        "function": {
            "name": "search",
            "description": "search the web",
            "parameters": {"type": "object"},
        },
    }]


def test_reasoning_effort_when_optional_and_on():
    body = build_request_body(_request(
        reasoning=ReasoningCapability(kind="optional"),
        extras=ChatSessionExtras(
            tools_enabled=False, reasoning_mode="on", reasoning_effort="high",
        ),
    ))
    assert body["reasoning_effort"] == "high"


def test_reasoning_effort_omitted_when_optional_and_off():
    body = build_request_body(_request(
        reasoning=ReasoningCapability(kind="optional"),
        extras=ChatSessionExtras(
            tools_enabled=False, reasoning_mode="off", reasoning_effort="high",
        ),
    ))
    assert "reasoning_effort" not in body


def test_reasoning_effort_omitted_when_no_reasoning_kind():
    body = build_request_body(_request(
        reasoning=ReasoningCapability(kind="no_reasoning"),
        extras=ChatSessionExtras(
            tools_enabled=False, reasoning_mode="on", reasoning_effort="high",
        ),
    ))
    assert "reasoning_effort" not in body


def test_image_message_uses_image_url_data_url():
    msg = CompletionMessage(
        role="user",
        content=[
            ContentPart(type="text", text="describe"),
            ContentPart(type="image", media_type="image/png", data="aGVsbG8="),
        ],
    )
    translated = _translate_message(msg)
    assert translated["role"] == "user"
    assert translated["content"] == [
        {"type": "text", "text": "describe"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,aGVsbG8="}},
    ]


def test_text_only_message_uses_plain_string():
    msg = CompletionMessage(role="user", content=[ContentPart(type="text", text="hi")])
    translated = _translate_message(msg)
    assert translated == {"role": "user", "content": "hi"}


def test_tool_call_message_preserves_calls():
    from shared.dtos.inference import ToolCallResult
    msg = CompletionMessage(
        role="assistant",
        content=[ContentPart(type="text", text="")],
        tool_calls=[ToolCallResult(id="c1", name="search", arguments='{"q":"x"}')],
    )
    translated = _translate_message(msg)
    assert translated["tool_calls"] == [{
        "id": "c1",
        "type": "function",
        "function": {"name": "search", "arguments": '{"q":"x"}'},
    }]


def test_tool_result_message_preserves_tool_call_id():
    msg = CompletionMessage(
        role="tool",
        content=[ContentPart(type="text", text='{"result": 42}')],
        tool_call_id="c1",
    )
    translated = _translate_message(msg)
    assert translated["tool_call_id"] == "c1"
