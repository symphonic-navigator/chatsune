import pytest

from backend.modules.llm._connections import (
    ConnectionRepository,
    InvalidAdapterTypeError,
    InvalidSlugError,
    SlugAlreadyExistsError,
)


@pytest.mark.asyncio
async def test_suggest_slug_returns_base_when_unused(test_db):
    repo = ConnectionRepository(test_db)
    await repo.create_indexes()
    assert await repo.suggest_slug("u1", "ollama-local") == "ollama-local"


@pytest.mark.asyncio
async def test_suggest_slug_auto_increments_on_duplicate(test_db):
    repo = ConnectionRepository(test_db)
    await repo.create_indexes()
    await repo.create(
        "u1", "ollama_http", "X", "ollama-local",
        {"url": "x", "max_parallel": 1},
    )
    assert await repo.suggest_slug("u1", "ollama-local") == "ollama-local-2"
    await repo.create(
        "u1", "ollama_http", "Y", "ollama-local-2",
        {"url": "x", "max_parallel": 1},
    )
    assert await repo.suggest_slug("u1", "ollama-local") == "ollama-local-3"


@pytest.mark.asyncio
async def test_create_rejects_unknown_adapter(test_db):
    repo = ConnectionRepository(test_db)
    with pytest.raises(InvalidAdapterTypeError):
        await repo.create("u1", "nope", "X", "s", {})


@pytest.mark.asyncio
async def test_create_rejects_invalid_slug(test_db):
    repo = ConnectionRepository(test_db)
    with pytest.raises(InvalidSlugError):
        await repo.create("u1", "ollama_http", "X", "Bad Slug", {})


@pytest.mark.asyncio
async def test_create_duplicate_slug_raises_with_suggestion(test_db):
    repo = ConnectionRepository(test_db)
    await repo.create_indexes()
    await repo.create(
        "u1", "ollama_http", "X", "ollama-local",
        {"url": "x", "max_parallel": 1},
    )
    with pytest.raises(SlugAlreadyExistsError) as exc:
        await repo.create(
            "u1", "ollama_http", "Y", "ollama-local",
            {"url": "y", "max_parallel": 1},
        )
    assert exc.value.suggested == "ollama-local-2"


@pytest.mark.asyncio
async def test_secret_field_is_encrypted(test_db):
    repo = ConnectionRepository(test_db)
    await repo.create_indexes()
    doc = await repo.create(
        "u1", "ollama_http", "X", "s",
        {"url": "u", "api_key": "SECRET", "max_parallel": 1},
    )
    assert "api_key" not in doc["config"]
    assert "api_key" in doc["config_encrypted"]
    assert repo.get_decrypted_secret(doc, "api_key") == "SECRET"


@pytest.mark.asyncio
async def test_dto_redacts_secrets(test_db):
    repo = ConnectionRepository(test_db)
    await repo.create_indexes()
    doc = await repo.create(
        "u1", "ollama_http", "X", "s",
        {"url": "u", "api_key": "SECRET", "max_parallel": 1},
    )
    dto = ConnectionRepository.to_dto(doc)
    assert dto.config["api_key"] == {"is_set": True}
    assert dto.config["url"] == "u"
