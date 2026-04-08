"""Inference orchestration and supporting helpers for the chat module.

Internal module — must not be imported from outside ``backend.modules.chat``.
"""

import asyncio
import base64
import json
import logging
import time
from datetime import datetime, timezone
from uuid import uuid4

from backend.modules.chat._inference import InferenceRunner
from backend.modules.chat._repository import ChatRepository
from backend.modules.chat._vision_fallback import describe_image, VisionFallbackError
from backend.token_counter import count_tokens
from backend.modules.chat._prompt_assembler import assemble
from backend.modules.chat._context import calculate_budget, select_message_pairs, get_ampel_status
from backend.jobs import (
    JobType,
    memory_extraction_slot_key,
    submit,
    try_acquire_inflight_slot,
)
from backend.jobs._disconnect_retry import buffer_submit_payload
from backend.database import get_db, get_redis
from backend.modules.llm import (
    stream_completion as llm_stream_completion,
    get_effective_context_window,
    get_model_supports_vision,
    get_model_supports_reasoning,
    LlmCredentialNotFoundError,
)
from backend.modules.persona import get_persona
from backend.modules.storage import (
    get_files_by_ids,
    get_cached_vision_description,
    store_vision_description,
)
from backend.modules.tools import execute_tool, get_active_definitions
from backend.ws.event_bus import get_event_bus
from backend.ws.manager import get_manager
from shared.dtos.inference import CompletionMessage, CompletionRequest, ContentPart
from shared.events.chat import (
    ChatStreamEndedEvent,
    ChatStreamErrorEvent,
    ChatVisionDescriptionEvent,
)

_log = logging.getLogger(__name__)

_runner = InferenceRunner()

# Active cancel events keyed by correlation_id
_cancel_events: dict[str, asyncio.Event] = {}

# Heartbeat bookkeeping for auto-cancelling orphaned inferences. The frontend
# pings ``chat.inference.alive`` while the user is actively watching a stream;
# if pings stop arriving (tab closed, network drop, reload) the watchdog sets
# the cancel event so the inference tears itself down cleanly.
_last_heartbeat: dict[str, float] = {}          # correlation_id -> monotonic timestamp
_cancel_user_ids: dict[str, str] = {}           # correlation_id -> user_id
_heartbeat_watchdogs: dict[str, asyncio.Task] = {}

# Guards concurrent mutation of the four dicts above. See BACKGROUND-JOBS-DEBT.md
# C-002: record_heartbeat, the watchdog loop, cancel_all_for_user and the
# run_inference finally block all mutate these dicts from different tasks,
# causing KeyError races. Never await anything unrelated while holding this
# lock — take a snapshot inside and do I/O outside.
_heartbeat_lock = asyncio.Lock()

# In-flight idle extraction timers keyed by "user_id:persona_id"
_idle_extraction_tasks: dict[str, asyncio.Task] = {}

_DEFAULT_CONTEXT_WINDOW = 8192
_IDLE_EXTRACTION_DELAY_SECONDS = 300  # 5 minutes
_HEARTBEAT_TIMEOUT_SECONDS = 30.0
_HEARTBEAT_CHECK_INTERVAL_SECONDS = 2.0


async def _heartbeat_watchdog(correlation_id: str) -> None:
    """Cancel the inference if no heartbeat arrives within the timeout window.

    Polls every ``_HEARTBEAT_CHECK_INTERVAL_SECONDS``. Exits silently once the
    correlation id is removed from ``_last_heartbeat`` (normal completion) or
    when the task itself is cancelled by the orchestrator's finally block.
    """
    try:
        while True:
            await asyncio.sleep(_HEARTBEAT_CHECK_INTERVAL_SECONDS)
            async with _heartbeat_lock:
                last = _last_heartbeat.get(correlation_id)
            if last is None:
                return
            if time.monotonic() - last > _HEARTBEAT_TIMEOUT_SECONDS:
                _log.warning(
                    "Heartbeat timeout for inference %s - cancelling",
                    correlation_id,
                )
                async with _heartbeat_lock:
                    event = _cancel_events.get(correlation_id)
                if event is not None:
                    event.set()
                return
    except asyncio.CancelledError:
        pass


