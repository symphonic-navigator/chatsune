"""Unit test: the 2026-04-24 session-toggles migration is idempotent and correct."""
import importlib

import pytest
from unittest.mock import AsyncMock

migration_mod = importlib.import_module(
    "backend.migrations.m_2026_04_24_session_toggles",
)

pytestmark = pytest.mark.asyncio


async def test_migrate_one_removes_disabled_and_sets_auto_read_when_voice_configured(monkeypatch):
    monkeypatch.setattr(
        "backend.modules.chat._toggle_defaults.get_tool_groups_for_persona",
        lambda persona: [],
    )
    session = {
        "_id": "s1",
        "persona_id": "p1",
        "disabled_tool_groups": [],
    }
    personas = AsyncMock()
    personas.find_one = AsyncMock(return_value={
        "_id": "p1",
        "voice_config": {"tts_provider_id": "xai", "dialogue_voice": "Ara"},
    })
    mutation = await migration_mod.migrate_one(session, personas)

    assert mutation["$unset"] == {"disabled_tool_groups": ""}
    assert mutation["$set"]["auto_read"] is True
    assert mutation["$set"]["tools_enabled"] is False


async def test_migrate_one_is_idempotent_on_already_migrated():
    session = {
        "_id": "s1",
        "persona_id": "p1",
        "tools_enabled": True,
        "auto_read": False,
    }
    personas = AsyncMock()
    result = await migration_mod.migrate_one(session, personas)
    assert result.get("skipped") is True
