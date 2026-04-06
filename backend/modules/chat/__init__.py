"""Chat module — sessions, messages, inference orchestration.

Public API: import only from this file.
"""

import asyncio
import logging
from datetime import datetime, timezone
from uuid import uuid4

from backend.modules.chat._handlers import router
from backend.modules.chat._inference import InferenceRunner
from backend.modules.chat._repository import ChatRepository
from backend.token_counter import count_tokens
from backend.modules.chat._prompt_assembler import assemble, assemble_preview
from backend.modules.chat._context import calculate_budget, select_message_pairs, get_ampel_status
from backend.jobs import submit, JobType
from backend.database import get_db, get_redis
from backend.modules.llm import (
    stream_completion as llm_stream_completion,
    get_effective_context_window,
    get_model_supports_vision,
    get_model_supports_reasoning,
    LlmCredentialNotFoundError,
)
from backend.modules.persona import get_persona
from backend.modules.bookmark import delete_bookmarks_for_message
from backend.modules.tools import execute_tool, get_active_definitions
from backend.ws.event_bus import get_event_bus
from backend.ws.manager import get_manager
from shared.dtos.inference import CompletionMessage, CompletionRequest, ContentPart
from shared.events.chat import (
    ChatContentDeltaEvent,
    ChatMessageDeletedEvent,
    ChatMessagesTruncatedEvent,
    ChatMessageUpdatedEvent,
    ChatSessionCreatedEvent,
    ChatSessionDeletedEvent,
    ChatSessionTitleUpdatedEvent,
    ChatStreamEndedEvent,
    ChatStreamErrorEvent,
    ChatStreamStartedEvent,
    ChatThinkingDeltaEvent,
)
from shared.topics import Topics

_log = logging.getLogger(__name__)

_runner = InferenceRunner()

# Active cancel events keyed by correlation_id
_cancel_events: dict[str, asyncio.Event] = {}

# In-flight idle extraction timers keyed by "user_id:persona_id"
_idle_extraction_tasks: dict[str, asyncio.Task] = {}

_DEFAULT_CONTEXT_WINDOW = 8192
_IDLE_EXTRACTION_DELAY_SECONDS = 300  # 5 minutes


async def init_indexes(db) -> None:
    """Create MongoDB indexes for the chat module collections."""
    await ChatRepository(db).create_indexes()


