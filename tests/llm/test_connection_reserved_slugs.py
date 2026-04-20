"""Reserved-slug rejection for user-created LLM connections.

Premium Provider ids (``xai``, ``mistral``, ``ollama_cloud``) are reserved
so a user cannot shadow them with a personal connection slug. The match
is exact — normal slugs like ``my-xai`` or ``mistral-eu`` are fine.
"""

import pytest

from backend.modules.llm._connections import (
    ConnectionRepository,
    SlugReservedError,
)


@pytest.mark.parametrize("slug", ["xai", "mistral", "ollama_cloud"])
async def test_reserved_slugs_rejected(mock_db, slug):
    repo = ConnectionRepository(mock_db)
    await repo.create_indexes()
    with pytest.raises(SlugReservedError):
        await repo.create(
            user_id="u1",
            adapter_type="ollama_http",
            display_name="x",
            slug=slug,
            config={"base_url": "http://localhost:11434"},
        )


async def test_non_reserved_slug_accepted(mock_db):
    repo = ConnectionRepository(mock_db)
    await repo.create_indexes()
    doc = await repo.create(
        user_id="u1",
        adapter_type="ollama_http",
        display_name="ok",
        slug="my-homeserver",
        config={"base_url": "http://localhost:11434"},
    )
    assert doc["slug"] == "my-homeserver"
