import pytest
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.modules.integrations._repository import (
    IntegrationRepository,
    _split_config, _redact_config, _encrypt, _decrypt,
)


def test_split_config_separates_secret_fields():
    plain, encrypted = _split_config(
        "mistral_voice",
        {"api_key": "sk-abc", "something_else": "x"},
    )
    assert "api_key" not in plain
    assert "api_key" in encrypted
    assert plain == {"something_else": "x"}


def test_split_config_skips_empty_secret():
    plain, encrypted = _split_config("mistral_voice", {"api_key": ""})
    assert encrypted == {}


def test_redact_reports_is_set_true_when_encrypted_present():
    redacted = _redact_config(
        "mistral_voice",
        plain={"something": 1},
        encrypted={"api_key": "gAAA..."},
    )
    assert redacted["api_key"] == {"is_set": True}
    assert redacted["something"] == 1


def test_redact_reports_is_set_false_when_encrypted_absent():
    redacted = _redact_config("mistral_voice", plain={}, encrypted={})
    assert redacted["api_key"] == {"is_set": False}


def test_encrypt_decrypt_roundtrip():
    assert _decrypt(_encrypt("hello")) == "hello"


@pytest.mark.asyncio
async def test_upsert_preserves_existing_secret_when_absent(mongo_db: AsyncIOMotorDatabase):
    repo = IntegrationRepository(mongo_db)
    await repo.upsert_config(
        user_id="u1", integration_id="mistral_voice", enabled=True,
        config={"api_key": "sk-original"},
    )
    # Upsert again WITHOUT api_key in config — existing value must be preserved
    await repo.upsert_config(
        user_id="u1", integration_id="mistral_voice", enabled=True,
        config={},
    )
    secret = await repo.get_decrypted_secret("u1", "mistral_voice", "api_key")
    assert secret == "sk-original"


@pytest.mark.asyncio
async def test_upsert_clears_secret_on_empty_string(mongo_db: AsyncIOMotorDatabase):
    repo = IntegrationRepository(mongo_db)
    await repo.upsert_config(
        user_id="u1", integration_id="mistral_voice", enabled=True,
        config={"api_key": "sk-original"},
    )
    await repo.upsert_config(
        user_id="u1", integration_id="mistral_voice", enabled=True,
        config={"api_key": ""},
    )
    secret = await repo.get_decrypted_secret("u1", "mistral_voice", "api_key")
    assert secret is None


@pytest.mark.asyncio
async def test_upsert_replaces_secret_with_new_value(mongo_db: AsyncIOMotorDatabase):
    repo = IntegrationRepository(mongo_db)
    await repo.upsert_config(
        user_id="u1", integration_id="mistral_voice", enabled=True,
        config={"api_key": "sk-old"},
    )
    await repo.upsert_config(
        user_id="u1", integration_id="mistral_voice", enabled=True,
        config={"api_key": "sk-new"},
    )
    secret = await repo.get_decrypted_secret("u1", "mistral_voice", "api_key")
    assert secret == "sk-new"


@pytest.mark.asyncio
async def test_upsert_returns_redacted_doc(mongo_db: AsyncIOMotorDatabase):
    repo = IntegrationRepository(mongo_db)
    result = await repo.upsert_config(
        user_id="u1", integration_id="mistral_voice", enabled=True,
        config={"api_key": "sk-abc"},
    )
    assert "config_encrypted" not in result
    assert result["config"]["api_key"] == {"is_set": True}


@pytest.mark.asyncio
async def test_delete_all_for_user_removes_encrypted_secrets(mongo_db: AsyncIOMotorDatabase):
    repo = IntegrationRepository(mongo_db)
    await repo.upsert_config(
        user_id="u1",
        integration_id="mistral_voice",
        enabled=True,
        config={"api_key": "sk-test"},
    )
    deleted = await repo.delete_all_for_user("u1")
    assert deleted == 1
    remaining = await repo.get_user_config("u1", "mistral_voice")
    assert remaining is None
