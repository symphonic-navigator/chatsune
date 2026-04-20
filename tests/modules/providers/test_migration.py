"""Tests for the Premium Provider Accounts v1 one-shot migration.

Uses the ``mongo_db`` fixture from ``tests/modules/providers/conftest.py`` —
that fixture already wipes every collection the migration reads or writes
before and after each test.
"""
from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet

from backend.config import settings
from backend.modules.providers._migration_v1 import (
    _MARKER_ID,
    _step_0_import_keys,
    run_if_needed,
)
from backend.modules.providers._repository import PremiumProviderAccountRepository


def _enc(plain: str) -> str:
    return Fernet(settings.encryption_key.encode()).encrypt(plain.encode()).decode()


# --------------------------------------------------------------------------- #
# Task 15 — scaffold / marker gate
# --------------------------------------------------------------------------- #


async def test_marker_prevents_rerun(mongo_db):
    await mongo_db["_migrations"].insert_one({"_id": _MARKER_ID})
    await run_if_needed(mongo_db, None)
    # Simply the absence of exceptions and speed is the assertion.


async def test_first_run_sets_marker(mongo_db):
    await run_if_needed(mongo_db, None)
    marker = await mongo_db["_migrations"].find_one({"_id": _MARKER_ID})
    assert marker is not None


# --------------------------------------------------------------------------- #
# Task 16 — step 0: import keys
# --------------------------------------------------------------------------- #


@pytest.fixture
async def seed_xai_http_connection(mongo_db):
    doc = {
        "_id": "c1", "user_id": "u1", "adapter_type": "xai_http",
        "display_name": "xAI", "slug": "xai-primary",
        "config": {}, "config_encrypted": {"api_key": _enc("xai-http-key")},
        "created_at": datetime.now(UTC), "updated_at": datetime.now(UTC),
    }
    await mongo_db["llm_connections"].insert_one(doc)
    return doc


@pytest.fixture
async def seed_xai_voice_integration(mongo_db):
    doc = {
        "user_id": "u1", "integration_id": "xai_voice", "enabled": True,
        "config": {}, "config_encrypted": {"api_key": _enc("xai-voice-key")},
    }
    await mongo_db["user_integration_configs"].insert_one(doc)
    return doc


@pytest.fixture
async def seed_mistral_voice_integration(mongo_db):
    doc = {
        "user_id": "u-m", "integration_id": "mistral_voice", "enabled": True,
        "config": {}, "config_encrypted": {"api_key": _enc("mistral-key")},
    }
    await mongo_db["user_integration_configs"].insert_one(doc)
    return doc


@pytest.fixture
async def seed_ollama_cloud_connection(mongo_db):
    doc = {
        "_id": "c2", "user_id": "u-oc", "adapter_type": "ollama_http",
        "display_name": "Ollama Cloud", "slug": "ollama-cloud",
        "config": {"base_url": "https://ollama.com"},
        "config_encrypted": {"api_key": _enc("oc-conn-key")},
        "created_at": datetime.now(UTC), "updated_at": datetime.now(UTC),
    }
    await mongo_db["llm_connections"].insert_one(doc)
    return doc


@pytest.fixture
async def seed_ollama_cloud_websearch_cred(mongo_db):
    doc = {
        "_id": "w1", "user_id": "u-oc2", "provider_id": "ollama_cloud_search",
        "api_key_encrypted": _enc("oc-websearch-key"),
        "created_at": datetime.now(UTC), "updated_at": datetime.now(UTC),
    }
    await mongo_db["websearch_user_credentials"].insert_one(doc)
    return doc


async def test_import_xai_from_llm_connection(mongo_db, seed_xai_http_connection):
    await _step_0_import_keys(mongo_db)
    repo = PremiumProviderAccountRepository(mongo_db)
    doc = await repo.find("u1", "xai")
    assert doc is not None
    assert repo.get_decrypted_secret(doc, "api_key") == "xai-http-key"


async def test_import_xai_fallback_to_voice_integration(
    mongo_db, seed_xai_voice_integration,
):
    # Only voice-integration key, no LLM connection
    await _step_0_import_keys(mongo_db)
    repo = PremiumProviderAccountRepository(mongo_db)
    doc = await repo.find("u1", "xai")
    assert doc is not None
    assert repo.get_decrypted_secret(doc, "api_key") == "xai-voice-key"


async def test_import_mistral_from_voice_integration(
    mongo_db, seed_mistral_voice_integration,
):
    await _step_0_import_keys(mongo_db)
    repo = PremiumProviderAccountRepository(mongo_db)
    doc = await repo.find("u-m", "mistral")
    assert doc is not None
    assert repo.get_decrypted_secret(doc, "api_key") == "mistral-key"


async def test_import_ollama_cloud_from_connection(
    mongo_db, seed_ollama_cloud_connection,
):
    await _step_0_import_keys(mongo_db)
    repo = PremiumProviderAccountRepository(mongo_db)
    doc = await repo.find("u-oc", "ollama_cloud")
    assert doc is not None
    assert repo.get_decrypted_secret(doc, "api_key") == "oc-conn-key"


async def test_import_ollama_cloud_fallback_websearch(
    mongo_db, seed_ollama_cloud_websearch_cred,
):
    await _step_0_import_keys(mongo_db)
    repo = PremiumProviderAccountRepository(mongo_db)
    doc = await repo.find("u-oc2", "ollama_cloud")
    assert doc is not None
    assert repo.get_decrypted_secret(doc, "api_key") == "oc-websearch-key"


async def test_import_is_idempotent(mongo_db, seed_xai_http_connection):
    await _step_0_import_keys(mongo_db)
    await _step_0_import_keys(mongo_db)
    docs = [
        d async for d in mongo_db["premium_provider_accounts"].find({"provider_id": "xai"})
    ]
    assert len(docs) == 1


async def test_import_primary_wins_on_conflict(
    mongo_db, seed_xai_http_connection, seed_xai_voice_integration, caplog,
):
    # User u1 has BOTH: LLM connection (primary) with "xai-http-key" + voice
    # integration (secondary) with "xai-voice-key". Primary wins.
    import logging
    caplog.set_level(logging.WARNING)
    await _step_0_import_keys(mongo_db)
    repo = PremiumProviderAccountRepository(mongo_db)
    doc = await repo.find("u1", "xai")
    assert repo.get_decrypted_secret(doc, "api_key") == "xai-http-key"
    assert any("conflict" in r.message.lower() for r in caplog.records)
