"""Websearch module — pluggable web-search adapters with own credential store.

Public API: import only from this file.
"""

import logging

from backend.database import get_db
from backend.modules.websearch._credentials import WebSearchCredentialRepository
from backend.modules.websearch._handlers import router
from backend.modules.websearch._registry import (
    SEARCH_ADAPTER_REGISTRY,
    SEARCH_PROVIDER_BASE_URLS,
    SEARCH_PROVIDER_DISPLAY_NAMES,
)
from shared.dtos.inference import ToolDefinition
from shared.dtos.websearch import WebFetchResultDto, WebSearchResultDto

logger = logging.getLogger(__name__)


class WebSearchProviderNotFoundError(Exception):
    """Search provider ID is not registered."""


class WebSearchCredentialNotFoundError(Exception):
    """No API key available for the requested search provider."""


# ---------------------------------------------------------------------------
# Tool definitions — injected into CompletionRequest.tools when search is on
# ---------------------------------------------------------------------------

_TOOL_WEB_SEARCH = ToolDefinition(
    name="web_search",
    description=(
        "Search the web for current information. Use this when the user "
        "explicitly asks you to search the web or look something up online. "
        "Do not use this tool unless the user requests a web search."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query"},
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (1-10, default 5)",
            },
        },
        "required": ["query"],
    },
)

_TOOL_WEB_FETCH = ToolDefinition(
    name="web_fetch",
    description=(
        "Fetch the full content of a web page by URL. Use this to read the "
        "detailed content of a page found via web_search."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The URL to fetch"},
        },
        "required": ["url"],
    },
)


def get_tool_definitions() -> list[ToolDefinition]:
    """Return the tool definitions to inject into the LLM request."""
    return [_TOOL_WEB_SEARCH, _TOOL_WEB_FETCH]


# ---------------------------------------------------------------------------
# Index initialisation
# ---------------------------------------------------------------------------

async def init_indexes(db) -> None:
    """Create indexes for the websearch credentials collection."""
    await WebSearchCredentialRepository(db).create_indexes()


# ---------------------------------------------------------------------------
# Key resolution — reads from this module's own credential store
# ---------------------------------------------------------------------------

async def _resolve_api_key(user_id: str, provider_id: str) -> str:
    repo = WebSearchCredentialRepository(get_db())
    doc = await repo.find(user_id, provider_id)
    if doc is None:
        raise WebSearchCredentialNotFoundError(
            f"No credential configured for search provider '{provider_id}'"
        )
    return repo.get_raw_key(doc)


# ---------------------------------------------------------------------------
# Public search / fetch API
# ---------------------------------------------------------------------------

async def search(
    user_id: str,
    provider_id: str,
    query: str,
    max_results: int = 5,
) -> list[WebSearchResultDto]:
    """Execute a web search via the given provider.

    Raises:
        WebSearchProviderNotFoundError: unknown provider_id.
        WebSearchCredentialNotFoundError: no key available.
        httpx.HTTPStatusError: upstream returned an error status.
    """
    if provider_id not in SEARCH_ADAPTER_REGISTRY:
        raise WebSearchProviderNotFoundError(
            f"Unknown search provider: {provider_id}"
        )

    api_key = await _resolve_api_key(user_id, provider_id)
    adapter = SEARCH_ADAPTER_REGISTRY[provider_id](
        base_url=SEARCH_PROVIDER_BASE_URLS[provider_id],
    )
    return await adapter.search(api_key, query, max_results)


async def fetch(
    user_id: str,
    provider_id: str,
    url: str,
) -> WebFetchResultDto:
    """Fetch full page content via the given provider.

    Raises:
        WebSearchProviderNotFoundError: unknown provider_id.
        WebSearchCredentialNotFoundError: no key available.
        httpx.HTTPStatusError: upstream returned an error status.
    """
    if provider_id not in SEARCH_ADAPTER_REGISTRY:
        raise WebSearchProviderNotFoundError(
            f"Unknown search provider: {provider_id}"
        )

    api_key = await _resolve_api_key(user_id, provider_id)
    adapter = SEARCH_ADAPTER_REGISTRY[provider_id](
        base_url=SEARCH_PROVIDER_BASE_URLS[provider_id],
    )
    return await adapter.fetch(api_key, url)


async def delete_all_for_user(user_id: str) -> int:
    """Delete all stored web-search credentials owned by ``user_id``.

    Called by the user self-delete (right-to-be-forgotten) cascade.
    """
    repo = WebSearchCredentialRepository(get_db())
    count = await repo.delete_all_for_user(user_id)
    logger.info(
        "websearch.delete_all_for_user user_id=%s deleted=%d",
        user_id, count,
    )
    return count


__all__ = [
    "router",
    "init_indexes",
    "get_tool_definitions",
    "search",
    "fetch",
    "delete_all_for_user",
    "WebSearchProviderNotFoundError",
    "WebSearchCredentialNotFoundError",
]
