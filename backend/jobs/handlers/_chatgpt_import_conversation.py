"""Per-conversation import job handler.

Reads one conversation document from ``chatgpt_import_conversations``,
parses its ``raw_data`` field, builds a CreateImportedSessionRequest,
calls the chat module's public ``create_imported_session`` API, then
records the link back into the conversation document and resets the
parent import's TTL.
"""
from __future__ import annotations

from datetime import UTC, datetime

import structlog

from backend.database import get_db
from backend.jobs._models import JobConfig, JobEntry
from backend.modules.chatgpt_import._parser import parse_conversation
from backend.modules.chatgpt_import._repository import ChatGptImportRepository
from backend.modules.chatgpt_import._session_builder import (
    build_imported_session_request,
)
from shared.events.chatgpt_import import (
    ChatGptImportConversationImportFailedEvent,
    ChatGptImportConversationImportedEvent,
)
from shared.topics import Topics

_log = structlog.get_logger(__name__)


async def handle_chatgpt_import_conversation(
    job: JobEntry,
    config: JobConfig,
    redis,
    event_bus,
) -> None:
    payload = job.payload
    user_id = payload["user_id"]
    import_id = payload["import_id"]
    chatgpt_conversation_id = payload["chatgpt_conversation_id"]
    persona_id = payload["persona_id"]
    correlation_id = payload.get("correlation_id") or job.correlation_id

    db = get_db()
    repo = ChatGptImportRepository(db)
    scope_import = f"chatgpt_import:{import_id}"
    scope_persona = f"persona:{persona_id}"

    async def _publish_failure(error_code: str, error_message: str) -> None:
        event = ChatGptImportConversationImportFailedEvent(
            import_id=import_id,
            chatgpt_conversation_id=chatgpt_conversation_id,
            persona_id=persona_id,
            error_code=error_code,
            error_message=error_message,
            correlation_id=correlation_id,
            timestamp=datetime.now(UTC),
        )
        await event_bus.publish(
            Topics.CHATGPT_IMPORT_CONVERSATION_IMPORT_FAILED,
            event,
            scope=scope_import,
            target_user_ids=[user_id],
            correlation_id=correlation_id,
        )

    conv_doc = await repo.get_conversation(
        user_id=user_id,
        import_id=import_id,
        chatgpt_conversation_id=chatgpt_conversation_id,
    )
    if not conv_doc:
        await _publish_failure(
            "conversation_not_found",
            "Conversation no longer in import",
        )
        return

    try:
        parsed = parse_conversation(conv_doc.get("raw_data") or {})
    except Exception as exc:  # noqa: BLE001
        _log.exception(
            "chatgpt_import.conversation.parse_failed",
            import_id=import_id,
            chatgpt_conversation_id=chatgpt_conversation_id,
        )
        await _publish_failure(type(exc).__name__, str(exc))
        return

    if not parsed.messages:
        await _publish_failure(
            "no_convertible_messages",
            "No user/assistant text after filtering",
        )
        return

    # Deferred import to break the circular dependency between the jobs
    # registry (which is imported during chat module bootstrap) and the
    # chat module's public API (which submits jobs).
    from backend.modules.chat import create_imported_session

    try:
        req = build_imported_session_request(parsed=parsed, persona_id=persona_id)
        session = await create_imported_session(
            user_id=user_id,
            persona_id=req.persona_id,
            title=req.title,
            messages=req.messages,
            imported_from=req.imported_from,
            imported_model_slug=req.imported_model_slug,
            original_created_at=req.original_created_at,
        )
    except Exception as exc:
        _log.exception(
            "chatgpt_import.conversation.create_failed",
            import_id=import_id,
            chatgpt_conversation_id=chatgpt_conversation_id,
        )
        await _publish_failure(type(exc).__name__, str(exc))
        raise

    session_id = str(session["_id"])
    await repo.record_import(
        import_id=import_id,
        chatgpt_conversation_id=chatgpt_conversation_id,
        persona_id=persona_id,
        session_id=session_id,
    )
    await repo.reset_ttl(import_id)

    imported_event = ChatGptImportConversationImportedEvent(
        import_id=import_id,
        chatgpt_conversation_id=chatgpt_conversation_id,
        persona_id=persona_id,
        session_id=session_id,
        title=parsed.title or "Imported conversation",
        correlation_id=correlation_id,
        timestamp=datetime.now(UTC),
    )
    # Publish on the import scope (ChatGPT-Import tab listens here) and on
    # the persona scope (history tabs / sidebar listen on persona:* to
    # refresh their session list when a new imported session lands).
    await event_bus.publish(
        Topics.CHATGPT_IMPORT_CONVERSATION_IMPORTED,
        imported_event,
        scope=scope_import,
        target_user_ids=[user_id],
        correlation_id=correlation_id,
    )
    await event_bus.publish(
        Topics.CHATGPT_IMPORT_CONVERSATION_IMPORTED,
        imported_event,
        scope=scope_persona,
        target_user_ids=[user_id],
        correlation_id=correlation_id,
    )
