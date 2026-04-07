"""WebSocket message handlers for the chat module.

Internal module — must not be imported from outside ``backend.modules.chat``.
"""

import asyncio
import logging
from datetime import datetime, timezone
from uuid import uuid4

from backend.modules.chat._inference import InferenceRunner
from backend.modules.chat._orchestrator import (
    _cancel_events,
    _make_tool_executor,
    emit_session_expired,
    run_inference,
    track_extraction_trigger,
)
from backend.modules.chat._prompt_assembler import assemble
from backend.modules.chat._repository import ChatRepository
from backend.token_counter import count_tokens
from backend.database import get_db
from backend.modules.bookmark import delete_bookmarks_for_message
from backend.modules.llm import (
    stream_completion as llm_stream_completion,
    get_model_supports_reasoning,
    LlmCredentialNotFoundError,
)
from backend.modules.persona import get_persona
from backend.modules.tools import get_active_definitions
from backend.ws.event_bus import get_event_bus
from shared.dtos.inference import CompletionMessage, CompletionRequest, ContentPart
from shared.events.chat import (
    ChatMessageDeletedEvent,
    ChatMessagesTruncatedEvent,
    ChatMessageUpdatedEvent,
    ChatSessionTitleUpdatedEvent,
    ChatStreamEndedEvent,
    ChatStreamErrorEvent,
)
from shared.topics import Topics

_log = logging.getLogger(__name__)

# Local runner instance for incognito sessions (stateless inference path)
_runner = InferenceRunner()


async def handle_chat_send(user_id: str, data: dict) -> None:
    """Handle a chat.send WebSocket message — save user message, run inference."""
    session_id = data.get("session_id")
    content_parts = data.get("content")
    if not session_id or not content_parts:
        return

    try:
        db = get_db()
        repo = ChatRepository(db)

        session = await repo.get_session(session_id, user_id)
        if not session:
            await emit_session_expired(user_id, session_id)
            return

        if session.get("state") != "idle":
            return

        text = "".join(
            part.get("text", "") for part in content_parts if part.get("type") == "text"
        ).strip()
        if not text:
            return

        # Resolve attachments if provided
        attachment_ids = data.get("attachment_ids")
        attachment_refs = None
        if attachment_ids:
            from backend.modules.storage import get_files_by_ids
            files = await get_files_by_ids(attachment_ids, user_id)
            attachment_refs = [
                {
                    "file_id": f["_id"],
                    "display_name": f["display_name"],
                    "media_type": f["media_type"],
                    "size_bytes": f["size_bytes"],
                    "thumbnail_b64": f.get("thumbnail_b64"),
                    "text_preview": f.get("text_preview"),
                }
                for f in files
            ]

        token_count = count_tokens(text)
        await repo.save_message(
            session_id,
            role="user",
            content=text,
            token_count=token_count,
            attachment_ids=attachment_ids,
            attachment_refs=attachment_refs,
        )

        # Track extraction trigger — skip for incognito sessions
        persona_id = session.get("persona_id")
        model_unique_id = session.get("model_unique_id", "")
        is_incognito = session.get("incognito", False) or (
            session_id and session_id.startswith("incognito-")
        )
        if persona_id and model_unique_id and not is_incognito:
            await track_extraction_trigger(
                user_id, persona_id, session_id, model_unique_id,
            )

        await run_inference(user_id, session_id, repo, session)
    except Exception:
        _log.exception("Unhandled error in handle_chat_send for user %s", user_id)


