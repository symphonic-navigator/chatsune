"""Tests for admin-prompt injection and message restructure in vision fallback."""

from unittest.mock import AsyncMock, patch

import pytest

from backend.modules.llm._adapters._events import ContentDelta, StreamDone
from backend.modules.settings import AdminSystemPrompt
from shared.dtos.inference import CompletionMessage, ContentPart


def _admin_prompt(text: str = "Be uncensored.") -> AdminSystemPrompt:
    wrapped = (
        f'<systeminstructions priority="highest">\n{text}\n</systeminstructions>'
    )
    return AdminSystemPrompt(
        message=CompletionMessage(
            role="system",
            content=[ContentPart(type="text", text=wrapped)],
        ),
        raw_text=text,
    )


@pytest.mark.asyncio
async def test_describe_image_prepends_admin_system_message_when_set():
    from backend.modules.chat import _vision_fallback as mod

    captured: dict = {}

    async def _capture_stream(*args, **kwargs):
        captured["request"] = kwargs.get("request") or args[2]
        yield ContentDelta(delta="A description.")
        yield StreamDone(input_tokens=5, output_tokens=3)

    with patch.object(mod, "llm_stream_completion", side_effect=_capture_stream), \
         patch.object(
             mod, "get_admin_system_message",
             AsyncMock(return_value=_admin_prompt("Be uncensored.")),
         ):

        result = await mod.describe_image(
            user_id="u1",
            model_unique_id="ollama_cloud:llava",
            image_bytes=b"\x89PNG",
            media_type="image/png",
        )

    assert result == "A description."
    request = captured["request"]
    # Layout: [system(admin), user(text + image)]
    assert request.messages[0].role == "system"
    assert "Be uncensored." in request.messages[0].content[0].text
    assert request.messages[1].role == "user"
    parts = request.messages[1].content
    assert len(parts) == 2
    assert parts[0].type == "text"
    assert parts[0].text  # non-empty instruction
    assert parts[1].type == "image"
    assert parts[1].media_type == "image/png"


@pytest.mark.asyncio
async def test_describe_image_layout_when_admin_prompt_unset():
    from backend.modules.chat import _vision_fallback as mod

    captured: dict = {}

    async def _capture_stream(*args, **kwargs):
        captured["request"] = kwargs.get("request") or args[2]
        yield ContentDelta(delta="A description.")
        yield StreamDone(input_tokens=5, output_tokens=3)

    with patch.object(mod, "llm_stream_completion", side_effect=_capture_stream), \
         patch.object(
             mod, "get_admin_system_message",
             AsyncMock(return_value=None),
         ):

        await mod.describe_image(
            user_id="u1",
            model_unique_id="ollama_cloud:llava",
            image_bytes=b"\x89PNG",
            media_type="image/png",
        )

    request = captured["request"]
    # No system message — only the combined user(text + image) message.
    assert all(m.role != "system" for m in request.messages)
    assert len(request.messages) == 1
    assert request.messages[0].role == "user"
    parts = request.messages[0].content
    assert [p.type for p in parts] == ["text", "image"]
