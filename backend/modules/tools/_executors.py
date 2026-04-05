"""Thin executor wrappers that call module public APIs."""

import json
import logging

_log = logging.getLogger(__name__)

# Default search provider — will become configurable later.
_DEFAULT_SEARCH_PROVIDER = "ollama_cloud"


class WebSearchExecutor:
    """Dispatches web_search and web_fetch tool calls to the websearch module."""

    async def execute(self, user_id: str, tool_name: str, arguments: dict) -> str:
        from backend.modules.websearch import (
            WebSearchCredentialNotFoundError,
            WebSearchProviderNotFoundError,
            fetch,
            search,
        )

        try:
            if tool_name == "web_search":
                query = arguments.get("query", "")
                max_results = arguments.get("max_results", 5)
                results = await search(
                    user_id=user_id,
                    provider_id=_DEFAULT_SEARCH_PROVIDER,
                    query=query,
                    max_results=max_results,
                )
                return json.dumps(
                    [r.model_dump() for r in results],
                    ensure_ascii=False,
                )

            if tool_name == "web_fetch":
                url = arguments.get("url", "")
                result = await fetch(
                    user_id=user_id,
                    provider_id=_DEFAULT_SEARCH_PROVIDER,
                    url=url,
                )
                return result.model_dump_json()

        except (WebSearchProviderNotFoundError, WebSearchCredentialNotFoundError) as exc:
            _log.warning("Web search credential issue for user %s: %s", user_id, exc)
            return json.dumps({"error": str(exc)})
        except Exception as exc:
            _log.warning("Web search failed for user %s: %s", user_id, exc)
            return json.dumps({"error": f"Web search failed: {exc}"})

        return json.dumps({"error": f"Unknown tool: {tool_name}"})