async def record_heartbeat(user_id: str, correlation_id: str) -> bool:
    """Refresh the heartbeat timestamp for an active inference.

    Also verifies that the caller owns the inference. Without the user-id
    check a malicious client could keep someone else's inference alive (or at
    least spoof heartbeats) by guessing correlation ids, so we bind each id
    to its originating user at inference start.
    """
    async with _heartbeat_lock:
        owner = _cancel_user_ids.get(correlation_id)
        if owner is None or owner != user_id:
            return False
        _last_heartbeat[correlation_id] = time.monotonic()
        return True


async def cancel_all_for_user(user_id: str) -> int:
    """Cancel every in-flight inference belonging to the given user.

    Used on WebSocket disconnect to avoid burning tokens on a response the
    user will never see. Returns the number of inferences signalled.
    """
    # Snapshot targets + their events under the lock, then fire event.set()
    # outside the lock — Event.set() is synchronous but we still avoid holding
    # the lock across any unnecessary work.
    async with _heartbeat_lock:
        targets = [cid for cid, uid in _cancel_user_ids.items() if uid == user_id]
        events = [_cancel_events.get(cid) for cid in targets]
    for event in events:
        if event is not None:
            event.set()
    return len(targets)


def _make_tool_executor(session: dict, persona: dict | None, correlation_id: str = ""):
    """Wrap execute_tool to inject knowledge library IDs for knowledge_search and session context for artefact tools."""
    persona_lib_ids = (persona or {}).get("knowledge_library_ids", [])
    session_lib_ids = session.get("knowledge_library_ids", [])
    sanitised = session.get("sanitised", False)

    async def _executor(user_id: str, tool_name: str, arguments_json: str) -> str:
        if tool_name == "knowledge_search":
            args = json.loads(arguments_json)
            args["_persona_library_ids"] = persona_lib_ids
            args["_session_library_ids"] = session_lib_ids
            args["_sanitised"] = sanitised
            args["_session_id"] = session.get("_id", "")
            arguments_json = json.dumps(args)

        artefact_tools = {"create_artefact", "update_artefact", "read_artefact", "list_artefacts"}
        if tool_name in artefact_tools:
            args = json.loads(arguments_json)
            args["_session_id"] = session.get("_id", "")
            args["_correlation_id"] = correlation_id
            arguments_json = json.dumps(args)

        return await execute_tool(user_id, tool_name, arguments_json)

    return _executor


