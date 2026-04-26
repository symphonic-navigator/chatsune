"""Inference orchestration and supporting helpers for the chat module.

Internal module — must not be imported from outside ``backend.modules.chat``.
"""

import asyncio
import base64
import json
import logging
import time
from datetime import datetime, timezone
from typing import Literal
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
    release_inflight_slot,
    submit,
    try_acquire_inflight_slot,
)
from backend.jobs._dedup import MEMORY_EXTRACTION_SLOT_TTL_SECONDS
from backend.jobs._disconnect_retry import buffer_submit_payload
from backend.database import get_db, get_redis
from backend.modules.llm import (
    stream_completion as llm_stream_completion,
    get_effective_context_window,
    get_model_supports_vision,
    get_model_supports_reasoning,
    resolve_for_model,
    LlmConnectionNotFoundError,
    LlmInvalidModelUniqueIdError,
)
from backend.modules.persona import get_persona
from backend.modules.storage import (
    get_files_by_ids,
    get_cached_vision_description,
    store_vision_description,
)
from backend.modules.tools import execute_tool, get_active_definitions, set_mcp_registry, get_mcp_registry
from shared.topics import Topics
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


def _filter_usable_history(docs: list[dict]) -> list[dict]:
    """Exclude messages that must not enter the LLM context.

    Aborted messages are interrupted/incomplete and pollute context.
    Refused messages are known to poison context with further refusals.
    """
    return [
        d for d in docs
        if d.get("status", "completed") not in ("aborted", "refused")
    ]


def _format_pti_knowledge_block(items: list[dict]) -> str:
    """Format PTI-injected knowledge_context items into a hidden context
    block prepended to the user's message text.

    PTI persists matched documents on the user message, but the LLM
    only sees plain message content unless we explicitly include them
    here. The block is wrapped in <context>…</context> with a brief
    instruction so the model treats it as background, not as something
    to quote verbatim.
    """
    blocks: list[str] = []
    for item in items:
        title = item.get("document_title", "")
        library = item.get("library_name", "")
        triggered_by = item.get("triggered_by", "")
        content = item.get("content", "")
        header = f"## {title}".rstrip()
        annot_bits: list[str] = []
        if library:
            annot_bits.append(f"from {library}")
        if triggered_by:
            annot_bits.append(f"triggered by: {triggered_by}")
        if annot_bits:
            header = f"{header}  _({'; '.join(annot_bits)})_"
        blocks.append(f"{header}\n\n{content}".strip())
    body = "\n\n---\n\n".join(blocks)
    return (
        "<context>\n"
        "The following documents were automatically retrieved based on phrases "
        "in the user's message. Use them silently as background — do not quote "
        "this framing or the headers verbatim.\n\n"
        f"{body}\n"
        "</context>\n\n"
    )

# Active cancel events keyed by correlation_id
_cancel_events: dict[str, asyncio.Event] = {}

# Maps correlation_id -> user_id so cancel_all_for_user can filter in-flight
# inferences by owner. Written by run_inference and handle_incognito_send,
# cleaned up in their respective finally blocks.
_cancel_user_ids: dict[str, str] = {}

# Cancels can arrive before run_inference has finished resolving prompt/model
# setup and registered its cancel_event. Keep a short tombstone so the event is
# set immediately once the run reaches registration.
_PENDING_CANCEL_TTL_SECONDS = 30.0
_pending_cancels: dict[str, tuple[str | None, float]] = {}

# In-flight idle extraction timers keyed by "user_id:persona_id"
_idle_extraction_tasks: dict[str, asyncio.Task] = {}

_DEFAULT_CONTEXT_WINDOW = 8192
_IDLE_EXTRACTION_DELAY_SECONDS = 300  # 5 minutes


def _prune_pending_cancels() -> None:
    now = time.monotonic()
    expired = [
        cid for cid, (_, ts) in _pending_cancels.items()
        if now - ts > _PENDING_CANCEL_TTL_SECONDS
    ]
    for cid in expired:
        _pending_cancels.pop(cid, None)


