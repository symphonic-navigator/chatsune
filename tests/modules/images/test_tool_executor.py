"""Tests for ImageGenerationToolExecutor."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.modules.images._tool_executor import ImageGenerationToolExecutor
from backend.modules.images._service import ImageGenerationOutcome
from shared.dtos.images import ImageRefDto


def _outcome():
    return ImageGenerationOutcome(
        image_refs=[
            ImageRefDto(
                id="img_a", blob_url="/api/images/img_a/blob",
                thumb_url="/api/images/img_a/thumb",
                width=1024, height=1024, prompt="x",
                model_id="grok-imagine-image", tool_call_id="tc_a",
            )
        ],
        moderated_count=0, successful_count=1,
        llm_text_result="Generated 1 image.\n...",
        all_moderated=False,
    )


@pytest.mark.asyncio
async def test_execute_happy_path():
    svc = MagicMock()
    svc.generate_for_chat = AsyncMock(return_value=_outcome())
    ex = ImageGenerationToolExecutor(svc)
    result = await ex.execute("u1", "generate_image", {"prompt": "a cat", "__tool_call_id__": "tc_a"})
    assert "Generated 1 image" in result
    svc.generate_for_chat.assert_awaited_once_with(
        user_id="u1", prompt="a cat", tool_call_id="tc_a",
    )


@pytest.mark.asyncio
async def test_execute_missing_prompt_returns_error_text():
    svc = MagicMock()
    ex = ImageGenerationToolExecutor(svc)
    result = await ex.execute("u1", "generate_image", {})
    assert "prompt is required" in result.lower()


@pytest.mark.asyncio
async def test_execute_empty_prompt_returns_error_text():
    svc = MagicMock()
    ex = ImageGenerationToolExecutor(svc)
    result = await ex.execute("u1", "generate_image", {"prompt": "   "})
    assert "prompt is required" in result.lower()


@pytest.mark.asyncio
async def test_execute_no_active_config_returns_friendly_error():
    svc = MagicMock()
    svc.generate_for_chat = AsyncMock(side_effect=LookupError("no active image configuration"))
    ex = ImageGenerationToolExecutor(svc)
    result = await ex.execute("u1", "generate_image", {"prompt": "a cat"})
    assert "image generation is not configured" in result.lower()


@pytest.mark.asyncio
async def test_execute_wrong_tool_name_raises():
    svc = MagicMock()
    ex = ImageGenerationToolExecutor(svc)
    with pytest.raises(ValueError):
        await ex.execute("u1", "not_generate_image", {"prompt": "x"})


@pytest.mark.asyncio
async def test_execute_generic_exception_returns_error_text():
    svc = MagicMock()
    svc.generate_for_chat = AsyncMock(side_effect=RuntimeError("adapter exploded"))
    ex = ImageGenerationToolExecutor(svc)
    result = await ex.execute("u1", "generate_image", {"prompt": "a cat"})
    assert "image generation failed" in result.lower()
    assert "RuntimeError" in result


@pytest.mark.asyncio
async def test_execute_uses_tool_call_id_from_arguments():
    """tool_call_id must be taken from arguments[__tool_call_id__], not hardcoded."""
    svc = MagicMock()
    svc.generate_for_chat = AsyncMock(return_value=_outcome())
    ex = ImageGenerationToolExecutor(svc)
    await ex.execute("u1", "generate_image", {"prompt": "dogs", "__tool_call_id__": "tc_xyz"})
    svc.generate_for_chat.assert_awaited_once_with(
        user_id="u1", prompt="dogs", tool_call_id="tc_xyz",
    )


@pytest.mark.asyncio
async def test_execute_tool_call_id_defaults_to_empty_string():
    """If __tool_call_id__ is absent, an empty string is passed through."""
    svc = MagicMock()
    svc.generate_for_chat = AsyncMock(return_value=_outcome())
    ex = ImageGenerationToolExecutor(svc)
    await ex.execute("u1", "generate_image", {"prompt": "cats"})
    svc.generate_for_chat.assert_awaited_once_with(
        user_id="u1", prompt="cats", tool_call_id="",
    )


def test_tool_definition_has_correct_shape():
    td = ImageGenerationToolExecutor.tool_definition()
    assert td.name == "generate_image"
    assert td.parameters["properties"]["prompt"]["type"] == "string"
    assert "prompt" in td.parameters["required"]