async def _resolve_image_attachments_for_inference(
    *,
    user_id: str,
    files: list[dict],
    supports_vision: bool,
    vision_fallback_model: str | None,
    emit_event,
    correlation_id: str,
) -> tuple[list[ContentPart], list[dict], None]:
    """Convert a list of file dicts into ContentParts plus vision snapshots.

    Returns ``(parts, snapshots, _)``. The third element is currently unused
    and reserved for future extensions. Snapshots are dicts with keys
    ``file_id, display_name, model_id, text``.

    For each image attachment:
      1. If the main model supports vision: pass through as an image part.
      2. Else if no fallback configured: emit a placeholder text part.
      3. Else if cache hit: emit a text part from the cache + snapshot +
         single success event.
      4. Else: emit pending event, call describe_image, on success store +
         snapshot + success event, on failure emit error event and use a
         placeholder text part with an error marker.

    Non-image attachments are converted to text parts as in the previous
    inline implementation.
    """
    parts: list[ContentPart] = []
    snapshots: list[dict] = []

    for f in files:
        if f.get("data") and f["media_type"].startswith("image/"):
            if supports_vision:
                parts.append(ContentPart(
                    type="image",
                    data=base64.b64encode(f["data"]).decode("ascii"),
                    media_type=f["media_type"],
                ))
                continue

            if not vision_fallback_model:
                parts.append(ContentPart(
                    type="text",
                    text=f"\n[Image: {f['display_name']} — model does not support vision, image omitted]",
                ))
                continue

            cached = await get_cached_vision_description(
                f["_id"], user_id, vision_fallback_model,
            )
            now = datetime.now(timezone.utc)
            if cached:
                parts.append(ContentPart(
                    type="text",
                    text=f"\n[Image description for {f['display_name']} (via {vision_fallback_model}):\n{cached}\n]",
                ))
                snapshots.append({
                    "file_id": f["_id"],
                    "display_name": f["display_name"],
                    "model_id": vision_fallback_model,
                    "text": cached,
                })
                await emit_event(ChatVisionDescriptionEvent(
                    correlation_id=correlation_id,
                    file_id=f["_id"],
                    display_name=f["display_name"],
                    model_id=vision_fallback_model,
                    status="success",
                    text=cached,
                    error=None,
                    timestamp=now,
                ))
                continue

            # Cache miss — announce pending, then call the vision model.
            await emit_event(ChatVisionDescriptionEvent(
                correlation_id=correlation_id,
                file_id=f["_id"],
                display_name=f["display_name"],
                model_id=vision_fallback_model,
                status="pending",
                text=None,
                error=None,
                timestamp=now,
            ))
            try:
                text = await describe_image(
                    user_id, vision_fallback_model, f["data"], f["media_type"],
                )
            except VisionFallbackError as exc:
                _log.warning(
                    "vision fallback failed for file=%s model=%s: %s",
                    f["_id"], vision_fallback_model, exc,
                )
                parts.append(ContentPart(
                    type="text",
                    text=f"\n[Image: {f['display_name']} — vision fallback failed]",
                ))
                await emit_event(ChatVisionDescriptionEvent(
                    correlation_id=correlation_id,
                    file_id=f["_id"],
                    display_name=f["display_name"],
                    model_id=vision_fallback_model,
                    status="error",
                    text=None,
                    error=str(exc),
                    timestamp=datetime.now(timezone.utc),
                ))
                continue

            await store_vision_description(
                f["_id"], user_id, vision_fallback_model, text,
            )
            parts.append(ContentPart(
                type="text",
                text=f"\n[Image description for {f['display_name']} (via {vision_fallback_model}):\n{text}\n]",
            ))
            snapshots.append({
                "file_id": f["_id"],
                "display_name": f["display_name"],
                "model_id": vision_fallback_model,
                "text": text,
            })
            await emit_event(ChatVisionDescriptionEvent(
                correlation_id=correlation_id,
                file_id=f["_id"],
                display_name=f["display_name"],
                model_id=vision_fallback_model,
                status="success",
                text=text,
                error=None,
                timestamp=datetime.now(timezone.utc),
            ))

        elif f.get("data"):
            text_content = f["data"].decode("utf-8", errors="replace")
            parts.append(ContentPart(
                type="text",
                text=f"\n--- {f['display_name']} ---\n{text_content}",
            ))

    return parts, snapshots, None