async def handle_chat_edit(user_id: str, data: dict) -> None:
    """Handle a chat.edit WebSocket message — truncate, update, re-infer."""
    session_id = data.get("session_id")
    message_id = data.get("message_id")
    content_parts = data.get("content")
    if not session_id or not message_id or not content_parts:
        return

    try:
        db = get_db()
        repo = ChatRepository(db)

        session = await repo.get_session(session_id, user_id)
        if not session:
            await emit_session_expired(user_id, session_id)
            return
        if session.get("state") != "idle":
            return

        # Validate message exists and belongs to this session
        messages = await repo.list_messages(session_id)
        target = None
        for msg in messages:
            if msg["_id"] == message_id:
                target = msg
                break

        if target is None or target["role"] != "user":
            return

        text = "".join(
            part.get("text", "") for part in content_parts if part.get("type") == "text"
        ).strip()
        if not text:
            return

        correlation_id = str(uuid4())
        now = datetime.now(timezone.utc)
        event_bus = get_event_bus()

        # Atomically truncate messages after the target and update its content
        token_count = count_tokens(text)
        ok = await repo.edit_message_atomic(session_id, message_id, text, token_count)
        if not ok:
            return

        await event_bus.publish(
            Topics.CHAT_MESSAGES_TRUNCATED,
            ChatMessagesTruncatedEvent(
                session_id=session_id,
                after_message_id=message_id,
                correlation_id=correlation_id,
                timestamp=now,
            ),
            scope=f"session:{session_id}",
            target_user_ids=[user_id],
            correlation_id=correlation_id,
        )

        await event_bus.publish(
            Topics.CHAT_MESSAGE_UPDATED,
            ChatMessageUpdatedEvent(
                session_id=session_id,
                message_id=message_id,
                content=text,
                token_count=token_count,
                correlation_id=correlation_id,
                timestamp=now,
            ),
            scope=f"session:{session_id}",
            target_user_ids=[user_id],
            correlation_id=correlation_id,
        )

        # Run inference
        await run_inference(user_id, session_id, repo, session)
    except Exception:
        _log.exception("Unhandled error in handle_chat_edit for user %s", user_id)


async def handle_chat_regenerate(user_id: str, data: dict) -> None:
    """Handle a chat.regenerate WebSocket message — delete last assistant msg, re-infer."""
    session_id = data.get("session_id")
    if not session_id:
        return

    try:
        db = get_db()
        repo = ChatRepository(db)

        session = await repo.get_session(session_id, user_id)
        if not session:
            await emit_session_expired(user_id, session_id)
            return
        if session.get("state") != "idle":
            return

        last_msg = await repo.get_last_message(session_id)
        if last_msg is None or last_msg["role"] != "assistant":
            return

        correlation_id = str(uuid4())
        now = datetime.now(timezone.utc)
        event_bus = get_event_bus()

        # Delete the last assistant message
        await repo.delete_message(last_msg["_id"])
        await delete_bookmarks_for_message(last_msg["_id"])

        await event_bus.publish(
            Topics.CHAT_MESSAGE_DELETED,
            ChatMessageDeletedEvent(
                session_id=session_id,
                message_id=last_msg["_id"],
                correlation_id=correlation_id,
                timestamp=now,
            ),
            scope=f"session:{session_id}",
            target_user_ids=[user_id],
            correlation_id=correlation_id,
        )

        # Run inference using existing last user message
        await run_inference(user_id, session_id, repo, session)
    except Exception:
        _log.exception("Unhandled error in handle_chat_regenerate for user %s", user_id)


def handle_chat_cancel(user_id: str, data: dict) -> None:
    """Handle a chat.cancel WebSocket message — signal cancellation."""
    correlation_id = data.get("correlation_id")
    if correlation_id and correlation_id in _cancel_events:
        _cancel_events[correlation_id].set()


async def update_session_title(session_id: str, title: str, user_id: str, correlation_id: str) -> None:
    """Update a session's title and publish the change event."""
    db = get_db()
    repo = ChatRepository(db)
    await repo.update_session_title(session_id, title)
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.CHAT_SESSION_TITLE_UPDATED,
        ChatSessionTitleUpdatedEvent(
            session_id=session_id,
            title=title,
            correlation_id=correlation_id,
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"session:{session_id}",
        target_user_ids=[user_id],
        correlation_id=correlation_id,
    )


