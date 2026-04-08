from shared.dtos.inference import (
    CompletionMessage,
    ContentPart,
    CompletionRequest,
)
from backend.modules.llm._adapters._ollama_base import OllamaBaseAdapter


class _Probe(OllamaBaseAdapter):
    provider_id = "probe"
    provider_display_name = "Probe"
    requires_key_for_listing = False

    def _auth_headers(self, api_key):  # noqa: D401
        return {}

    async def validate_key(self, api_key):
        return True


def _make_request(**overrides):
    base = dict(
        model="llama3.2",
        messages=[
            CompletionMessage(
                role="user",
                content=[ContentPart(type="text", text="hi")],
            ),
        ],
        temperature=None,
        tools=None,
        supports_reasoning=False,
        reasoning_enabled=False,
    )
    base.update(overrides)
    return CompletionRequest(**base)


def test_build_chat_payload_minimal():
    payload = _Probe._build_chat_payload(_make_request())
    assert payload["model"] == "llama3.2"
    assert payload["stream"] is True
    assert payload["messages"] == [{"role": "user", "content": "hi"}]
    assert "think" not in payload
    assert "options" not in payload
    assert "tools" not in payload


def test_build_chat_payload_with_thinking_and_temperature():
    payload = _Probe._build_chat_payload(
        _make_request(supports_reasoning=True, reasoning_enabled=True, temperature=0.7),
    )
    assert payload["think"] is True
    assert payload["options"] == {"temperature": 0.7}