def request_cancel(correlation_id: str, user_id: str | None = None) -> bool:
    """Signal a correlation cancel now, or remember it until registration.

    Returns True if an already-registered inference was signalled, False if a
    pending tombstone was stored.
    """
    if not correlation_id:
        return False
    event = _cancel_events.get(correlation_id)
    if event is not None:
        owner = _cancel_user_ids.get(correlation_id)
        if user_id is None or owner is None or owner == user_id:
            event.set()
            return True
    _prune_pending_cancels()
    _pending_cancels[correlation_id] = (user_id, time.monotonic())
    return False


def _consume_pending_cancel(correlation_id: str, user_id: str) -> bool:
    item = _pending_cancels.get(correlation_id)
    if not item:
        return False
    owner, ts = item
    if time.monotonic() - ts > _PENDING_CANCEL_TTL_SECONDS:
        _pending_cancels.pop(correlation_id, None)
        return False
    if owner is not None and owner != user_id:
        return False
    _pending_cancels.pop(correlation_id, None)
    return True


async def cancel_all_for_user(user_id: str) -> int:
    """Cancel every in-flight inference belonging to the given user.

    Used on WebSocket disconnect to avoid burning tokens on a response the
    user will never see. Returns the number of inferences signalled.
    """
    targets = [cid for cid, uid in _cancel_user_ids.items() if uid == user_id]
    for cid in targets:
        event = _cancel_events.get(cid)
        if event is not None:
            event.set()
    return len(targets)