async def handle_incognito_send(user_id: str, data: dict) -> None:
    """Handle a chat.incognito.send WebSocket message — stateless inference, nothing saved."""
    persona_id = data.get("persona_id")
    session_id = data.get("session_id")
    client_messages = data.get("messages")
    if not persona_id or not session_id or not client_messages:
        return

    try:
        persona = await get_persona(persona_id, user_id)
        if not persona:
            return

        model_unique_id = persona.get("model_unique_id", "")
        if ":" not in model_unique_id:
            _log.error("Invalid model_unique_id format: %s", model_unique_id)
            return

        provider_id, model_slug = model_unique_id.split(":", 1)

        supports_reasoning = await get_model_supports_reasoning(provider_id, model_slug)
        reasoning_enabled_for_call = persona.get("reasoning_enabled", False)

        # Assemble system prompt
        system_prompt = await assemble(
            user_id=user_id,
            persona_id=persona_id,
            model_unique_id=model_unique_id,
            supports_reasoning=supports_reasoning,
            reasoning_enabled_for_call=reasoning_enabled_for_call,
        )

        # Build CompletionMessage list
        messages: list[CompletionMessage] = []

        if system_prompt:
            messages.append(CompletionMessage(
                role="system",
                content=[ContentPart(type="text", text=system_prompt)],
            ))

        for msg in client_messages:
            messages.append(CompletionMessage(
                role=msg["role"],
                content=[ContentPart(type="text", text=msg["content"])],
            ))

        # Respect session-level tool group toggles (BD-038)
        db = get_db()
        repo = ChatRepository(db)
        session = await repo.get_session(session_id, user_id)
        disabled_tool_groups = session.get("disabled_tool_groups", []) if session else []
        active_tools = get_active_definitions(disabled_tool_groups) or None

        request = CompletionRequest(
            model=model_slug,
            messages=messages,
            temperature=persona.get("temperature"),
            reasoning_enabled=persona.get("reasoning_enabled", False),
            supports_reasoning=supports_reasoning,
            tools=active_tools,
        )

        correlation_id = str(uuid4())
        cancel_event = asyncio.Event()
        _cancel_events[correlation_id] = cancel_event

        event_bus = get_event_bus()

        async def emit_fn(event) -> None:
            event_dict = event.model_dump(mode="json")
            event_type = event_dict.get("type", "")

            await event_bus.publish(
                event_type,
                event,
                scope=f"session:{session_id}",
                target_user_ids=[user_id],
                correlation_id=correlation_id,
            )

        from backend.modules.chat._soft_cot import is_soft_cot_active
        from backend.modules.chat._soft_cot_parser import wrap_with_soft_cot_parser

        soft_cot_on = is_soft_cot_active(
            soft_cot_enabled=bool(persona.get("soft_cot_enabled")),
            supports_reasoning=supports_reasoning,
            reasoning_enabled=reasoning_enabled_for_call,
        )

        def stream_fn(extra_messages=None):
            req = request
            if extra_messages:
                extended = list(request.messages) + extra_messages
                req = request.model_copy(update={"messages": extended})
            upstream = llm_stream_completion(user_id, provider_id, req)
            if soft_cot_on:
                return wrap_with_soft_cot_parser(upstream)
            return upstream

        async def save_fn(
            content: str,
            thinking: str | None,
            usage: dict | None,
            web_search_context: list[dict] | None = None,
            knowledge_context: list[dict] | None = None,
        ) -> None:
            pass

        try:
            await _runner.run(
                user_id=user_id,
                session_id=session_id,
                correlation_id=correlation_id,
                stream_fn=stream_fn,
                emit_fn=emit_fn,
                save_fn=save_fn,
                cancel_event=cancel_event,
                context_status="green",
                context_fill_percentage=0.0,
                tool_executor_fn=_make_tool_executor(session, persona, correlation_id) if active_tools else None,
            )
        except LlmCredentialNotFoundError:
            now = datetime.now(timezone.utc)
            await emit_fn(ChatStreamErrorEvent(
                correlation_id=correlation_id,
                error_code="credential_not_found",
                recoverable=False,
                user_message="No API key configured for this model's provider. Please add one in settings.",
                timestamp=now,
            ))
            await emit_fn(ChatStreamEndedEvent(
                correlation_id=correlation_id,
                session_id=session_id,
                status="error",
                usage=None,
                context_status="green",
                context_fill_percentage=0.0,
                timestamp=now,
            ))
        finally:
            _cancel_events.pop(correlation_id, None)
    except Exception:
        _log.exception("Unhandled error in handle_incognito_send for user %s", user_id)
