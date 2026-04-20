"""Persona._validate_model_unique_id must recognise Premium Provider slugs."""

import pytest
from fastapi import HTTPException

from backend.modules.persona import _handlers as persona_handlers_mod
from backend.modules.persona._handlers import _validate_model_unique_id
from backend.modules.providers._repository import PremiumProviderAccountRepository


@pytest.fixture
async def mock_db():
    # Local fixture — the persona test folder does not have a conftest db
    # fixture yet, and we only need the ``premium_provider_accounts`` and
    # ``llm_connections`` collections for these tests.
    import pytest_asyncio  # noqa: F401
    from motor.motor_asyncio import AsyncIOMotorClient
    from backend.config import settings

    client = AsyncIOMotorClient(settings.mongodb_uri)
    db = client[settings.mongo_db_name]
    to_clean = ["premium_provider_accounts", "llm_connections"]
    for c in to_clean:
        await db[c].drop()
    try:
        yield db
    finally:
        for c in to_clean:
            await db[c].drop()
        client.close()


@pytest.fixture(autouse=True)
def _patch_get_db(monkeypatch, mock_db):
    """Route every ``get_db`` reachable from the validator to the test db."""
    monkeypatch.setattr(persona_handlers_mod, "get_db", lambda: mock_db)
    import backend.database as database_mod
    import backend.modules.llm._resolver as resolver_mod
    monkeypatch.setattr(database_mod, "get_db", lambda: mock_db)
    monkeypatch.setattr(resolver_mod, "get_db", lambda: mock_db)


@pytest.mark.asyncio
async def test_premium_slug_with_account_passes(mock_db):
    repo = PremiumProviderAccountRepository(mock_db)
    await repo.upsert("u-xai", "xai", {"api_key": "k"})

    # Must not raise — the user has a Premium Provider Account for xAI.
    await _validate_model_unique_id("u-xai", "xai:grok-3")


@pytest.mark.asyncio
async def test_premium_slug_without_account_raises_422():
    with pytest.raises(HTTPException) as ei:
        await _validate_model_unique_id("fresh-user", "xai:grok-3")
    assert ei.value.status_code == 422


@pytest.mark.asyncio
async def test_mistral_premium_slug_with_account_passes(mock_db):
    # ``mistral`` is a reserved premium slug with no LLM adapter (yet), but
    # the validator should still accept it when the user has an account —
    # the persona is simply declaring its intended provider. Any inference
    # attempt would fail later, but the persona is still configurable.
    repo = PremiumProviderAccountRepository(mock_db)
    await repo.upsert("u-mistral", "mistral", {"api_key": "k"})

    await _validate_model_unique_id("u-mistral", "mistral:mistral-large")


@pytest.mark.asyncio
async def test_invalid_format_raises_400():
    with pytest.raises(HTTPException) as ei:
        await _validate_model_unique_id("user", "no-colon-here")
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_non_premium_slug_still_requires_connection(mock_db):
    # ``random-slug`` is neither a reserved premium provider nor a known
    # user connection → validator rejects with 422.
    with pytest.raises(HTTPException) as ei:
        await _validate_model_unique_id("user", "random-slug:some-model")
    assert ei.value.status_code == 422
