"""Tests for prompt-extension deduplication in get_integration_prompt_extensions.

These tests are deliberately DB-free: they monkeypatch the module-level
``get_enabled_integration_ids`` so no MongoDB connection is required.
``get_integration`` stays real — it reads the in-memory registry only.
"""

import pytest

import backend.modules.integrations as integ


@pytest.mark.asyncio
async def test_identical_voice_templates_deduplicated(monkeypatch):
    """xai_voice and nano_gpt_voice_xai share the byte-identical xAI voice
    block; it must appear exactly once in the combined extension."""

    async def fake_enabled(user_id, persona_id=None):
        return ["xai_voice", "nano_gpt_voice_xai"]

    monkeypatch.setattr(integ, "get_enabled_integration_ids", fake_enabled)

    result = await integ.get_integration_prompt_extensions("u", "p")

    assert result is not None
    assert result.count('<integrations name="xai_voice">') == 1


@pytest.mark.asyncio
async def test_non_identical_templates_both_kept(monkeypatch):
    """Distinct templates must each be preserved — deduplication only
    removes byte-identical duplicates, never different blocks."""

    async def fake_enabled(user_id, persona_id=None):
        return ["xai_voice", "lovense"]

    monkeypatch.setattr(integ, "get_enabled_integration_ids", fake_enabled)

    result = await integ.get_integration_prompt_extensions("u", "p")

    assert result is not None
    assert result.count('<integrations name="xai_voice">') == 1
    assert result.count('<integrations name="lovense">') == 1
