"""WebSocket message handlers for the chat module.

Internal module — must not be imported from outside ``backend.modules.chat``.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from uuid import uuid4

from backend.modules.chat._emoji_extractor import extract_emojis
from backend.modules.chat._inference import InferenceRunner
from backend.modules.chat._orchestrator import (
    _cancel_events,
    _cancel_user_ids,
    _consume_pending_cancel,
    _make_tool_executor,
    cancel_all_for_user,
    emit_session_expired,
    request_cancel,
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
    LlmConnectionNotFoundError,
)
from backend.modules.persona import get_persona
from backend.modules.tools import get_active_definitions
from backend.modules.user import UserService
from backend.ws.event_bus import get_event_bus
from shared.dtos.inference import CompletionMessage, CompletionRequest, ContentPart
from shared.events.chat import (
    ChatMessageCreatedEvent,
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

# Retracts can overtake their original chat.send because the websocket router
# runs chat.send in a background task. Keep a short-lived tombstone so a late
# send for the same correlation_id does not save or infer after the user has
# already barged it away.
_PENDING_RETRACT_TTL_SECONDS = 30.0
_pending_retracts: dict[str, tuple[str, str | None, float]] = {}


def _remember_retract(user_id: str, correlation_id: str, session_id: str | None) -> None:
    now = time.monotonic()
    expired = [
        cid for cid, (_, _, ts) in _pending_retracts.items()
        if now - ts > _PENDING_RETRACT_TTL_SECONDS
    ]
    for cid in expired:
        _pending_retracts.pop(cid, None)
    _pending_retracts[correlation_id] = (user_id, session_id, now)


def _consume_retract(user_id: str, correlation_id: str) -> tuple[bool, str | None]:
    item = _pending_retracts.get(correlation_id)
    if not item:
        return False, None
    owner_id, session_id, ts = item
    if time.monotonic() - ts > _PENDING_RETRACT_TTL_SECONDS:
        _pending_retracts.pop(correlation_id, None)
        return False, None
    if owner_id != user_id:
        return False, None
    _pending_retracts.pop(correlation_id, None)
    return True, session_id


async def _publish_message_deleted(
    *,
    user_id: str,
    session_id: str,
    message_id: str,
    correlation_id: str,
) -> None:
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.CHAT_MESSAGE_DELETED,
        ChatMessageDeletedEvent(
            session_id=session_id,
            message_id=message_id,
            correlation_id=correlation_id,
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"session:{session_id}",
        target_user_ids=[user_id],
        correlation_id=correlation_id,
    )


async def handle_chat_send(user_id: str, data: dict, *, connection_id: str | None = None) -> None:
    """Handle a chat.send WebSocket message — save user message, run inference."""
    session_id = data.get("session_id")
    content_parts = data.get("content")
    client_message_id = data.get("client_message_id")
    if not session_id or not content_parts:
        return

    try:
        db = get_db()
        repo = ChatRepository(db)

        session = await repo.get_session(session_id, user_id)
        if not session:
            await emit_session_expired(user_id, session_id)
            return

        text = "".join(
            part.get("text", "") for part in content_parts if part.get("type") == "text"
        ).strip()
        if not text:
            return

        correlation_id = data.get("correlation_id") or str(uuid4())

        was_retracted, retract_session_id = _consume_retract(user_id, correlation_id)
        if was_retracted:
            # The user barged before this background chat.send task reached
            # persistence/inference. Drop the send and delete the optimistic
            # client bubble so the UI does not keep a prompt that never ran.
            if client_message_id:
                await _publish_message_deleted(
                    user_id=user_id,
                    session_id=retract_session_id or session_id,
                    message_id=client_message_id,
                    correlation_id=correlation_id,
                )
            _log.info(
                "chat.send dropped because correlation_id=%s was already retracted",
                correlation_id,
            )
            return

        # Per-user single-stream policy: a new user action cancels any
        # in-flight inference the user still has running. The old run's
        # finally block will release the per-user inference lock shortly
        # after the cancel event fires; the new run_inference call below
        # then acquires it. Partially streamed content from the old run
        # is persisted by the runner (see _inference.py).
        cancelled = await cancel_all_for_user(user_id)
        if cancelled:
            _log.info(
                "chat.send cancelled %d in-flight inference(s) for user=%s",
                cancelled, user_id,
            )

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

        # PTI: inject any documents whose trigger phrases match this message.
        # Persona library IDs come from the persona doc; session library IDs
        # are read by get_pti_injections from the session itself.
        from backend.modules.knowledge import get_pti_injections, pti_index_cache

        persona_id_for_pti = session.get("persona_id")
        persona_library_ids: list[str] = []
        if persona_id_for_pti:
            persona_doc = await get_persona(persona_id_for_pti, user_id)
            if persona_doc:
                persona_library_ids = persona_doc.get("knowledge_library_ids") or []

        pti_items, pti_overflow = await get_pti_injections(
            db=db,
            cache=pti_index_cache,
            session_id=session_id,
            message=text,
            persona_library_ids=persona_library_ids,
        )

        knowledge_context_for_save = (
            [item.model_dump(mode="json") for item in pti_items] if pti_items else None
        )
        pti_overflow_for_save = (
            pti_overflow.model_dump(mode="json") if pti_overflow else None
        )

        saved_msg = await repo.save_message(
            session_id,
            role="user",
            content=text,
            token_count=token_count,
            knowledge_context=knowledge_context_for_save,
            pti_overflow=pti_overflow_for_save,
            attachment_ids=attachment_ids,
            attachment_refs=attachment_refs,
            correlation_id=correlation_id,
            user_id=user_id,
        )

        was_retracted, retract_session_id = _consume_retract(user_id, correlation_id)
        if was_retracted:
            await repo.delete_message(saved_msg["_id"])
            await _publish_message_deleted(
                user_id=user_id,
                session_id=retract_session_id or session_id,
                message_id=client_message_id or saved_msg["_id"],
                correlation_id=correlation_id,
            )
            _log.info(
                "chat.send saved then dropped because correlation_id=%s was retracted",
                correlation_id,
            )
            return

        event_bus = get_event_bus()
        await event_bus.publish(
            Topics.CHAT_MESSAGE_CREATED,
            ChatMessageCreatedEvent(
                session_id=session_id,
                message_id=saved_msg["_id"],
                role="user",
                content=text,
                token_count=token_count,
                correlation_id=correlation_id,
                timestamp=datetime.now(timezone.utc),
                client_message_id=client_message_id,
                knowledge_context=knowledge_context_for_save,
                pti_overflow=pti_overflow_for_save,
            ),
            scope=f"session:{session_id}",
            target_user_ids=[user_id],
            correlation_id=correlation_id,
        )

        was_retracted, _ = _consume_retract(user_id, correlation_id)
        if was_retracted:
            # handle_chat_retract already deleted the persisted message and
            # published the real-id delete event. Stop before extraction or
            # inference can resurrect work for the cancelled prompt.
            _log.info(
                "chat.send stopped before inference because correlation_id=%s was retracted",
                correlation_id,
            )
            return

        # Best-effort: refresh the user's recent-emoji LRU. Failures here must
        # never block the chat send — if Mongo or the event bus blip we log
        # and continue.
        try:
            emojis = extract_emojis(text)
            if emojis:
                user_service = UserService(db, event_bus)
                await user_service.touch_recent_emojis(user_id, emojis)
        except Exception as exc:
            _log.warning(
                "recent_emojis_update_failed user=%s error=%s",
                user_id, exc,
            )

        # Track extraction trigger — skip for incognito sessions
        persona_id = session.get("persona_id")
        is_incognito = session.get("incognito", False) or (
            session_id and session_id.startswith("incognito-")
        )
        if persona_id and not is_incognito:
            await track_extraction_trigger(
                user_id, persona_id, session_id,
            )

        was_retracted, _ = _consume_retract(user_id, correlation_id)
        if was_retracted:
            _log.info(
                "chat.send stopped after extraction tracking because correlation_id=%s was retracted",
                correlation_id,
            )
            return

        await run_inference(user_id, session_id, repo, session, connection_id=connection_id, correlation_id=correlation_id)
    except Exception:
        _log.exception("Unhandled error in handle_chat_send for user %s", user_id)


async def handle_chat_edit(user_id: str, data: dict, *, connection_id: str | None = None) -> None:
    """Handle a chat.edit WebSocket message — truncate, update, re-infer."""
    session_id = data.get("session_id")
    message_id = data.get("message_id")
    content_parts = data.get("content")
    # Synthetic correlation id we can attach to any rejection error so the
    # frontend can clear its "waiting for response" state. The happy path
    # generates its own below once we know the edit is going through.
    rejection_correlation_id = str(uuid4())

    async def _reject(code: str, message: str) -> None:
        """Emit a visible error instead of silently swallowing the edit.

        Every failure branch below used to ``return`` silently, leaving
        the UI stuck on its optimistic update with no way to recover.

        Requires a ``session_id`` — without it we have no scope to publish
        under and no tab to display the error in, so the caller must guard
        that case separately (see the early-return below).
        """
        event_bus = get_event_bus()
        await event_bus.publish(
            Topics.CHAT_STREAM_ERROR,
            ChatStreamErrorEvent(
                correlation_id=rejection_correlation_id,
                error_code=code,
                recoverable=False,
                user_message=message,
                timestamp=datetime.now(timezone.utc),
            ),
            scope=f"session:{session_id}",
            target_user_ids=[user_id],
            correlation_id=rejection_correlation_id,
        )
        _log.info(
            "Rejected chat.edit: user=%s session=%s message=%s code=%s",
            user_id, session_id, message_id, code,
        )

    if not session_id:
        # The client sent a chat.edit with no session id at all — we have
        # no scope to route an error event to and no UI tab to show it in.
        # Drop silently with a warning; this only happens for buggy clients.
        _log.warning(
            "Dropping chat.edit with no session_id: user=%s message=%s",
            user_id, message_id,
        )
        return
    if not message_id or not content_parts:
        await _reject("invalid_edit", "The edit request was malformed.")
        return

    try:
        db = get_db()
        repo = ChatRepository(db)

        session = await repo.get_session(session_id, user_id)
        if not session:
            await emit_session_expired(user_id, session_id)
            return

        # Per-user single-stream policy — see handle_chat_send.
        cancelled = await cancel_all_for_user(user_id)
        if cancelled:
            _log.info(
                "chat.edit cancelled %d in-flight inference(s) for user=%s",
                cancelled, user_id,
            )

        # Validate message exists and belongs to this session
        messages = await repo.list_messages(session_id)
        target = None
        for msg in messages:
            if msg["_id"] == message_id:
                target = msg
                break

        if target is None or target["role"] != "user":
            await _reject(
                "edit_target_missing",
                "The message you tried to edit was not found.",
            )
            return

        text = "".join(
            part.get("text", "") for part in content_parts if part.get("type") == "text"
        ).strip()
        if not text:
            await _reject("invalid_edit", "Cannot save an empty message.")
            return

        correlation_id = data.get("correlation_id") or str(uuid4())
        now = datetime.now(timezone.utc)
        event_bus = get_event_bus()

        # Atomically truncate messages after the target and update its content
        token_count = count_tokens(text)
        ok = await repo.edit_message_atomic(session_id, message_id, text, token_count)
        if not ok:
            await _reject(
                "edit_failed",
                "The message could not be saved. Please try again.",
            )
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
        await run_inference(user_id, session_id, repo, session, connection_id=connection_id, correlation_id=correlation_id)
    except Exception:
        _log.exception("Unhandled error in handle_chat_edit for user %s", user_id)


async def handle_chat_regenerate(user_id: str, data: dict, *, connection_id: str | None = None) -> None:
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

        # Per-user single-stream policy — see handle_chat_send.
        cancelled = await cancel_all_for_user(user_id)
        if cancelled:
            _log.info(
                "chat.regenerate cancelled %d in-flight inference(s) for user=%s",
                cancelled, user_id,
            )

        last_msg = await repo.get_last_message(session_id)
        if last_msg is None:
            return
        if last_msg["role"] not in ("assistant", "user"):
            return

        correlation_id = data.get("correlation_id") or str(uuid4())
        now = datetime.now(timezone.utc)
        event_bus = get_event_bus()

        if last_msg["role"] == "assistant":
            # Delete the last assistant message — we're going to replace it.
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
        # If last_msg is a user message, nothing to delete — just re-infer below.

        # Run inference using existing last user message
        await run_inference(user_id, session_id, repo, session, connection_id=connection_id, correlation_id=correlation_id)
    except Exception:
        _log.exception("Unhandled error in handle_chat_regenerate for user %s", user_id)


def handle_chat_cancel(user_id: str, data: dict) -> None:
    """Handle a chat.cancel WebSocket message — signal cancellation."""
    correlation_id = data.get("correlation_id")
    if correlation_id:
        request_cancel(correlation_id, user_id)


async def handle_chat_retract(user_id: str, data: dict) -> None:
    """Handle chat.retract — cancel in-flight inference and delete its user message.

    Used when the frontend cancels a response before any CONTENT_DELTA
    has arrived (the barge-before-delta case). The user message itself
    should disappear from history so the user is not left with a stray
    prompt bubble.
    """
    correlation_id = data.get("correlation_id")
    if not correlation_id:
        return

    session_id = data.get("session_id")
    _remember_retract(user_id, correlation_id, session_id)
    # Signal cancel first — stops in-flight inference even if the message is gone.
    # If run_inference has not registered its cancel_event yet, request_cancel
    # stores a pending tombstone that is consumed at registration time.
    request_cancel(correlation_id, user_id)

    try:
        db = get_db()
        repo = ChatRepository(db)

        user_message_id = await repo.user_message_by_correlation(user_id, correlation_id)
        if not user_message_id:
            _log.info(
                "chat.retract: no user message for correlation_id=%s",
                correlation_id,
            )
            return

        await repo.delete_message(user_message_id)

        await _publish_message_deleted(
            user_id=user_id,
            session_id=session_id or "",
            message_id=user_message_id,
            correlation_id=correlation_id,
        )
    except Exception:
        _log.exception("Unhandled error in handle_chat_retract for user %s", user_id)


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


async def handle_incognito_send(user_id: str, data: dict, *, connection_id: str | None = None) -> None:
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

        _, model_slug = model_unique_id.split(":", 1)

        supports_reasoning = await get_model_supports_reasoning(user_id, model_unique_id)
        reasoning_enabled_for_call = persona.get("reasoning_enabled", False)

        # Respect session-level tool toggle (BD-038). Reading this before the
        # prompt assembly so integration prompt extensions can be gated on it.
        db = get_db()
        repo = ChatRepository(db)
        session = await repo.get_session(session_id, user_id)
        tools_enabled = session.get("tools_enabled", False) if session else False
        active_tools = get_active_definitions([]) if tools_enabled else None

        # Assemble system prompt (integration prompt extensions follow tools_enabled)
        system_prompt = await assemble(
            user_id=user_id,
            persona_id=persona_id,
            model_unique_id=model_unique_id,
            supports_reasoning=supports_reasoning,
            reasoning_enabled_for_call=reasoning_enabled_for_call,
            tools_enabled=tools_enabled,
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

        request = CompletionRequest(
            model=model_slug,
            messages=messages,
            temperature=persona.get("temperature"),
            reasoning_enabled=persona.get("reasoning_enabled", False),
            supports_reasoning=supports_reasoning,
            tools=active_tools,
            cache_hint=session_id,
        )

        correlation_id = data.get("correlation_id") or str(uuid4())
        cancel_event = asyncio.Event()
        _cancel_events[correlation_id] = cancel_event
        _cancel_user_ids[correlation_id] = user_id
        if _consume_pending_cancel(correlation_id, user_id):
            cancel_event.set()

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
            upstream = llm_stream_completion(user_id, model_unique_id, req)
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
                tool_executor_fn=_make_tool_executor(session, persona, correlation_id, connection_id) if active_tools else None,
            )
        except LlmConnectionNotFoundError:
            now = datetime.now(timezone.utc)
            await emit_fn(ChatStreamErrorEvent(
                correlation_id=correlation_id,
                error_code="connection_not_found",
                recoverable=False,
                user_message="Connection not found — please select a model in the persona again.",
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
            _cancel_user_ids.pop(correlation_id, None)
    except Exception:
        _log.exception("Unhandled error in handle_incognito_send for user %s", user_id)
