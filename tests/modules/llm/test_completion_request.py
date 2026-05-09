from shared.dtos.chat import ChatSessionExtras
from shared.dtos.inference import CompletionMessage, CompletionRequest, ContentPart
from shared.dtos.llm import ReasoningCapability, ToolCapability


def _user(text: str) -> CompletionMessage:
    return CompletionMessage(role="user", content=[ContentPart(type="text", text=text)])


def test_completion_request_carries_extras_and_capability():
    req = CompletionRequest(
        model="x:y",
        messages=[_user("hi")],
        extras=ChatSessionExtras(
            tools_enabled=True, reasoning_mode="on", reasoning_effort="medium"
        ),
        reasoning=ReasoningCapability(kind="optional"),
        tools_capability=ToolCapability(supported=True),
    )
    assert req.extras.reasoning_mode == "on"
    assert req.reasoning.kind == "optional"


def test_completion_request_default_extras_off_no_tools():
    req = CompletionRequest(
        model="x:y",
        messages=[_user("hi")],
        reasoning=ReasoningCapability(kind="no_reasoning"),
        tools_capability=ToolCapability(supported=False),
    )
    # Default extras: tools off, reasoning off
    assert req.extras.tools_enabled is False
    assert req.extras.reasoning_mode == "off"
