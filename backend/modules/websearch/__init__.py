"""Websearch module — pluggable web-search adapters with credential sharing.

Public API: import only from this file.
"""

import logging

import httpx

from backend.modules.websearch._registry import (
    KEY_SOURCES,
    SEARCH_ADAPTER_REGISTRY,
    SEARCH_PROVIDER_BASE_URLS,
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
# Key resolution
# ---------------------------------------------------------------------------

async def _resolve_api_key(user_id: str, provider_id: str) -> str:
    """Resolve the API key for a search provider, following KEY_SOURCES."""
    source = KEY_SOURCES.get(provider_id)

    if source is not None and source.startswith("llm:"):
        llm_provider_id = source.removeprefix("llm:")
        # Import locally to avoid circular imports at module load time.
        from backend.modules.llm import (
            LlmCredentialNotFoundError,
            LlmProviderNotFoundError,
            get_api_key,
        )
        try:
            return await get_api_key(user_id, llm_provider_id)
        except (LlmProviderNotFoundError, LlmCredentialNotFoundError) as exc:
            raise WebSearchCredentialNotFoundError(str(exc)) from exc

    # source is None → provider uses its own credential store (not yet implemented)
    raise WebSearchCredentialNotFoundError(
        f"No credential source configured for search provider '{provider_id}'"
    )


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


__all__ = [
    "get_tool_definitions",
    "search",
    "fetch",
    "WebSearchProviderNotFoundError",
    "WebSearchCredentialNotFoundError",
]
