import pytest
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.modules.integrations._models import IntegrationDefinition
from backend.modules.integrations._registry import _registry as _integration_registry
from backend.modules.integrations._repository import (
    IntegrationRepository,
    _split_config, _redact_config, _encrypt, _decrypt,
)


# The built-in integrations no longer store secrets directly (they are
# delegated to Premium Provider accounts). To keep exercising the
# repository's encryption machinery, we register a minimal synthetic
# integration with a ``secret=True`` field for the duration of these tests.
_TEST_INTEGRATION_ID = "__test_secret_integration__"


def _ensure_test_integration_registered() -> None:
    if _TEST_INTEGRATION_ID in _integration_registry:
        return
    _integration_registry[_TEST_INTEGRATION_ID] = IntegrationDefinition(
        id=_TEST_INTEGRATION_ID,
        display_name="Test Secret Integration",
        description="Synthetic integration for repository encryption tests.",
        icon="",
        execution_mode="backend",
        config_fields=[
            {
                "key": "api_key",
                "label": "API Key",
                "field_type": "password",
                "secret": True,
                "required": True,
                "description": "",
            },
        ],
    )


_ensure_test_integration_registered()


def test_split_config_separates_secret_fields():
    plain, encrypted = _split_config(
        _TEST_INTEGRATION_ID,
        {"api_key": "sk-abc", "something_else": "x"},
    )
    assert "api_key" not in plain
    assert "api_key" in encrypted
    assert plain == {"something_else": "x"}


def test_split_config_skips_empty_secret():
    plain, encrypted = _split_config(_TEST_INTEGRATION_ID, {"api_key": ""})
    assert encrypted == {}


def test_redact_reports_is_set_true_when_encrypted_present():
    redacted = _redact_config(
        _TEST_INTEGRATION_ID,
        plain={"something": 1},
        encrypted={"api_key": "gAAA..."},
    )
    assert redacted["api_key"] == {"is_set": True}
    assert redacted["something"] == 1


def test_redact_reports_is_set_false_when_encrypted_absent():
    redacted = _redact_config(_TEST_INTEGRATION_ID, plain={}, encrypted={})
    assert redacted["api_key"] == {"is_set": False}


def test_encrypt_decrypt_roundtrip():
    assert _decrypt(_encrypt("hello")) == "hello"


@pytest.mark.asyncio
async def test_upsert_preserves_existing_secret_when_absent(mongo_db: AsyncIOMotorDatabase):
    repo = IntegrationRepository(mongo_db)
    await repo.upsert_config(
        user_id="u1", integration_id=_TEST_INTEGRATION_ID, enabled=True,
        config={"api_key": "sk-original"},
    )
    # Upsert again WITHOUT api_key in config — existing value must be preserved
    await repo.upsert_config(
        user_id="u1", integration_id=_TEST_INTEGRATION_ID, enabled=True,
        config={},
    )
    secret = await repo.get_decrypted_secret("u1", _TEST_INTEGRATION_ID, "api_key")
    assert secret == "sk-original"


@pytest.mark.asyncio
async def test_upsert_clears_secret_on_empty_string(mongo_db: AsyncIOMotorDatabase):
    repo = IntegrationRepository(mongo_db)
    await repo.upsert_config(
        user_id="u1", integration_id=_TEST_INTEGRATION_ID, enabled=True,
        config={"api_key": "sk-original"},
    )
    await repo.upsert_config(
        user_id="u1", integration_id=_TEST_INTEGRATION_ID, enabled=True,
        config={"api_key": ""},
    )
    secret = await repo.get_decrypted_secret("u1", _TEST_INTEGRATION_ID, "api_key")
    assert secret is None


@pytest.mark.asyncio
async def test_upsert_replaces_secret_with_new_value(mongo_db: AsyncIOMotorDatabase):
    repo = IntegrationRepository(mongo_db)
    await repo.upsert_config(
        user_id="u1", integration_id=_TEST_INTEGRATION_ID, enabled=True,
        config={"api_key": "sk-old"},
    )
    await repo.upsert_config(
        user_id="u1", integration_id=_TEST_INTEGRATION_ID, enabled=True,
        config={"api_key": "sk-new"},
    )
    secret = await repo.get_decrypted_secret("u1", _TEST_INTEGRATION_ID, "api_key")
    assert secret == "sk-new"


@pytest.mark.asyncio
async def test_upsert_returns_redacted_doc(mongo_db: AsyncIOMotorDatabase):
    repo = IntegrationRepository(mongo_db)
    result = await repo.upsert_config(
        user_id="u1", integration_id=_TEST_INTEGRATION_ID, enabled=True,
        config={"api_key": "sk-abc"},
    )
    assert "config_encrypted" not in result
    assert result["config"]["api_key"] == {"is_set": True}


@pytest.mark.asyncio
async def test_delete_all_for_user_removes_encrypted_secrets(mongo_db: AsyncIOMotorDatabase):
    repo = IntegrationRepository(mongo_db)
    await repo.upsert_config(
        user_id="u1",
        integration_id=_TEST_INTEGRATION_ID,
        enabled=True,
        config={"api_key": "sk-test"},
    )
    deleted = await repo.delete_all_for_user("u1")
    assert deleted == 1
    remaining = await repo.get_user_config("u1", _TEST_INTEGRATION_ID)
    assert remaining is None
