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
        from backend.modules.knowledge import search

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


class ArtefactToolExecutor:
    """Dispatches artefact tool calls (create, update, read, list) to the artefact module."""

    async def execute(self, user_id: str, tool_name: str, arguments: dict) -> str:
        session_id = arguments.pop("_session_id", "")
        correlation_id = arguments.pop("_correlation_id", "")

        try:
            from backend.modules.artefact import (
                create_artefact,
                list_artefacts,
                read_artefact,
                update_artefact,
            )

            if tool_name == "create_artefact":
                # Normalise type to lowercase — some models return "HTML" / "Markdown"
                # despite the enum specifying lowercase, and the frontend preview
                # switch is strictly case-sensitive.
                raw_type = arguments.get("type", "") or ""
                result = await create_artefact(
                    user_id=user_id,
                    session_id=session_id,
                    handle=arguments.get("handle", ""),
                    title=arguments.get("title", ""),
                    artefact_type=raw_type.strip().lower(),
                    content=arguments.get("content", ""),
                    language=arguments.get("language"),
                    correlation_id=correlation_id,
                )
                return json.dumps(result)

            if tool_name == "update_artefact":
                result = await update_artefact(
                    user_id=user_id,
                    session_id=session_id,
                    handle=arguments.get("handle", ""),
                    content=arguments.get("content", ""),
                    title=arguments.get("title"),
                    correlation_id=correlation_id,
                )
                return json.dumps(result)

            if tool_name == "read_artefact":
                handle = arguments.get("handle", "")
                artefact = await read_artefact(session_id=session_id, handle=handle)
                if not artefact:
                    return json.dumps({"error": f"No artefact with handle '{handle}' found in this session."})
                return json.dumps({
                    "handle": artefact["handle"],
                    "title": artefact["title"],
                    "type": artefact["type"],
                    "language": artefact.get("language"),
                    "version": artefact.get("version", 1),
                    "size_bytes": artefact.get("size_bytes", 0),
                    "content": artefact["content"],
                }, ensure_ascii=False)

            if tool_name == "list_artefacts":
                artefacts = await list_artefacts(session_id=session_id)
                summary = [
                    {
                        "handle": a["handle"],
                        "title": a["title"],
                        "type": a["type"],
                        "language": a.get("language"),
                        "version": a.get("version", 1),
                        "size_bytes": a.get("size_bytes", 0),
                    }
                    for a in artefacts
                ]
                return json.dumps({"artefacts": summary}, ensure_ascii=False)

        except Exception as exc:
            _log.warning("Artefact tool '%s' failed for user %s: %s", tool_name, user_id, exc)
            return json.dumps({"error": f"Artefact tool failed: {exc}"})

        return json.dumps({"error": f"Unknown artefact tool: {tool_name}"})


_VALID_JOURNAL_CATEGORIES = {
    "preference", "fact", "relationship", "value",
    "insight", "projects", "creative",
}
_MAX_JOURNAL_CONTENT_LENGTH = 2000


class JournalToolExecutor:
    """Dispatches write_journal_entry tool calls to the memory module."""

    async def execute(self, user_id: str, tool_name: str, arguments: dict) -> str:
        if tool_name != "write_journal_entry":
            return json.dumps({"error": f"Unknown journal tool: {tool_name}"})

        content = arguments.get("content")
        category = arguments.get("category")
        persona_id = arguments.get("_persona_id")
        persona_name = arguments.get("_persona_name", "")
        session_id = arguments.get("_session_id")
        correlation_id = arguments.get("_correlation_id", "")

        # Validation — content
        if not isinstance(content, str) or not content.strip():
            return json.dumps({"error": "content must be a non-empty string"})
        if len(content) > _MAX_JOURNAL_CONTENT_LENGTH:
            return json.dumps({
                "error": (
                    f"content too long (max {_MAX_JOURNAL_CONTENT_LENGTH} "
                    "characters)"
                ),
            })

        # Validation — category
        if not isinstance(category, str) or category not in _VALID_JOURNAL_CATEGORIES:
            return json.dumps({
                "error": (
                    "category must be one of: preference, fact, relationship, "
                    "value, insight, projects, creative"
                ),
            })

        # Dispatch context — must be injected by the chat orchestrator
        if not persona_id or not session_id:
            _log.error(
                "write_journal_entry missing dispatch context: "
                "persona_id=%r session_id=%r correlation_id=%r",
                persona_id, session_id, correlation_id,
            )
            return json.dumps({"error": "internal: missing session context"})

        try:
            from backend.modules import memory as memory_mod

            dto = await memory_mod.write_persona_authored_entry(
                user_id=user_id,
                persona_id=persona_id,
                persona_name=persona_name,
                content=content,
                category=category,
                source_session_id=session_id,
                correlation_id=correlation_id,
            )
            return json.dumps({"status": "recorded", "entry_id": dto.id})

        except Exception as exc:
            _log.exception(
                "write_journal_entry failed for user=%s persona=%s correlation_id=%s: %s",
                user_id, persona_id, correlation_id, exc,
            )
            return json.dumps({"error": "failed to record entry"})
