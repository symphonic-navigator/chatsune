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
    _inflight,
    _consume_pending_cancel,
    _make_tool_executor,
    cancel_inflight_for_session,
    emit_session_expired,
    maybe_trigger_disconnect_extraction,
    request_cancel,
    run_inference,
    track_extraction_trigger,
)
from backend.modules.chat._prompt_assembler import assemble
from backend.modules.chat._repository import ChatRepository
from backend.token_counter import count_tokens
from backend.database import get_db, get_redis
from backend.modules.bookmark import delete_bookmarks_for_message
from backend.modules.llm import (
    stream_completion as llm_stream_completion,
    get_effective_context_window,
    get_model_metadata,
    LlmConnectionNotFoundError,
)
from backend.modules.chat._extras_remap import default_extras_for_capability
from shared.dtos.chat import ChatSessionExtras
from shared.dtos.llm import ReasoningCapability, ToolCapability
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


# Threshold mirrors the orchestrator's defence-in-depth check in
# ``_orchestrator.run_inference``: 80 % fill is the same red-ampel cutoff
# defined in ``_context.get_ampel_status``.
_CONTEXT_FULL_FILL_RATIO = 0.80
_DEFAULT_CONTEXT_WINDOW = 8192


async def _emit_stream_error(
    *,
    user_id: str,
    session_id: str,
    correlation_id: str,
    error_code: str,
    user_message: str,
    recoverable: bool,
) -> None:
    """Publish a ChatStreamErrorEvent under the session scope."""
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.CHAT_STREAM_ERROR,
        ChatStreamErrorEvent(
            correlation_id=correlation_id,
            error_code=error_code,
            recoverable=recoverable,
            user_message=user_message,
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"session:{session_id}",
        target_user_ids=[user_id],
        correlation_id=correlation_id,
    )


async def _compaction_lock_held(session_id: str) -> bool:
    """Return True iff a compaction job currently holds the session lock."""
    redis = get_redis()
    value = await redis.get(f"compaction:lock:{session_id}")
    return value is not None


async def _is_context_window_full(
    user_id: str,
    session: dict,
    new_message_tokens: int,
) -> bool:
    """Cheap pre-flight check — would adding this message push fill to >= 80 %.

    Uses ``session.context_used_tokens`` as the basis: that value is
    persisted at the end of each inference and already accounts for
    system prompt + history tokens at the previous turn. Adding the
    new user message tokens gives a conservative upper bound. The
    orchestrator runs the precise check after assembly as
    defence-in-depth — this one exists only to avoid persisting a
    user message that can never be answered.
    """
    persisted_used = int(session.get("context_used_tokens") or 0)
    if persisted_used <= 0:
        # Fresh session or pre-metric session — cannot evaluate. The
        # orchestrator's check still runs after history assembly.
        return False

    session_model = session.get("model_unique_id")
    if not session_model:
        persona_id = session.get("persona_id")
        if persona_id:
            persona = await get_persona(persona_id, user_id)
            session_model = (persona or {}).get("model_unique_id") or ""
    if not session_model:
        return False

    max_context = await get_effective_context_window(user_id, session_model)
    if not max_context:
        max_context = _DEFAULT_CONTEXT_WINDOW

    projected = persisted_used + max(0, int(new_message_tokens))
    fill_ratio = projected / max_context if max_context > 0 else 1.0
    return fill_ratio >= _CONTEXT_FULL_FILL_RATIO


