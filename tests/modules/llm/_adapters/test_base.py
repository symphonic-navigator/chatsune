"""Tests for BaseAdapter image-generation hooks (Task 8)."""

from collections.abc import AsyncIterator

import pytest

from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._types import ResolvedConnection
from shared.dtos.images import ImageGenItem, ImageGroupConfig, XaiImagineConfig
from shared.dtos.inference import CompletionRequest
from shared.dtos.llm import ModelMetaDto


class DummyAdapter(BaseAdapter):
    """Minimal concrete subclass for testing BaseAdapter defaults."""

    adapter_type = "dummy"
    display_name = "Dummy"
    view_id = "dummy"

    async def fetch_models(self, connection: ResolvedConnection) -> list[ModelMetaDto]:
        return []

    def stream_completion(
        self, connection: ResolvedConnection, request: CompletionRequest,
    ) -> AsyncIterator:
        async def _empty():
            return
            yield  # make it an async generator

        return _empty()


# ---------------------------------------------------------------------------
# Image-generation capability tests
# ---------------------------------------------------------------------------

def test_base_adapter_image_capability_default_false() -> None:
    """A subclass that does not override supports_image_generation must be False."""
    assert DummyAdapter.supports_image_generation is False


@pytest.mark.asyncio
async def test_base_adapter_image_groups_default_empty() -> None:
    """image_groups() must return an empty list by default."""
    adapter = DummyAdapter()
    result = await adapter.image_groups(connection=None)  # type: ignore[arg-type]
    assert result == []


@pytest.mark.asyncio
async def test_base_adapter_generate_images_default_raises() -> None:
    """generate_images() must raise NotImplementedError by default."""
    adapter = DummyAdapter()
    config = XaiImagineConfig()
    with pytest.raises(NotImplementedError):
        await adapter.generate_images(
            None,  # type: ignore[arg-type]
            "xai_imagine",
            config,
            "a red panda in the rain",
        )