async def _run_inference(
    user_id: str,
    session_id: str,
    repo: ChatRepository,
    session: dict,
) -> None:
    """Shared inference path used by send, edit, and regenerate."""
    persona_id = session.get("persona_id")
    model_unique_id = session.get("model_unique_id", "")

    if ":" not in model_unique_id:
        _log.error("Invalid model_unique_id format: %s", model_unique_id)
        await repo.update_session_state(session_id, "idle")
        return

    provider_id, model_slug = model_unique_id.split(":", 1)

    # Assemble system prompt
    system_prompt = await assemble(
        user_id=user_id,
        persona_id=persona_id,
        model_unique_id=model_unique_id,
    )
    system_prompt_tokens = count_tokens(system_prompt) if system_prompt else 0

    # Get context window size (respects user override)
    max_context = await get_effective_context_window(user_id, provider_id, model_slug)
    if max_context is None or max_context == 0:
        max_context = _DEFAULT_CONTEXT_WINDOW

    # Load message history
    history_docs = await repo.list_messages(session_id)

    # The last message should be the user's new message
    new_msg_tokens = history_docs[-1]["token_count"] if history_docs else 0

    # Calculate budget (exclude the new user message from pair selection)
    budget = calculate_budget(
        max_context_tokens=max_context,
        system_prompt_tokens=system_prompt_tokens,
        new_message_tokens=new_msg_tokens,
    )

    # Check if context is full (pre-send check)
    all_history_tokens = sum(doc["token_count"] for doc in history_docs)
    total_tokens_used = system_prompt_tokens + all_history_tokens
    fill_ratio = total_tokens_used / max_context if max_context > 0 else 1.0

    if fill_ratio >= 0.8:
        correlation_id = str(uuid4())
        now = datetime.now(timezone.utc)
        manager = get_manager()
        await manager.send_to_user(user_id, ChatStreamErrorEvent(
            correlation_id=correlation_id,
            error_code="context_window_full",
            recoverable=False,
            user_message="Context window is full. Please start a new session.",
            timestamp=now,
        ).model_dump(mode="json"))
        await repo.update_session_state(session_id, "idle")
        return

    # Pair-based backread: select history pairs (exclude last user message)
    history_for_pairs = history_docs[:-1] if history_docs else []
    selected_history, _ = select_message_pairs(history_for_pairs, budget.available_for_chat)

    # Build messages for the LLM
    messages: list[CompletionMessage] = []

    if system_prompt:
        messages.append(CompletionMessage(
            role="system",
            content=[ContentPart(type="text", text=system_prompt)],
        ))

    for doc in selected_history:
        content_parts_list: list[ContentPart] = [ContentPart(type="text", text=doc["content"])]
        # Historical attachments get text placeholders instead of binary data
        refs = doc.get("attachment_refs")
        if refs:
            for ref in refs:
                content_parts_list.append(
                    ContentPart(type="text", text=f"\n[Attachment: {ref['display_name']}]")
                )
        messages.append(CompletionMessage(role=doc["role"], content=content_parts_list))

    # Append the new user message (with full attachment data if present)
    if history_docs:
        last_msg = history_docs[-1]
        last_msg_parts: list[ContentPart] = [ContentPart(type="text", text=last_msg["content"])]
        attachment_ids = last_msg.get("attachment_ids")
        if attachment_ids:
            from backend.modules.storage import get_files_by_ids
            supports_vision = await get_model_supports_vision(provider_id, model_slug)
            files = await get_files_by_ids(attachment_ids, user_id)
            for f in files:
                if f.get("data") and f["media_type"].startswith("image/"):
                    if not supports_vision:
                        last_msg_parts.append(ContentPart(
                            type="text",
                            text=f"\n[Image: {f['display_name']} — model does not support vision, image omitted]",
                        ))
                        continue
                    import base64
                    last_msg_parts.append(ContentPart(
                        type="image",
                        data=base64.b64encode(f["data"]).decode("ascii"),
                        media_type=f["media_type"],
                    ))
                elif f.get("data"):
                    text_content = f["data"].decode("utf-8", errors="replace")
                    last_msg_parts.append(ContentPart(
                        type="text",
                        text=f"\n--- {f['display_name']} ---\n{text_content}",
                    ))
        messages.append(CompletionMessage(role=last_msg["role"], content=last_msg_parts))

    # Get persona settings for temperature/reasoning
    persona = await get_persona(persona_id, user_id) if persona_id else None

    # Resolve active tool definitions based on session toggle state
    disabled_tool_groups = session.get("disabled_tool_groups", [])
    active_tools = get_active_definitions(disabled_tool_groups) or None

    # Resolve reasoning: session override > persona default
    reasoning_override = session.get("reasoning_override")
    if reasoning_override is not None:
        reasoning_enabled = reasoning_override
    else:
        reasoning_enabled = persona.get("reasoning_enabled", False) if persona else False

    supports_reasoning = await get_model_supports_reasoning(provider_id, model_slug)

    request = CompletionRequest(
        model=model_slug,
        messages=messages,
        temperature=persona.get("temperature") if persona else None,
        reasoning_enabled=reasoning_enabled,
        supports_reasoning=supports_reasoning,
        tools=active_tools,
    )

    # Set session state to streaming
    await repo.update_session_state(session_id, "streaming")

    correlation_id = str(uuid4())
    cancel_event = asyncio.Event()
    _cancel_events[correlation_id] = cancel_event

    manager = get_manager()
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

    def stream_fn(extra_messages=None):
        req = request
        if extra_messages:
            extended = list(request.messages) + extra_messages
            req = request.model_copy(update={"messages": extended})
        return llm_stream_completion(user_id, provider_id, req)

    async def save_fn(
        content: str,
        thinking: str | None,
        usage: dict | None,
        web_search_context: list[dict] | None = None,
    ) -> str | None:
        token_count = count_tokens(content)
        doc = await repo.save_message(
            session_id,
            role="assistant",
            content=content,
            token_count=token_count,
            thinking=thinking,
            web_search_context=web_search_context,
        )
        await repo.update_session_state(session_id, "idle")

        # Trigger title generation after first assistant response
        if not session.get("title"):
            msg_count = await repo.count_messages(session_id)
            if msg_count >= 2:
                messages = await repo.list_messages(session_id)
                first_user = next((m for m in messages if m["role"] == "user"), None)
                first_assistant = next((m for m in messages if m["role"] == "assistant"), None)
                if first_user and first_assistant:
                    await submit(
                        job_type=JobType.TITLE_GENERATION,
                        user_id=user_id,
                        model_unique_id=model_unique_id,
                        payload={
                            "session_id": session_id,
                            "messages": [
                                {"role": "user", "content": first_user["content"]},
                                {"role": "assistant", "content": first_assistant["content"]},
                            ],
                        },
                        correlation_id=correlation_id,
                    )

        return doc["_id"]

    # Calculate ampel status for the response
    context_status = get_ampel_status(fill_ratio)

    try:
        await _runner.run(
            user_id=user_id,
            session_id=session_id,
            correlation_id=correlation_id,
            stream_fn=stream_fn,
            emit_fn=emit_fn,
            save_fn=save_fn,
            cancel_event=cancel_event,
            context_status=context_status,
            context_fill_percentage=fill_ratio,
            tool_executor_fn=execute_tool if active_tools else None,
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
    except Exception as e:
        _log.error("Unexpected error in _run_inference for session %s: %s", session_id, e)
    finally:
        # Always reset to idle — covers success (idempotent), cancel, error,
        # and disconnect scenarios where the stream ends without exception.
        await repo.update_session_state(session_id, "idle")
        _cancel_events.pop(correlation_id, None)


async def _emit_session_expired(user_id: str, session_id: str) -> None:
    """Send a session_expired error event to the user."""
    now = datetime.now(timezone.utc)
    correlation_id = str(uuid4())
    manager = get_manager()
    await manager.send_to_user(user_id, ChatStreamErrorEvent(
        correlation_id=correlation_id,
        error_code="session_expired",
        recoverable=False,
        user_message="This chat session no longer exists. A new session will be created.",
        timestamp=now,
    ).model_dump(mode="json"))


async def _schedule_idle_extraction(
    user_id: str,
    persona_id: str,
    session_id: str,
    model_unique_id: str,
    idle_timestamp: str,
) -> None:
    """Wait for idle period, then submit memory extraction if user is still idle."""
    try:
        await asyncio.sleep(_IDLE_EXTRACTION_DELAY_SECONDS)

        redis = get_redis()
        tracking_key = f"memory:extraction:{user_id}:{persona_id}"
        current_ts = await redis.hget(tracking_key, "last_message_at")

        # User sent another message — a newer timer will handle extraction
        if current_ts != idle_timestamp:
            return

        # Fetch recent user messages for extraction
        db = get_db()
        repo = ChatRepository(db)
        messages = await repo.list_messages(session_id)
        user_messages = [
            m["content"] for m in messages
            if m["role"] == "user"
        ]

        if not user_messages:
            return

        # Take the last 20 user messages at most
        recent = user_messages[-20:]

        await submit(
            job_type=JobType.MEMORY_EXTRACTION,
            user_id=user_id,
            model_unique_id=model_unique_id,
            payload={
                "persona_id": persona_id,
                "session_id": session_id,
                "messages": recent,
            },
        )
        _log.info(
            "Submitted idle-triggered memory extraction for user %s, persona %s, session %s",
            user_id, persona_id, session_id,
        )
    except asyncio.CancelledError:
        pass
    except Exception:
        _log.exception(
            "Error in idle extraction timer for user %s, persona %s",
            user_id, persona_id,
        )
    finally:
        _idle_extraction_tasks.pop(f"{user_id}:{persona_id}", None)


async def _track_extraction_trigger(
    user_id: str,
    persona_id: str,
    session_id: str,
    model_unique_id: str,
) -> None:
    """Track message count and schedule idle-based extraction after a user message."""
    try:
        redis = get_redis()
        tracking_key = f"memory:extraction:{user_id}:{persona_id}"
        now_iso = datetime.now(timezone.utc).isoformat()

        await redis.hincrby(tracking_key, "messages_since_extraction", 1)
        await redis.hset(tracking_key, "last_message_at", now_iso)

        # Cancel any existing idle timer for this user+persona pair
        task_key = f"{user_id}:{persona_id}"
        old_task = _idle_extraction_tasks.pop(task_key, None)
        if old_task and not old_task.done():
            old_task.cancel()

        # Schedule new idle extraction timer
        task = asyncio.create_task(
            _schedule_idle_extraction(
                user_id, persona_id, session_id, model_unique_id, now_iso,
            )
        )
        _idle_extraction_tasks[task_key] = task
    except Exception:
        _log.exception(
            "Error tracking extraction trigger for user %s, persona %s",
            user_id, persona_id,
        )


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
            await _emit_session_expired(user_id, session_id)
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
            await _track_extraction_trigger(
                user_id, persona_id, session_id, model_unique_id,
            )

        await _run_inference(user_id, session_id, repo, session)
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
            await _emit_session_expired(user_id, session_id)
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
        await _run_inference(user_id, session_id, repo, session)
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
            await _emit_session_expired(user_id, session_id)
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
        await _run_inference(user_id, session_id, repo, session)
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

        # Assemble system prompt
        system_prompt = await assemble(
            user_id=user_id,
            persona_id=persona_id,
            model_unique_id=model_unique_id,
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

        supports_reasoning = await get_model_supports_reasoning(provider_id, model_slug)

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

        def stream_fn(extra_messages=None):
            req = request
            if extra_messages:
                extended = list(request.messages) + extra_messages
                req = request.model_copy(update={"messages": extended})
            return llm_stream_completion(user_id, provider_id, req)

        async def save_fn(
            content: str,
            thinking: str | None,
            usage: dict | None,
            web_search_context: list[dict] | None = None,
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
                tool_executor_fn=execute_tool if active_tools else None,
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


async def cleanup_stale_empty_sessions() -> int:
    """Delete empty sessions older than 24 hours. Returns count of deleted sessions."""
    from backend.modules.bookmark import delete_bookmarks_for_session
    db = get_db()
    repo = ChatRepository(db)
    stale_ids = await repo.delete_stale_empty_sessions(max_age_minutes=1440)
    if stale_ids:
        for sid in stale_ids:
            await delete_bookmarks_for_session(sid)
        _log.info("Cleaned up %d stale empty sessions", len(stale_ids))
    return len(stale_ids)


async def cleanup_soft_deleted_sessions() -> int:
    """Hard-delete sessions that were soft-deleted more than 1 hour ago. Returns count."""
    from backend.modules.bookmark import delete_bookmarks_for_session
    db = get_db()
    repo = ChatRepository(db)
    deleted_ids = await repo.hard_delete_expired_sessions(max_age_minutes=60)
    if deleted_ids:
        for sid in deleted_ids:
            await delete_bookmarks_for_session(sid)
        _log.info("Hard-deleted %d soft-deleted sessions", len(deleted_ids))
    return len(deleted_ids)


__all__ = [
    "router", "init_indexes",
    "handle_chat_send", "handle_chat_edit", "handle_chat_regenerate",
    "handle_chat_cancel", "handle_incognito_send", "update_session_title",
    "cleanup_stale_empty_sessions", "cleanup_soft_deleted_sessions", "assemble_preview",
]
