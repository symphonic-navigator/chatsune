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


class KnowledgeSearchExecutor:
    """Dispatches knowledge_search tool calls to the knowledge retrieval module."""

    async def execute(self, user_id: str, tool_name: str, arguments: dict) -> str:
        from backend.modules.knowledge._retrieval import search

        try:
            query = arguments.get("query", "")
            if not query:
                return json.dumps({"error": "No query provided"})

            persona_library_ids = arguments.get("_persona_library_ids", [])
            session_library_ids = arguments.get("_session_library_ids", [])
            sanitised = arguments.get("_sanitised", False)

            session_id = arguments.get("_session_id", "")

            results = await search(
                user_id=user_id,
                query=query,
                persona_library_ids=persona_library_ids,
                session_library_ids=session_library_ids,
                sanitised=sanitised,
            )

            # Publish event for frontend pills
            if results:
                from datetime import datetime, timezone
                from uuid import uuid4
                from backend.ws.event_bus import get_event_bus
                from shared.events.knowledge import KnowledgeSearchCompletedEvent
                from shared.topics import Topics

                event_bus = get_event_bus()
                correlation_id = str(uuid4())
                await event_bus.publish(
                    Topics.KNOWLEDGE_SEARCH_COMPLETED,
                    KnowledgeSearchCompletedEvent(
                        session_id=session_id,
                        results=results,
                        correlation_id=correlation_id,
                        timestamp=datetime.now(timezone.utc),
                    ),
                    scope=f"user:{user_id}",
                    target_user_ids=[user_id],
                    correlation_id=correlation_id,
                )

            if not results:
                return json.dumps({"results": [], "message": "No relevant knowledge found."})

            return json.dumps(
                {"results": [r.model_dump() for r in results]},
                ensure_ascii=False,
            )

        except Exception as exc:
            _log.warning("Knowledge search failed for user %s: %s", user_id, exc)
            return json.dumps({"error": f"Knowledge search failed: {exc}"})
