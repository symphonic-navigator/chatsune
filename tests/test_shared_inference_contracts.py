from shared.dtos.chat import ChatSessionExtras
from shared.dtos.inference import (
    CompletionMessage,
    CompletionRequest,
    ContentPart,
    ToolDefinition,
)
from shared.dtos.llm import ReasoningCapability, ToolCapability


def _default_reasoning() -> ReasoningCapability:
    return ReasoningCapability(kind="optional")


def _default_tools() -> ToolCapability:
    return ToolCapability(supported=False)


def _default_extras(reasoning_on: bool = False, tools_enabled: bool = False) -> ChatSessionExtras:
    return ChatSessionExtras(
        tools_enabled=tools_enabled,
        reasoning_mode="on" if reasoning_on else "off",
        reasoning_effort=None,
    )


def test_text_content_part():
    part = ContentPart(type="text", text="hello")
    assert part.type == "text"
    assert part.text == "hello"
    assert part.data is None


def test_image_content_part():
    part = ContentPart(type="image", data="base64data", media_type="image/png")
    assert part.type == "image"
    assert part.data == "base64data"


def test_completion_message_user():
    msg = CompletionMessage(
        role="user",
        content=[ContentPart(type="text", text="hi")],
    )
    assert msg.role == "user"
    assert len(msg.content) == 1
    assert msg.tool_calls is None
    assert msg.tool_call_id is None


def test_completion_message_tool():
    msg = CompletionMessage(
        role="tool",
        content=[ContentPart(type="text", text='{"result": 42}')],
        tool_call_id="call_abc",
    )
    assert msg.role == "tool"
    assert msg.tool_call_id == "call_abc"


def test_tool_definition():
    td = ToolDefinition(
        name="web_search",
        description="Search the web",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
    )
    assert td.type == "function"
    assert td.name == "web_search"


def test_completion_request_minimal():
    req = CompletionRequest(
        model="qwen3:32b",
        messages=[
            CompletionMessage(role="user", content=[ContentPart(type="text", text="hi")])
        ],
        reasoning=_default_reasoning(),
        tools_capability=_default_tools(),
        extras=_default_extras(reasoning_on=False),
    )
    assert req.model == "qwen3:32b"
    assert req.temperature is None
    assert req.tools is None
    assert req.extras.reasoning_mode == "off"


def test_completion_request_full():
    req = CompletionRequest(
        model="qwen3:32b",
        messages=[
            CompletionMessage(role="system", content=[ContentPart(type="text", text="You are helpful.")]),
            CompletionMessage(role="user", content=[ContentPart(type="text", text="hi")]),
        ],
        temperature=0.7,
        tools=[
            ToolDefinition(name="search", description="Search", parameters={"type": "object", "properties": {}}),
        ],
        reasoning=_default_reasoning(),
        tools_capability=ToolCapability(supported=True),
        extras=_default_extras(reasoning_on=True, tools_enabled=True),
    )
    assert req.temperature == 0.7
    assert len(req.tools) == 1
    assert req.extras.reasoning_mode == "on"


def test_cache_hint_defaults_to_none():
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(role="user", content=[ContentPart(type="text", text="hi")])],
        reasoning=_default_reasoning(),
        tools_capability=_default_tools(),
        extras=_default_extras(),
    )
    assert req.cache_hint is None


def test_cache_hint_accepts_string():
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(role="user", content=[ContentPart(type="text", text="hi")])],
        cache_hint="sess-abc",
        reasoning=_default_reasoning(),
        tools_capability=_default_tools(),
        extras=_default_extras(),
    )
    assert req.cache_hint == "sess-abc"
