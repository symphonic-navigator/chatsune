"""Tests for premium-provider catalogue ordering by sort_priority."""
from __future__ import annotations

import pytest

from backend.modules.providers import PremiumProviderService


class _StubRepo:
    """Repository stub — catalogue() never reads from it."""
    async def list_for_user(self, user_id: str):  # pragma: no cover
        return []


@pytest.mark.asyncio
async def test_catalogue_is_sorted_by_sort_priority():
    svc = PremiumProviderService(_StubRepo())  # type: ignore[arg-type]
    out = await svc.catalogue()
    priorities = [item["sort_priority"] for item in out]
    assert priorities == sorted(priorities), (
        f"catalogue not sorted by sort_priority: {priorities}"
    )


@pytest.mark.asyncio
async def test_catalogue_emits_sort_priority_field():
    svc = PremiumProviderService(_StubRepo())  # type: ignore[arg-type]
    out = await svc.catalogue()
    assert all("sort_priority" in item for item in out)
    assert all(isinstance(item["sort_priority"], int) for item in out)


@pytest.mark.asyncio
async def test_featured_providers_appear_in_expected_order():
    """Ollama Cloud → Tensorix → xAI → Mistral; the rest follow."""
    svc = PremiumProviderService(_StubRepo())  # type: ignore[arg-type]
    out = await svc.catalogue()
    ids = [item["id"] for item in out]
    # Featured tier is fully ordered.
    assert ids.index("ollama_cloud") < ids.index("tensorix")
    assert ids.index("tensorix") < ids.index("xai")
    assert ids.index("xai") < ids.index("mistral")
    # Long tail comes after Mistral.
    for tail_id in ("nano_gpt", "openrouter", "novita"):
        assert ids.index("mistral") < ids.index(tail_id), (
            f"{tail_id} should come after mistral; ids={ids}"
        )


@pytest.mark.asyncio
async def test_tensorix_is_registered_with_correct_metadata():
    svc = PremiumProviderService(_StubRepo())  # type: ignore[arg-type]
    out = await svc.catalogue()
    tensorix = next(p for p in out if p["id"] == "tensorix")
    assert tensorix["display_name"] == "Tensorix"
    assert tensorix["base_url"] == "https://api.tensorix.ai/v1"
    assert tensorix["icon"] == "tensorix"
    # LLM only.
    assert tensorix["capabilities"] == ["llm"]