async def run_inference(
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

    # Resolve persona and reasoning context early so the prompt assembler
    # can decide whether to inject the Soft-CoT block.
    persona = await get_persona(persona_id, user_id) if persona_id else None
    reasoning_override = session.get("reasoning_override")
    if reasoning_override is not None:
        reasoning_enabled = reasoning_override
    else:
        reasoning_enabled = persona.get("reasoning_enabled", False) if persona else False
    supports_reasoning = await get_model_supports_reasoning(provider_id, model_slug)

    # Assemble system prompt
    system_prompt = await assemble(
        user_id=user_id,
        persona_id=persona_id,
        model_unique_id=model_unique_id,
        supports_reasoning=supports_reasoning,
        reasoning_enabled_for_call=reasoning_enabled,
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
        # Feed back stored vision snapshots so the model has consistent context
        snaps = doc.get("vision_descriptions_used")
        if snaps:
            for s in snaps:
                content_parts_list.append(
                    ContentPart(
                        type="text",
                        text=f"\n[Image description for {s['display_name']} (via {s['model_id']}):\n{s['text']}\n]",
                    )
                )
        messages.append(CompletionMessage(role=doc["role"], content=content_parts_list))

    # Set up correlation ID and event emission BEFORE building messages so
    # that _resolve_image_attachments_for_inference can emit vision
    # description events from inside the attachment loop.
    correlation_id = str(uuid4())
    cancel_event = asyncio.Event()
    watchdog_task = asyncio.create_task(_heartbeat_watchdog(correlation_id))
    async with _heartbeat_lock:
        _cancel_events[correlation_id] = cancel_event
        _last_heartbeat[correlation_id] = time.monotonic()
        _cancel_user_ids[correlation_id] = user_id
        _heartbeat_watchdogs[correlation_id] = watchdog_task

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

    # Append the new user message (with full attachment data if present)
    if history_docs:
        last_msg = history_docs[-1]
        last_msg_parts: list[ContentPart] = [ContentPart(type="text", text=last_msg["content"])]
        new_msg_vision_snapshots: list[dict] = []
        attachment_ids = last_msg.get("attachment_ids")
        if attachment_ids:
            supports_vision = await get_model_supports_vision(provider_id, model_slug)
            files = await get_files_by_ids(attachment_ids, user_id)
            vision_fallback_model = persona.get("vision_fallback_model") if persona else None
            extra_parts, new_msg_vision_snapshots, _ = await _resolve_image_attachments_for_inference(
                user_id=user_id,
                files=files,
                supports_vision=supports_vision,
                vision_fallback_model=vision_fallback_model,
                emit_event=emit_fn,
                correlation_id=correlation_id,
            )
            last_msg_parts.extend(extra_parts)
            if new_msg_vision_snapshots:
                await repo.update_message_vision_snapshots(
                    last_msg["_id"], new_msg_vision_snapshots,
                )
        messages.append(CompletionMessage(role=last_msg["role"], content=last_msg_parts))

    # Resolve active tool definitions based on session toggle state
    disabled_tool_groups = session.get("disabled_tool_groups", [])
    active_tools = get_active_definitions(disabled_tool_groups) or None

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

    from backend.modules.chat._soft_cot import is_soft_cot_active
    from backend.modules.chat._soft_cot_parser import wrap_with_soft_cot_parser

    soft_cot_on = is_soft_cot_active(
        soft_cot_enabled=bool(persona and persona.get("soft_cot_enabled")),
        supports_reasoning=supports_reasoning,
        reasoning_enabled=reasoning_enabled,
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
    ) -> str | None:
        token_count = count_tokens(content)
        doc = await repo.save_message(
            session_id,
            role="assistant",
            content=content,
            token_count=token_count,
            thinking=thinking,
            web_search_context=web_search_context,
            knowledge_context=knowledge_context,
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
    except Exception as e:
        _log.error("Unexpected error in run_inference for session %s: %s", session_id, e)
    finally:
        # Always reset to idle — covers success (idempotent), cancel, error,
        # and disconnect scenarios where the stream ends without exception.
        await repo.update_session_state(session_id, "idle")
        async with _heartbeat_lock:
            _cancel_events.pop(correlation_id, None)
            _last_heartbeat.pop(correlation_id, None)
            _cancel_user_ids.pop(correlation_id, None)
            watchdog = _heartbeat_watchdogs.pop(correlation_id, None)
        if watchdog is not None and not watchdog.done():
            watchdog.cancel()


async def emit_session_expired(user_id: str, session_id: str) -> None:
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

        # Fetch unextracted user messages only
        db = get_db()
        repo = ChatRepository(db)
        unextracted = await repo.list_unextracted_user_messages(session_id, limit=20)

        if not unextracted:
            _log.debug(
                "No unextracted messages for idle extraction: user=%s persona=%s session=%s",
                user_id, persona_id, session_id,
            )
            return

        message_ids = [m["_id"] for m in unextracted]
        message_contents = [m["content"] for m in unextracted]

        # Dedup: only one in-flight memory extraction per user+persona.
        # If a previous extraction is still queued / running / retrying
        # (or recently failed and the cooldown TTL has not expired), we
        # skip this submission. Prevents queue flood when the provider
        # is slow or unreachable.
        slot_key = memory_extraction_slot_key(user_id, persona_id)
        if not await try_acquire_inflight_slot(redis, slot_key, ttl_seconds=3600):
            _log.info(
                "Skipping idle extraction — another extraction is already in flight: user=%s persona=%s",
                user_id, persona_id,
            )
            return

        await submit(
            job_type=JobType.MEMORY_EXTRACTION,
            user_id=user_id,
            model_unique_id=model_unique_id,
            payload={
                "persona_id": persona_id,
                "session_id": session_id,
                "messages": message_contents,
                "message_ids": message_ids,
            },
        )
        _log.info(
            "Submitted idle-triggered extraction: user=%s persona=%s session=%s msg_count=%d msg_ids=%s",
            user_id, persona_id, session_id, len(message_ids), message_ids,
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


async def track_extraction_trigger(
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
        await redis.hset(tracking_key, mapping={
            "last_message_at": now_iso,
            "session_id": session_id,
            "model_unique_id": model_unique_id,
        })

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


async def trigger_disconnect_extraction(user_id: str) -> None:
    """Submit memory extraction for all personas with pending messages when a user disconnects.

    Cancels any in-flight idle extraction timers for this user, then checks Redis
    tracking keys for personas with messages_since_extraction > 0 and submits
    extraction jobs immediately.
    """
    try:
        # Cancel all idle extraction timers for this user
        keys_to_cancel = [k for k in _idle_extraction_tasks if k.startswith(f"{user_id}:")]
        for task_key in keys_to_cancel:
            task = _idle_extraction_tasks.pop(task_key, None)
            if task and not task.done():
                task.cancel()

        redis = get_redis()

        # Scan for all tracking keys belonging to this user
        prefix = f"memory:extraction:{user_id}:"
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor, match=f"{prefix}*", count=100)
            for key in keys:
                tracking = await redis.hgetall(key)
                count_str = tracking.get("messages_since_extraction", "0")
                if int(count_str) <= 0:
                    continue

                session_id = tracking.get("session_id")
                model_unique_id = tracking.get("model_unique_id")
                if not session_id or not model_unique_id:
                    continue

                # Extract persona_id from the key
                persona_id = key.removeprefix(prefix)

                # Fetch unextracted user messages only
                db = get_db()
                repo = ChatRepository(db)
                unextracted = await repo.list_unextracted_user_messages(session_id, limit=20)

                if not unextracted:
                    _log.debug(
                        "No unextracted messages for disconnect extraction: user=%s persona=%s session=%s",
                        user_id, persona_id, session_id,
                    )
                    continue

                message_ids = [m["_id"] for m in unextracted]
                message_contents = [m["content"] for m in unextracted]

                # Dedup: skip if an extraction for this persona is
                # already in flight (queued / running / retrying), or
                # still inside the cooldown window from a recent failure.
                slot_key = memory_extraction_slot_key(user_id, persona_id)
                if not await try_acquire_inflight_slot(redis, slot_key, ttl_seconds=3600):
                    _log.info(
                        "Skipping disconnect extraction — another extraction is already in flight: user=%s persona=%s",
                        user_id, persona_id,
                    )
                    continue

                submit_kwargs = {
                    "job_type": JobType.MEMORY_EXTRACTION.value,
                    "user_id": user_id,
                    "model_unique_id": model_unique_id,
                    "payload": {
                        "persona_id": persona_id,
                        "session_id": session_id,
                        "messages": message_contents,
                        "message_ids": message_ids,
                    },
                }

                # H-003: retry a handful of times before giving up, and if
                # we still fail, buffer the payload in Redis so the recovery
                # loop can replay it once the transient fault clears.
                delays = [0.1, 0.5, 2.0]
                last_exc: Exception | None = None
                submitted = False
                for delay in delays:
                    try:
                        await asyncio.sleep(delay)
                        await submit(
                            job_type=JobType.MEMORY_EXTRACTION,
                            user_id=user_id,
                            model_unique_id=model_unique_id,
                            payload=submit_kwargs["payload"],
                        )
                        submitted = True
                        break
                    except Exception as exc:
                        last_exc = exc

                if submitted:
                    _log.info(
                        "Submitted disconnect-triggered extraction: user=%s persona=%s session=%s msg_count=%d",
                        user_id, persona_id, session_id, len(message_ids),
                    )
                else:
                    _log.error(
                        "trigger_disconnect_extraction: submit failed after %d attempts, buffering for recovery (user=%s persona=%s)",
                        len(delays), user_id, persona_id, exc_info=last_exc,
                    )
                    await buffer_submit_payload(redis, user_id, submit_kwargs)

            if cursor == 0:
                break
    except Exception:
        _log.exception(
            "Error triggering disconnect extraction for user %s", user_id,
        )