def _make_tool_executor(
    session: dict,
    persona: dict | None,
    correlation_id: str = "",
    connection_id: str | None = None,
    model_slug: str = "",
):
    """Wrap execute_tool to inject session context and forward the
    originating WebSocket connection id for client-side tools."""
    persona_lib_ids = (persona or {}).get("knowledge_library_ids", [])
    session_lib_ids = session.get("knowledge_library_ids", [])
    sanitised = session.get("sanitised", False)

    async def _executor(
        user_id: str,
        tool_name: str,
        arguments_json: str,
        *,
        tool_call_id: str,
    ) -> str:
        if tool_name == "knowledge_search":
            args = json.loads(arguments_json)
            args["_persona_library_ids"] = persona_lib_ids
            args["_session_library_ids"] = session_lib_ids
            args["_sanitised"] = sanitised
            args["_session_id"] = session.get("_id", "")
            arguments_json = json.dumps(args)

        artefact_tools = {
            "create_artefact", "update_artefact", "read_artefact", "list_artefacts",
        }
        if tool_name in artefact_tools:
            args = json.loads(arguments_json)
            args["_session_id"] = session.get("_id", "")
            args["_correlation_id"] = correlation_id
            arguments_json = json.dumps(args)

        if tool_name == "write_journal_entry":
            args = json.loads(arguments_json)
            args["_session_id"] = session.get("_id", "")
            args["_persona_id"] = (persona or {}).get("_id", "")
            args["_persona_name"] = (persona or {}).get("name", "")
            args["_correlation_id"] = correlation_id
            arguments_json = json.dumps(args)

        if tool_name == "generate_image":
            # Inject the tool-call id so ImageGenerationToolExecutor can
            # tag the persisted document and emit the correct event scope.
            # Use a fresh dict to avoid mutating the caller's object.
            args = json.loads(arguments_json)
            arguments_json = json.dumps({**args, "__tool_call_id__": tool_call_id})

        return await execute_tool(
            user_id,
            tool_name,
            arguments_json,
            tool_call_id=tool_call_id,
            session_id=session.get("_id", ""),
            originating_connection_id=connection_id or "",
            model=model_slug,
        )

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
    *,
    connection_id: str | None = None,
    correlation_id: str | None = None,
) -> None:
    """Shared inference path used by send, edit, and regenerate."""
    persona_id = session.get("persona_id")

    # Resolve persona early — the model is always read from the persona,
    # never from the session.
    persona = await get_persona(persona_id, user_id) if persona_id else None
    model_unique_id = persona.get("model_unique_id", "") if persona else ""

    if ":" not in model_unique_id:
        _log.error("Invalid model_unique_id format: %s", model_unique_id)
        await repo.update_session_state(session_id, "idle")
        return

    llm_connection_slug, model_slug = model_unique_id.split(":", 1)
    # Premium-aware resolve: handles reserved slugs (``xai``, ``ollama_cloud``)
    # by routing through the Premium Provider service, otherwise falls back
    # to the user's Connection repository. If neither matches we keep the
    # historical fallback of (slug, "unknown") — inference will then fail
    # downstream with a proper ``LlmConnectionNotFoundError`` but debug
    # metadata remains non-None for event emission.
    try:
        resolved_connection = await resolve_for_model(user_id, model_unique_id)
    except LlmConnectionNotFoundError:
        resolved_connection = None
    connection_display_name = (
        resolved_connection.display_name if resolved_connection is not None else llm_connection_slug
    )
    adapter_type = (
        resolved_connection.adapter_type if resolved_connection is not None else "unknown"
    )
    reasoning_override = session.get("reasoning_override")
    if reasoning_override is not None:
        reasoning_enabled = reasoning_override
    else:
        reasoning_enabled = persona.get("reasoning_enabled", False) if persona else False
    supports_reasoning = await get_model_supports_reasoning(user_id, model_unique_id)

    # Assemble system prompt
    tools_enabled_flag = session.get("tools_enabled", False)
    system_prompt = await assemble(
        user_id=user_id,
        persona_id=persona_id,
        model_unique_id=model_unique_id,
        supports_reasoning=supports_reasoning,
        reasoning_enabled_for_call=reasoning_enabled,
        tools_enabled=tools_enabled_flag,
    )
    system_prompt_tokens = count_tokens(system_prompt) if system_prompt else 0

    # Get context window size (respects user override)
    max_context = await get_effective_context_window(user_id, model_unique_id)
    if max_context is None or max_context == 0:
        max_context = _DEFAULT_CONTEXT_WINDOW

    # Load message history
    history_docs = await repo.list_messages(session_id)
    # Aborted assistant messages pollute the LLM context with
    # half-finished thoughts or truncated code — strip them before
    # context pair selection. The matching user prompts remain in place
    # so a regenerate still has the user's input to work with.
    history_docs = _filter_usable_history(history_docs)

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
    # Use the caller-supplied correlation_id (threaded from the handler so
    # all stream events share the same id as the user message event) or
    # generate a new one for backwards compatibility.
    correlation_id = correlation_id or str(uuid4())
    cancel_event = asyncio.Event()
    _cancel_events[correlation_id] = cancel_event
    _cancel_user_ids[correlation_id] = user_id
    if _consume_pending_cancel(correlation_id, user_id):
        cancel_event.set()

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
        # PTI: prepend any phrase-triggered knowledge_context items as a
        # hidden context block so the LLM actually sees the lore. Only
        # source="trigger" items belong here; source="search" items come
        # from assistant-side knowledge_search tool calls and are already
        # surfaced via tool-result messages during inference.
        pti_items = [
            item for item in (last_msg.get("knowledge_context") or [])
            if item.get("source") == "trigger"
        ]
        if pti_items:
            last_msg_parts.insert(
                0,
                ContentPart(type="text", text=_format_pti_knowledge_block(pti_items)),
            )
        new_msg_vision_snapshots: list[dict] = []
        attachment_ids = last_msg.get("attachment_ids")
        if attachment_ids:
            supports_vision = await get_model_supports_vision(user_id, model_unique_id)
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
    tools_enabled = session.get("tools_enabled", False)

    if not tools_enabled:
        active_tools = None
    else:
        # MCP registry: populated eagerly on WebSocket connect (eager_discover_mcp).
        # Fallback: if the eager task hasn't finished yet, run discovery inline.
        mcp_registry = get_mcp_registry(connection_id) if connection_id else None
        if (
            connection_id
            and (mcp_registry is None or not mcp_registry.backend_discovered)
        ):
            from backend.modules.tools import eager_discover_mcp
            await eager_discover_mcp(connection_id, user_id)
            mcp_registry = get_mcp_registry(connection_id)

        # Extract persona MCP config for tool filtering
        persona_mcp_config = None
        if persona and persona.get("mcp_config"):
            from shared.dtos.mcp import PersonaMcpConfig
            persona_mcp_config = PersonaMcpConfig(**persona["mcp_config"])

        active_tools = await get_active_definitions(
            [],  # empty disabled-list — all groups active; tools_enabled is the master switch
            mcp_registry=mcp_registry,
            persona_mcp_config=persona_mcp_config,
            user_id=user_id,
        ) or None

        # Merge integration tools (independent of MCP/tool group toggles)
        from backend.modules.integrations import get_integration_tools
        integration_tools = await get_integration_tools(user_id, persona_id if persona_id else None)
        if integration_tools:
            if active_tools is None:
                active_tools = integration_tools
            else:
                active_tools = list(active_tools) + integration_tools

    # Estimate tokens consumed by tool definitions sent with the API call
    tool_definition_tokens = 0
    if active_tools:
        for td in active_tools:
            tool_definition_tokens += count_tokens(
                td.name + " " + td.description + " " + json.dumps(td.parameters)
            )

    # Recalculate budget with tool definitions included so the ampel
    # status and fill ratio reflect the true context consumption.
    budget = calculate_budget(
        max_context_tokens=max_context,
        system_prompt_tokens=system_prompt_tokens,
        new_message_tokens=new_msg_tokens,
        tool_definition_tokens=tool_definition_tokens,
    )
    total_tokens_used = system_prompt_tokens + tool_definition_tokens + all_history_tokens
    fill_ratio = total_tokens_used / max_context if max_context > 0 else 1.0

    request = CompletionRequest(
        model=model_slug,
        messages=messages,
        temperature=persona.get("temperature") if persona else None,
        reasoning_enabled=reasoning_enabled,
        supports_reasoning=supports_reasoning,
        tools=active_tools,
        cache_hint=session_id,
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

    async def stream_fn(extra_messages=None):
        req = request
        if extra_messages:
            extended = list(request.messages) + extra_messages
            req = request.model_copy(update={"messages": extended})

        upstream = llm_stream_completion(user_id, model_unique_id, req)
        if soft_cot_on:
            upstream = wrap_with_soft_cot_parser(upstream)

        async for event in upstream:
            yield event

    async def save_fn(
        content: str,
        thinking: str | None = None,
        usage: dict | None = None,
        web_search_context: list[dict] | None = None,
        knowledge_context: list[dict] | None = None,
        artefact_refs: list | None = None,
        tool_calls: list[dict] | None = None,
        image_refs: list[dict] | None = None,
        refusal_text: str | None = None,
        status: Literal["completed", "aborted", "refused"] = "completed",
    ) -> str | None:
        token_count = count_tokens(content)
        doc = await repo.save_message(
            session_id,
            role="assistant",
            content=content,
            token_count=token_count,
            thinking=thinking,
            usage=usage,
            web_search_context=web_search_context,
            knowledge_context=knowledge_context,
            artefact_refs=artefact_refs,
            tool_calls=tool_calls,
            image_refs=image_refs,
            refusal_text=refusal_text,
            status=status,
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
            context_used_tokens=total_tokens_used,
            context_max_tokens=max_context,
            tool_executor_fn=_make_tool_executor(session, persona, correlation_id, connection_id, model_slug) if active_tools else None,
            connection_display_name=connection_display_name,
            model_name=model_slug,
            adapter_type=adapter_type,
            model_slug=model_slug,
        )
        # Persist the latest context-window utilisation on the session so
        # that opening the chat later can hydrate the indicator without
        # waiting for the next inference to complete.
        try:
            await repo.update_session_context_metrics(
                session_id, context_status, fill_ratio,
                used_tokens=total_tokens_used,
                max_tokens=max_context,
            )
        except Exception:
            _log.exception(
                "Failed to persist context metrics for session %s", session_id,
            )
    except LlmConnectionNotFoundError:
        now = datetime.now(timezone.utc)
        await emit_fn(ChatStreamErrorEvent(
            correlation_id=correlation_id,
            error_code="connection_not_found",
            recoverable=False,
            user_message="Model not linked to a connection — please select it again in the persona.",
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
    except LlmInvalidModelUniqueIdError:
        now = datetime.now(timezone.utc)
        await emit_fn(ChatStreamErrorEvent(
            correlation_id=correlation_id,
            error_code="invalid_model_unique_id",
            recoverable=False,
            user_message="Model ID invalid — please select it again in the persona.",
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
        _cancel_events.pop(correlation_id, None)
        _cancel_user_ids.pop(correlation_id, None)


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

        # Resolve model from persona at submission time so we always use
        # the current setting, not a stale cached value.
        persona = await get_persona(persona_id, user_id)
        model_unique_id = persona.get("model_unique_id", "") if persona else ""
        if not model_unique_id:
            _log.warning(
                "Cannot run idle extraction — persona has no model: user=%s persona=%s",
                user_id, persona_id,
            )
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
        if not await try_acquire_inflight_slot(redis, slot_key, ttl_seconds=MEMORY_EXTRACTION_SLOT_TTL_SECONDS):
            _log.info(
                "Skipping idle extraction — another extraction is already in flight: user=%s persona=%s",
                user_id, persona_id,
            )
            return

        # Catch BaseException (including CancelledError) so a cancel or a
        # raising submit() does not leak the slot. Without this the 1h TTL
        # would block this persona even though no job was ever queued.
        try:
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
        except BaseException:
            await release_inflight_slot(redis, slot_key)
            raise
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
        })

        # Cancel any existing idle timer for this user+persona pair
        task_key = f"{user_id}:{persona_id}"
        old_task = _idle_extraction_tasks.pop(task_key, None)
        if old_task and not old_task.done():
            old_task.cancel()

        # Schedule new idle extraction timer
        task = asyncio.create_task(
            _schedule_idle_extraction(
                user_id, persona_id, session_id, now_iso,
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
                if not session_id:
                    continue

                # Extract persona_id from the key
                persona_id = key.removeprefix(prefix)

                # Resolve model from persona at submission time
                persona = await get_persona(persona_id, user_id)
                model_unique_id = persona.get("model_unique_id", "") if persona else ""
                if not model_unique_id:
                    _log.warning(
                        "Cannot run disconnect extraction — persona has no model: user=%s persona=%s",
                        user_id, persona_id,
                    )
                    continue

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
                if not await try_acquire_inflight_slot(redis, slot_key, ttl_seconds=MEMORY_EXTRACTION_SLOT_TTL_SECONDS):
                    _log.info(
                        "Skipping disconnect extraction — another extraction is already in flight: user=%s persona=%s",
                        user_id, persona_id,
                    )
                    continue

                slot_released = False
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
                try:
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
                        try:
                            await buffer_submit_payload(redis, user_id, submit_kwargs)
                        except Exception:
                            # Nothing has been queued and nothing has been
                            # buffered — release the slot so the next trigger
                            # (or recovery loop) is not blocked for an hour.
                            _log.exception(
                                "trigger_disconnect_extraction: buffering also failed, releasing inflight slot: user=%s persona=%s",
                                user_id, persona_id,
                            )
                            await release_inflight_slot(redis, slot_key)
                            slot_released = True
                except BaseException:
                    # Cancellation or any unexpected error between acquire
                    # and submit/buffer must not leak the slot.
                    if not slot_released:
                        await release_inflight_slot(redis, slot_key)
                    raise

            if cursor == 0:
                break
    except Exception:
        _log.exception(
            "Error triggering disconnect extraction for user %s", user_id,
        )