async def _resolve_attachment_ids(
    attachment_ids: list[str],
    user_id: str,
) -> list[dict]:
    """Resolve a list of attachment IDs into attachment-ref dicts.

    Tries the storage module first. Any IDs not found there are looked up in
    the image service (generated images). IDs that exist in neither source
    are silently dropped — the message is still saved without them.

    Returns a list of dicts shaped to match ``AttachmentRefDto``.
    """
    from backend.modules.storage import get_files_by_ids

    storage_files = await get_files_by_ids(attachment_ids, user_id)
    found_ids = {f["_id"] for f in storage_files}

    refs: list[dict] = [
        {
            "file_id": f["_id"],
            "display_name": f["display_name"],
            "media_type": f["media_type"],
            "size_bytes": f["size_bytes"],
            "thumbnail_b64": f.get("thumbnail_b64"),
            "text_preview": f.get("text_preview"),
        }
        for f in storage_files
    ]

    missing_ids = [aid for aid in attachment_ids if aid not in found_ids]
    if missing_ids:
        _log.debug(
            "chat.attachment_resolve storage_miss ids=%s user=%s — trying image service",
            missing_ids, user_id,
        )
        try:
            from backend.modules.images import get_image_service
            image_service = get_image_service()
        except RuntimeError:
            # ImageService not initialised (test/script context) — skip silently.
            _log.debug(
                "chat.attachment_resolve image_service_not_initialised user=%s", user_id,
            )
            image_service = None

        if image_service is not None:
            for aid in missing_ids:
                detail = await image_service.get_image(user_id=user_id, image_id=aid)
                if detail is None:
                    _log.debug(
                        "chat.attachment_resolve not_found id=%s user=%s", aid, user_id,
                    )
                    continue

                _log.debug(
                    "chat.attachment_resolve image_found id=%s user=%s blob_url=%s",
                    aid, user_id, detail.blob_url,
                )
                refs.append({
                    "file_id": detail.id,
                    "display_name": detail.prompt or "Generated image",
                    "media_type": "image/jpeg",
                    "size_bytes": 0,
                    "thumbnail_b64": None,
                    "text_preview": None,
                })

    return refs


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

        # Per-session single-stream policy: a new user action cancels
        # the in-flight inference for *this session only*. Inferences
        # in other sessions (e.g. the user's other persona) keep
        # running in the background and persist when they finish.
        cancelled = await cancel_inflight_for_session(user_id, session_id)
        if cancelled:
            _log.info(
                "chat.send cancelled %d in-flight inference(s) for session=%s user=%s",
                cancelled, session_id, user_id,
            )

        # Compaction lock — refuse to persist while a compaction job
        # holds the session's lock. Doing so would race against the
        # checkpoint write and could send the LLM either pre- or
        # post-compact history depending on timing.
        if await _compaction_lock_held(session_id):
            await _emit_stream_error(
                user_id=user_id,
                session_id=session_id,
                correlation_id=correlation_id,
                error_code="compaction_in_progress",
                user_message=(
                    "A compaction is currently summarising this conversation. "
                    "Please retry in a moment."
                ),
                recoverable=True,
            )
            return

        # Resolve attachments if provided
        attachment_ids = data.get("attachment_ids")
        attachment_refs = None
        if attachment_ids:
            refs = await _resolve_attachment_ids(attachment_ids, user_id)
            attachment_refs = refs if refs else None

        token_count = count_tokens(text)

        # Context-window pre-flight — fire BEFORE persisting the user
        # message so a refusal does not leave an orphan turn at the tail
        # (which would then break pair-matching for every subsequent
        # attempt). The orchestrator's check stays in place as
        # defence-in-depth.
        if await _is_context_window_full(user_id, session, token_count):
            await _emit_stream_error(
                user_id=user_id,
                session_id=session_id,
                correlation_id=correlation_id,
                error_code="context_window_full",
                user_message=(
                    "This conversation has reached the model's context "
                    "limit. Compact the conversation or switch to a model "
                    "with a larger context window."
                ),
                recoverable=False,
            )
            return

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

        # Compaction lock — same reason as ``handle_chat_send``: refuse
        # to mutate history while a compaction job is rewriting the
        # checkpoint chain.
        if await _compaction_lock_held(session_id):
            await _reject(
                "compaction_in_progress",
                "A compaction is currently summarising this conversation. "
                "Please retry in a moment.",
            )
            return

        # Per-session single-stream policy: a new user action cancels
        # the in-flight inference for *this session only*. Inferences
        # in other sessions (e.g. the user's other persona) keep
        # running in the background and persist when they finish.
        cancelled = await cancel_inflight_for_session(user_id, session_id)
        if cancelled:
            _log.info(
                "chat.edit cancelled %d in-flight inference(s) for session=%s user=%s",
                cancelled, session_id, user_id,
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

        # Compaction edit guard — if the target message sits before the
        # latest compaction checkpoint's tail-start, the message lives in
        # the immutable compact snapshot and can no longer be edited.
        # The tail (created_at >= tail_start_msg.created_at) remains
        # editable. See spec §6.8.
        checkpoints = session.get("compaction_checkpoints") or []
        if checkpoints:
            latest = checkpoints[-1]
            tail_start_msg = await repo.get_message(latest["tail_start_message_id"])
            if (
                tail_start_msg is not None
                and target["created_at"] < tail_start_msg["created_at"]
            ):
                await _reject(
                    "edit_before_compact",
                    (
                        "This message is part of a compact snapshot and "
                        "can no longer be edited. Start a new session if "
                        "you need to go back further."
                    ),
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

        # Compaction lock — refuse regenerate while compaction is in
        # flight. A regenerate would delete the last assistant message
        # which may be part of the source range the compaction job is
        # currently summarising. Use the caller's correlation_id if
        # supplied so the optimistic frontend bubble clears cleanly.
        if await _compaction_lock_held(session_id):
            await _emit_stream_error(
                user_id=user_id,
                session_id=session_id,
                correlation_id=data.get("correlation_id") or str(uuid4()),
                error_code="compaction_in_progress",
                user_message=(
                    "A compaction is currently summarising this conversation. "
                    "Please retry in a moment."
                ),
                recoverable=True,
            )
            return

        # Per-session single-stream policy: a new user action cancels
        # the in-flight inference for *this session only*. Inferences
        # in other sessions (e.g. the user's other persona) keep
        # running in the background and persist when they finish.
        cancelled = await cancel_inflight_for_session(user_id, session_id)
        if cancelled:
            _log.info(
                "chat.regenerate cancelled %d in-flight inference(s) for session=%s user=%s",
                cancelled, session_id, user_id,
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
            await delete_bookmarks_for_message(last_msg["_id"], user_id)

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

        # Resolve the model capability so extras and the CompletionRequest
        # carry consistent reasoning/tools shapes — same pattern as the
        # main orchestrator (run_inference). Conservative fallback when
        # the model can no longer be resolved.
        meta = await get_model_metadata(user_id, model_unique_id)
        if meta is not None:
            reasoning_cap = meta.reasoning
            tools_cap = meta.tools
            supports_reasoning = meta.supports_reasoning
        else:
            reasoning_cap = ReasoningCapability(kind="no_reasoning")
            tools_cap = ToolCapability(supported=False)
            supports_reasoning = False

        # Respect session-level extras (or capability defaults if the
        # session predates the extras field). Reading this before the
        # prompt assembly so integration prompt extensions can be gated
        # on it.
        db = get_db()
        repo = ChatRepository(db)
        session = await repo.get_session(session_id, user_id)
        raw_extras = session.get("extras") if session else None
        if raw_extras is None:
            extras = default_extras_for_capability(reasoning_cap, tools_cap)
        else:
            extras = ChatSessionExtras.model_validate(raw_extras)

        active_tools = (
            await get_active_definitions([], user_id=user_id)
            if extras.tools_enabled else None
        )

        # Assemble system prompt — extras carries the tool/reasoning
        # state for prompt-level gating.
        system_prompt = await assemble(
            user_id=user_id,
            persona_id=persona_id,
            model_unique_id=model_unique_id,
            supports_reasoning=supports_reasoning,
            extras=extras,
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
            reasoning=reasoning_cap,
            tools_capability=tools_cap,
            extras=extras,
            tools=active_tools,
            cache_hint=session_id,
            anthropic_cache_ttl=persona.get("anthropic_cache_ttl", "5m"),
        )

        correlation_id = data.get("correlation_id") or str(uuid4())
        cancel_event = asyncio.Event()
        _cancel_events[correlation_id] = cancel_event
        _inflight[correlation_id] = (user_id, session_id)
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

        from backend.modules.chat._soft_cot_parser import wrap_with_soft_cot_parser

        def stream_fn(extra_messages=None):
            req = request
            if extra_messages:
                extended = list(request.messages) + extra_messages
                req = request.model_copy(update={"messages": extended})
            upstream = llm_stream_completion(user_id, model_unique_id, req)
            return wrap_with_soft_cot_parser(upstream)

        async def save_fn(
            content: str,
            thinking: str | None = None,
            usage: dict | None = None,
            events: list | None = None,
            refusal_text: str | None = None,
            status: str = "completed",
        ) -> None:
            # Incognito mode discards everything by design.
            return None

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
            _inflight.pop(correlation_id, None)
            try:
                await maybe_trigger_disconnect_extraction(user_id)
            except Exception:
                _log.warning(
                    "maybe_trigger_disconnect_extraction raised in handle_incognito_send finally for user=%s",
                    user_id, exc_info=True,
                )
    except Exception:
        _log.exception("Unhandled error in handle_incognito_send for user %s", user_id)


async def _emit_compaction_failed(
    event_bus,
    session_id: str,
    correlation_id: str,
    user_id: str,
    *,
    error_code: str,
    user_message: str,
    recoverable: bool,
) -> None:
    """Publish a ChatCompactionFailedEvent — used by the trigger handler.

    Deferred imports mirror the rest of this file's pattern (heavy chat /
    shared modules are pulled in lazily where they would otherwise cause
    circular imports through ``backend.modules.chat.__init__``).
    """
    from shared.events.chat import ChatCompactionFailedEvent

    await event_bus.publish(
        Topics.CHAT_COMPACTION_FAILED,
        ChatCompactionFailedEvent(
            session_id=session_id,
            correlation_id=correlation_id,
            error_code=error_code,
            user_message=user_message,
            recoverable=recoverable,
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"session:{session_id}",
        target_user_ids=[user_id],
        correlation_id=correlation_id,
    )


async def handle_chat_compaction_request(
    user_id: str, data: dict, *, connection_id: str | None = None,
) -> None:
    """Handle a chat.compaction.request WebSocket message — trigger a
    compaction job. See spec §6.1.

    Signature mirrors the other ``handle_chat_*`` handlers in this file so
    the WS router can dispatch all of them uniformly. ``connection_id`` is
    currently unused — the job runs against the session, not the WS
    connection — but is accepted to keep the dispatch contract uniform.
    """
    from backend.database import get_redis

    session_id = data.get("session_id")
    if not session_id:
        return

    correlation_id = data.get("correlation_id") or str(uuid4())
    event_bus = get_event_bus()

    # Sentinels for the lock-leak safety net at the bottom of this
    # function. ``lock_key`` is only set once we have actually acquired
    # the lock; ``lock_handed_off`` flips to ``True`` once the job is
    # successfully queued so the outer except knows the job's
    # ``finally`` will release the lock instead.
    lock_key: str | None = None
    lock_handed_off = False

    try:
        db = get_db()
        repo = ChatRepository(db)

        session = await repo.get_session(session_id, user_id)
        if session is None:
            # Ownership / not-found — silent, no event to route.
            return

        # Minimum-size check — refuses tiny sessions outright.
        total_messages = await repo.count_messages(session_id)
        total_tokens = int(session.get("context_used_tokens") or 0)
        if total_messages <= 12 or total_tokens < 4000:
            await _emit_compaction_failed(
                event_bus, session_id, correlation_id, user_id,
                error_code="too_small", recoverable=False,
                user_message="Conversation too short to compact yet.",
            )
            return

        # Lower threshold — refuse to compact sessions that haven't filled
        # at least 30 % of the model's context window yet (no benefit).
        fill = float(session.get("context_fill_percentage") or 0.0)
        if fill < 0.30:
            await _emit_compaction_failed(
                event_bus, session_id, correlation_id, user_id,
                error_code="below_threshold", recoverable=False,
                user_message=(
                    "Conversation is not large enough to benefit from "
                    "compaction yet."
                ),
            )
            return

        # Idempotency lock — refuses concurrent compactions for the same
        # session. The job handler releases the lock in its ``finally``
        # block; the trigger handler does NOT release on success.
        redis = get_redis()
        candidate_lock_key = f"compaction:lock:{session_id}"
        acquired = await redis.set(candidate_lock_key, correlation_id, nx=True, ex=600)
        if not acquired:
            await _emit_compaction_failed(
                event_bus, session_id, correlation_id, user_id,
                error_code="already_running", recoverable=True,
                user_message=(
                    "A compaction is already running for this conversation."
                ),
            )
            return
        # Lock is now ours — promote it to the outer-scope sentinel so
        # the bottom-of-function safety net knows there is a lock to
        # release if anything below raises before ``submit_job`` lands.
        lock_key = candidate_lock_key

        # Pre-flight: compute the source range using the same helpers the
        # job handler uses, so a session that cannot possibly compact is
        # rejected up front (without paying for a queued job that would
        # then fail at the LLM boundary). On any error path past this
        # point the lock must be released — see ``await redis.delete(...)``
        # calls below.
        from backend.modules.chat._compaction import (
            COMPACTION_MAX_OUTPUT_TOKENS,
            COMPACTION_SAFETY_MARGIN,
            COMPACTION_SYSTEM_PROMPT_TOKENS,
            determine_tail_start_index,
            sanitise_source,
            select_source_range,
        )
        from backend.modules.llm import get_effective_context_window

        model_unique_id = session.get("model_unique_id") or ""
        if not model_unique_id:
            # Session has no per-session model override — fall back to
            # the persona's default model.
            from backend.modules.persona import get_persona

            persona = await get_persona(session.get("persona_id"), user_id)
            model_unique_id = (persona or {}).get("model_unique_id", "")

        model_context = (
            await get_effective_context_window(user_id, model_unique_id)
            or 8192
        )

        all_messages = await repo.list_messages(session_id)

        checkpoints = session.get("compaction_checkpoints") or []
        prev_checkpoint_id = checkpoints[-1]["id"] if checkpoints else None
        prev_tail_start_id = (
            checkpoints[-1]["tail_start_message_id"] if checkpoints else None
        )

        try:
            tail_start_idx = determine_tail_start_index(
                all_messages, model_context=model_context,
            )
            source_raw, tail_msgs = select_source_range(
                all_messages,
                tail_start_index=tail_start_idx,
                prev_tail_start_id=prev_tail_start_id,
            )
        except ValueError:
            # Previous checkpoint references a message that no longer
            # exists. Same condition the job handler reports — surface
            # it now to avoid queueing a doomed job.
            await redis.delete(lock_key)
            _log.exception(
                "compaction.stale_prev_checkpoint session=%s correlation_id=%s",
                session_id, correlation_id,
            )
            await _emit_compaction_failed(
                event_bus, session_id, correlation_id, user_id,
                error_code="stale_prev_checkpoint", recoverable=False,
                user_message=(
                    "The previous compact snapshot references a message "
                    "that no longer exists. Start a new conversation to "
                    "compact again."
                ),
            )
            return

        source_msgs = sanitise_source(source_raw)
        source_tokens = sum(
            int(m.get("token_count") or 0) for m in source_msgs
        )

        # Re-compact guard: when the conversation hasn't grown since the
        # last checkpoint, source_msgs is empty and there is nothing
        # meaningful to summarise. Reject the trigger with a clear
        # message instead of running the LLM on an empty transcript.
        if prev_checkpoint_id and source_tokens < 200:
            await redis.delete(lock_key)
            await _emit_compaction_failed(
                event_bus, session_id, correlation_id, user_id,
                error_code="too_small", recoverable=False,
                user_message=(
                    "Nothing new to compact since the last snapshot — "
                    "continue the conversation and try again later."
                ),
            )
            return

        overhead = (
            COMPACTION_SYSTEM_PROMPT_TOKENS
            + COMPACTION_MAX_OUTPUT_TOKENS
            + COMPACTION_SAFETY_MARGIN
        )
        if source_tokens + overhead > model_context:
            await redis.delete(lock_key)
            await _emit_compaction_failed(
                event_bus, session_id, correlation_id, user_id,
                error_code="compaction_source_too_large", recoverable=False,
                user_message=(
                    "Conversation is too large for the current model to "
                    "compact. Switch to a model with a larger context "
                    "window or start a new session."
                ),
            )
            return

        # Submit the job. Heuristic for the estimated post-compact size:
        # compaction targets 5–10 % of source token count, floored at 500
        # so the UI does not show 0 for tiny sessions.
        from backend.jobs._models import JobType
        from backend.jobs._submit import submit as submit_job
        from shared.events.chat import ChatCompactionStartedEvent

        estimated_after = max(500, int(source_tokens * 0.08))

        await submit_job(
            job_type=JobType.CHAT_COMPACTION,
            user_id=user_id,
            model_unique_id=model_unique_id,
            payload={
                "session_id": session_id,
                "correlation_id": correlation_id,
                "prev_checkpoint_id": prev_checkpoint_id,
            },
            correlation_id=correlation_id,
        )
        # Job is queued — its ``finally`` block now owns lock release.
        lock_handed_off = True

        await event_bus.publish(
            Topics.CHAT_COMPACTION_STARTED,
            ChatCompactionStartedEvent(
                session_id=session_id,
                correlation_id=correlation_id,
                tokens_before=source_tokens,
                estimated_tokens_after=estimated_after,
                tail_message_count=len(tail_msgs),
                timestamp=datetime.now(timezone.utc),
            ),
            scope=f"session:{session_id}",
            target_user_ids=[user_id],
            correlation_id=correlation_id,
        )
    except Exception:
        _log.exception(
            "Unhandled error in handle_chat_compaction_request for user %s",
            user_id,
        )
        # Safety net: if anything between lock acquisition and a
        # successful ``submit_job`` raised, release the lock so the
        # user can retry without waiting for the 600 s TTL to expire.
        if lock_key and not lock_handed_off:
            try:
                await get_redis().delete(lock_key)
            except Exception:
                _log.exception(
                    "compaction.lock_release_failed session=%s",
                    session_id,
                )
