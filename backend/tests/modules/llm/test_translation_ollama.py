from shared.dtos.inference import CompletionRequest, CompletionMessage, ContentPart
from shared.dtos.chat import ChatSessionExtras
from shared.dtos.llm import ReasoningCapability, ToolCapability
from backend.modules.llm._adapters._ollama_http import build_request_body


def _user(text: str) -> CompletionMessage:
    return CompletionMessage(role="user", content=[ContentPart(type="text", text=text)])


def _req(extras, reasoning):
    return CompletionRequest(
        model="llama3.3:70b",
        messages=[_user("hi")],
        reasoning=reasoning,
        tools_capability=ToolCapability(supported=True),
        extras=extras,
    )


def test_ollama_no_reasoning_model_omits_thinking_field():
    req = _req(
        ChatSessionExtras(tools_enabled=True, reasoning_mode="off", reasoning_effort=None),
        ReasoningCapability(kind="no_reasoning"),
    )
    body = build_request_body(req)
    assert "think" not in body


def test_ollama_optional_reasoning_on_sets_think_true():
    req = _req(
        ChatSessionExtras(tools_enabled=True, reasoning_mode="on", reasoning_effort=None),
        ReasoningCapability(kind="optional"),
    )
    body = build_request_body(req)
    assert body.get("think") is True


def test_ollama_optional_reasoning_off_sets_think_false_explicitly():
    req = _req(
        ChatSessionExtras(tools_enabled=True, reasoning_mode="off", reasoning_effort=None),
        ReasoningCapability(kind="optional"),
    )
    body = build_request_body(req)
    assert body.get("think") is False  # always-explicit rule
