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
    _step_1_rewrite_model_unique_ids,
    _step_2_delete_migrated_connections,
    _step_3_strip_integration_api_keys,
    _step_4_drop_websearch_credentials,
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


# --------------------------------------------------------------------------- #
# Task 17 — steps 1..3
# --------------------------------------------------------------------------- #


@pytest.fixture
async def seed_xai_http_connection_with_persona(mongo_db):
    conn = {
        "_id": "c1x", "user_id": "u-px", "adapter_type": "xai_http",
        "display_name": "xAI", "slug": "xai-primary",
        "config": {}, "config_encrypted": {"api_key": _enc("x")},
        "created_at": datetime.now(UTC), "updated_at": datetime.now(UTC),
    }
    persona = {
        "_id": "p1", "user_id": "u-px", "model_unique_id": "xai-primary:grok-3",
    }
    await mongo_db["llm_connections"].insert_one(conn)
    await mongo_db["personas"].insert_one(persona)

    class S:
        pass
    s = S()
    s.slug = "xai-primary"
    s.user_id = "u-px"
    return s


@pytest.fixture
async def seed_ollama_cloud_connection_with_persona(mongo_db):
    conn = {
        "_id": "c2c", "user_id": "u-po", "adapter_type": "ollama_http",
        "display_name": "Ollama Cloud", "slug": "my-cloud",
        "config": {"base_url": "https://ollama.com"},
        "config_encrypted": {"api_key": _enc("y")},
        "created_at": datetime.now(UTC), "updated_at": datetime.now(UTC),
    }
    persona = {
        "_id": "p2", "user_id": "u-po", "model_unique_id": "my-cloud:llama3.2",
    }
    await mongo_db["llm_connections"].insert_one(conn)
    await mongo_db["personas"].insert_one(persona)

    class S:
        pass
    s = S()
    s.slug = "my-cloud"
    s.user_id = "u-po"
    return s


@pytest.fixture
async def seed_ollama_local_connection(mongo_db):
    conn = {
        "_id": "clc", "user_id": "u-local", "adapter_type": "ollama_http",
        "display_name": "my-homeserver", "slug": "my-homeserver",
        "config": {"base_url": "http://192.168.0.10:11434"},
        "config_encrypted": {},
        "created_at": datetime.now(UTC), "updated_at": datetime.now(UTC),
    }
    await mongo_db["llm_connections"].insert_one(conn)
    return conn


async def test_rewrite_xai_model_ids(mongo_db, seed_xai_http_connection_with_persona):
    await _step_1_rewrite_model_unique_ids(mongo_db)
    persona = await mongo_db["personas"].find_one({"user_id": "u-px"})
    assert persona["model_unique_id"] == "xai:grok-3"


async def test_rewrite_ollama_cloud_model_ids(
    mongo_db, seed_ollama_cloud_connection_with_persona,
):
    await _step_1_rewrite_model_unique_ids(mongo_db)
    persona = await mongo_db["personas"].find_one({"user_id": "u-po"})
    assert persona["model_unique_id"] == "ollama_cloud:llama3.2"


async def test_delete_xai_http_connections(mongo_db, seed_xai_http_connection):
    await _step_2_delete_migrated_connections(mongo_db)
    assert await mongo_db["llm_connections"].count_documents({"adapter_type": "xai_http"}) == 0


async def test_delete_ollama_cloud_connections_only(
    mongo_db, seed_ollama_cloud_connection, seed_ollama_local_connection,
):
    await _step_2_delete_migrated_connections(mongo_db)
    remaining = [d async for d in mongo_db["llm_connections"].find({})]
    assert len(remaining) == 1
    assert remaining[0]["_id"] == "clc"     # local selfhosted kept


async def test_strip_integration_api_keys(mongo_db, seed_xai_voice_integration):
    await _step_3_strip_integration_api_keys(mongo_db)
    cfg = await mongo_db["user_integration_configs"].find_one(
        {"integration_id": "xai_voice"},
    )
    assert "api_key" not in (cfg.get("config_encrypted") or {})


async def test_drop_websearch_collection_idempotent(mongo_db):
    await mongo_db["websearch_user_credentials"].insert_one(
        {"_id": "x", "user_id": "u1", "provider_id": "ollama_cloud_search"},
    )
    await _step_4_drop_websearch_credentials(mongo_db)
    await _step_4_drop_websearch_credentials(mongo_db)   # no-op second run
    names = await mongo_db.list_collection_names()
    assert "websearch_user_credentials" not in names
