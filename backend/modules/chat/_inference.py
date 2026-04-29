import asyncio
import json
import logging
import os
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Literal

from backend.config import settings
from backend.jobs import get_user_lock
from shared.dtos.images import ImageRefDto
from backend.modules.metrics import inferences_aborted_total
from backend.modules.llm import (
    ContentDelta,
    StreamAborted,
    StreamDone,
    StreamError,
    StreamRefused,
    StreamSlow,
    ThinkingDelta,
    ToolCallEvent,
)
from shared.dtos.chat import (
    ArtefactRefDto,
    KnowledgeContextItem,
    TimelineEntryArtefact,
    TimelineEntryImage,
    TimelineEntryKnowledgeSearch,
    TimelineEntryToolCall,
    TimelineEntryWebSearch,
    WebSearchContextItemDto,
)
from shared.dtos.inference import CompletionMessage
from shared.events.chat import (
    ChatContentDeltaEvent, ChatStreamEndedEvent, ChatStreamErrorEvent,
    ChatStreamSlowEvent, ChatStreamStartedEvent, ChatThinkingDeltaEvent,
    ChatToolCallCompletedEvent, ChatToolCallStartedEvent,
    ChatWebSearchContextEvent, WebSearchContextItem,
)

_log = logging.getLogger(__name__)

# Opt-in per-chunk delta tracing. Enable via LLM_TRACE_DELTAS=1 in the
# environment. Mirrors the adapter-side switch so we can see both sides
# of the pipeline (what arrived from the provider vs. what was emitted
# to the client) when diagnosing "TTFT then long pause" issues.
_TRACE_DELTAS = os.environ.get("LLM_TRACE_DELTAS") == "1"

_MAX_TOOL_ITERATIONS = 5
_REFUSAL_FALLBACK_TEXT = "The model declined this request."


def make_timeline_entry(
    *,
    seq: int,
    tool_name: str,
    tool_call_id: str,
    arguments: dict,
    success: bool,
    moderated_count: int = 0,
    knowledge_results: list | None = None,
    web_items: list | None = None,
    artefact_ref: ArtefactRefDto | None = None,
    image_refs: list | None = None,
):
    """Map one completed tool call to its TimelineEntry variant.

    A failed tool always becomes a generic ``tool_call`` entry, regardless
    of which tool it was — empty knowledge/web pills would be confusing
    and a failed image generation has no refs to render.
    """
    if not success:
        return TimelineEntryToolCall(
            seq=seq,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments=arguments,
            success=False,
            moderated_count=moderated_count,
        )

    if tool_name == "knowledge_search":
        items = [
            r if isinstance(r, KnowledgeContextItem)
            else KnowledgeContextItem.model_validate(r)
            for r in (knowledge_results or [])
        ]
        return TimelineEntryKnowledgeSearch(seq=seq, items=items)

    if tool_name in ("web_search", "web_fetch"):
        items = [
            w if isinstance(w, WebSearchContextItemDto)
            else WebSearchContextItemDto.model_validate(w)
            for w in (web_items or [])
        ]
        return TimelineEntryWebSearch(seq=seq, items=items)

    if tool_name in ("create_artefact", "update_artefact") and artefact_ref is not None:
        return TimelineEntryArtefact(seq=seq, ref=artefact_ref)

    if tool_name == "generate_image":
        return TimelineEntryImage(
            seq=seq,
            refs=list(image_refs or []),
            moderated_count=moderated_count,
        )

    return TimelineEntryToolCall(
        seq=seq,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        arguments=arguments,
        success=success,
        moderated_count=moderated_count,
    )


class InferenceRunner:
    """Orchestrates a single inference stream with per-user serialisation.

    Supports a multi-iteration tool loop: if the model emits tool calls,
    they are executed and the results fed back for a follow-up inference,
    up to ``_MAX_TOOL_ITERATIONS`` times.
    """

    async def run(
        self,
        user_id: str,
        session_id: str,
        correlation_id: str,
        stream_fn: Callable,
        emit_fn: Callable,
        save_fn: Callable,
        cancel_event: asyncio.Event | None = None,
        context_status: str = "green",
        context_fill_percentage: float = 0.0,
        context_used_tokens: int = 0,
        context_max_tokens: int = 0,
        tool_executor_fn: Callable | None = None,
        connection_display_name: str | None = None,
        model_name: str | None = None,
        adapter_type: str = "",
        model_slug: str = "",
    ) -> None:
        lock = get_user_lock(user_id)
        async with lock:
            await self._run_locked(
                user_id, session_id, correlation_id, stream_fn, emit_fn, save_fn,
                cancel_event, context_status, context_fill_percentage,
                context_used_tokens, context_max_tokens,
                tool_executor_fn, connection_display_name, model_name, adapter_type, model_slug,
            )

    async def _run_locked(
        self,
        user_id: str,
        session_id: str,
        correlation_id: str,
        stream_fn: Callable,
        emit_fn: Callable,
        save_fn: Callable,
        cancel_event: asyncio.Event | None,
        context_status: str = "green",
        context_fill_percentage: float = 0.0,
        context_used_tokens: int = 0,
        context_max_tokens: int = 0,
        tool_executor_fn: Callable | None = None,
        connection_display_name: str | None = None,
        model_name: str | None = None,
        adapter_type: str = "",
        model_slug: str = "",
    ) -> None:
        now = datetime.now(timezone.utc)
        await emit_fn(ChatStreamStartedEvent(
            session_id=session_id, correlation_id=correlation_id, timestamp=now,
        ))

        full_content = ""
        full_thinking = ""
        usage = None
        status = "completed"
        iter_refusal_text: str | None = None

        # Single chronological timeline of tool-derived events. Replaces
        # the four/five parallel lists (web_search_context,
        # knowledge_context, artefact_refs, image_refs, tool_calls) we
        # used to accumulate. ``next_seq`` is the per-message ordering key.
        events: list = []
        next_seq = 0

        # Mirror of the cumulative web-search context for the streaming
        # ChatWebSearchContextEvent payload — kept in lockstep with the
        # web_search/web_fetch entries we append to ``events``. Not
        # persisted; only used to feed the live event payload.
        web_search_context: list[dict] = []

        # Extra messages accumulated across tool-loop iterations.
        # Each iteration appends: assistant (with tool_calls) + tool result messages.
        extra_messages: list[CompletionMessage] = []

        t_stream_start = time.monotonic()
        t_first_token: float | None = None

        try:
            for iteration in range(_MAX_TOOL_ITERATIONS + 1):
                stream = (
                    await stream_fn(extra_messages)
                    if asyncio.iscoroutinefunction(stream_fn)
                    else stream_fn(extra_messages)
                )

                # Per-iteration accumulators
                iter_content = ""
                iter_thinking = ""
                iter_refusal_text: str | None = None
                iter_tool_calls: list[ToolCallEvent] = []
                cancelled = False
                stream_end_reason: str = "unknown"

                if settings.inference_logging:
                    _log.info(
                        "inference.stream.begin session=%s correlation_id=%s iteration=%d",
                        session_id, correlation_id, iteration,
                    )

                async for event in stream:
                    if cancel_event and cancel_event.is_set():
                        cancelled = True
                        status = "cancelled"
                        stream_end_reason = "cancelled"
                        break

                    match event:
                        case ContentDelta(delta=delta):
                            if t_first_token is None:
                                t_first_token = time.monotonic()
                            iter_content += delta
                            if _TRACE_DELTAS:
                                _log.info(
                                    "LLM_TRACE path=inference-emit kind=content "
                                    "correlation_id=%s len=%d preview=%r",
                                    correlation_id, len(delta), delta[:40],
                                )
                            await emit_fn(ChatContentDeltaEvent(
                                correlation_id=correlation_id, delta=delta,
                            ))

                        case ThinkingDelta(delta=delta):
                            if t_first_token is None:
                                t_first_token = time.monotonic()
                            iter_thinking += delta
                            if _TRACE_DELTAS:
                                _log.info(
                                    "LLM_TRACE path=inference-emit kind=thinking "
                                    "correlation_id=%s len=%d preview=%r",
                                    correlation_id, len(delta), delta[:40],
                                )
                            await emit_fn(ChatThinkingDeltaEvent(
                                correlation_id=correlation_id, delta=delta,
                            ))

                        case ToolCallEvent() as tc:
                            iter_tool_calls.append(tc)

                        case StreamDone() as done:
                            usage = {}
                            if done.input_tokens is not None:
                                usage["input_tokens"] = done.input_tokens
                            if done.output_tokens is not None:
                                usage["output_tokens"] = done.output_tokens
                            stream_end_reason = "done"

                        case StreamError() as err:
                            status = "error"
                            stream_end_reason = f"error:{err.error_code}"
                            await emit_fn(ChatStreamErrorEvent(
                                correlation_id=correlation_id,
                                error_code=err.error_code,
                                recoverable=err.error_code == "provider_unavailable",
                                user_message=err.message,
                                timestamp=datetime.now(timezone.utc),
                            ))

                        case StreamSlow():
                            await emit_fn(ChatStreamSlowEvent(
                                correlation_id=correlation_id,
                                timestamp=datetime.now(timezone.utc),
                            ))

                        case StreamAborted() as ab:
                            _log.warning(
                                "chat.stream.aborted session=%s correlation_id=%s reason=%s",
                                session_id, correlation_id, ab.reason,
                            )
                            status = "aborted"
                            stream_end_reason = f"aborted:{ab.reason}"
                            # Prometheus label name stays ``provider`` for
                            # dashboard backwards-compatibility; the value is
                            # now the adapter type (low-cardinality).
                            inferences_aborted_total.labels(
                                model=model_slug or "unknown",
                                provider=adapter_type or "unknown",
                            ).inc()
                            await emit_fn(ChatStreamErrorEvent(
                                correlation_id=correlation_id,
                                error_code="stream_aborted",
                                recoverable=True,
                                user_message="The response was interrupted. Please regenerate.",
                                timestamp=datetime.now(timezone.utc),
                            ))

                        case StreamRefused() as refused:
                            _log.warning(
                                "chat.stream.refused session=%s correlation_id=%s reason=%s",
                                session_id, correlation_id, refused.reason,
                            )
                            status = "refused"
                            stream_end_reason = f"refused:{refused.reason or 'unspecified'}"
                            iter_refusal_text = refused.refusal_text
                            await emit_fn(ChatStreamErrorEvent(
                                correlation_id=correlation_id,
                                error_code="refusal",
                                recoverable=True,
                                user_message=refused.refusal_text or _REFUSAL_FALLBACK_TEXT,
                                timestamp=datetime.now(timezone.utc),
                            ))

                if settings.inference_logging:
                    _log.info(
                        "inference.stream.end session=%s correlation_id=%s iteration=%d "
                        "reason=%s tool_calls=%d content_chars=%d thinking_chars=%d",
                        session_id, correlation_id, iteration, stream_end_reason,
                        len(iter_tool_calls), len(iter_content), len(iter_thinking),
                    )

                # Accumulate content/thinking across iterations
                full_content += iter_content
                if iter_thinking:
                    full_thinking += iter_thinking

                if cancelled or status in ("error", "aborted", "refused"):
                    break

                # No tool calls or no executor → we are done
                if not iter_tool_calls or tool_executor_fn is None:
                    break

                # Execute tool calls and prepare for next iteration
                from shared.dtos.inference import (
                    CompletionMessage, ContentPart, ToolCallResult,
                )

                # Build assistant message with tool calls for the LLM context
                assistant_msg = CompletionMessage(
                    role="assistant",
                    content=(
                        [ContentPart(type="text", text=iter_content)]
                        if iter_content else []
                    ),
                    tool_calls=[
                        ToolCallResult(
                            id=tc.id, name=tc.name, arguments=tc.arguments,
                        )
                        for tc in iter_tool_calls
                    ],
                )
                extra_messages.append(assistant_msg)

                # The content from this iteration was a tool-call turn — for
                # most tools the final user-facing content will come from the
                # next iteration, and resetting avoids duplication (artefact
                # tools tend to narrate the same idea before AND after the
                # call). For ``generate_image`` the model usually has nothing
                # meaningful to say after the call (it considers the request
                # fulfilled once the images render), so the pre-call preamble
                # IS the user-facing message — preserving it is the right
                # behaviour. The condition checks "all tools are preserve-
                # preamble" so a mixed iter (rare) still resets to be safe.
                #
                # Thinking, however, is cumulative regardless: reasoning that
                # preceded a tool call is still part of the model's complete
                # reasoning trace and must survive a chat reload, otherwise
                # the thinking bubble disappears on refresh.
                _PRESERVE_PREAMBLE_TOOLS = frozenset({"generate_image"})
                preserve_preamble = bool(iter_tool_calls) and all(
                    tc.name in _PRESERVE_PREAMBLE_TOOLS
                    for tc in iter_tool_calls
                )
                if not preserve_preamble:
                    full_content = ""

                for tc in iter_tool_calls:
                    now = datetime.now(timezone.utc)
                    arguments = json.loads(tc.arguments)

                    if settings.inference_logging:
                        _log.info(
                            "inference.tool_call.begin session=%s correlation_id=%s "
                            "tool_call_id=%s tool=%s args_chars=%d",
                            session_id, correlation_id, tc.id, tc.name,
                            len(tc.arguments) if tc.arguments else 0,
                        )

                    await emit_fn(ChatToolCallStartedEvent(
                        correlation_id=correlation_id,
                        tool_call_id=tc.id,
                        tool_name=tc.name,
                        arguments=arguments,
                        timestamp=now,
                    ))

                    result_str = await tool_executor_fn(
                        user_id, tc.name, tc.arguments,
                        tool_call_id=tc.id,
                    )

                    if settings.inference_logging:
                        _log.info(
                            "inference.tool_call.end session=%s correlation_id=%s "
                            "tool_call_id=%s tool=%s result_chars=%d",
                            session_id, correlation_id, tc.id, tc.name,
                            len(result_str) if result_str else 0,
                        )

                    try:
                        parsed_result = json.loads(result_str)
                        tool_success = not (isinstance(parsed_result, dict) and "error" in parsed_result)
                    except (json.JSONDecodeError, TypeError):
                        parsed_result = None
                        tool_success = True

                    # Capture artefact tool calls BEFORE emitting the completed event so
                    # the ref can be attached to the event payload.
                    ref_for_event: ArtefactRefDto | None = None
                    if tc.name in ("create_artefact", "update_artefact"):
                        if isinstance(parsed_result, dict) and parsed_result.get("ok"):
                            ref_for_event = ArtefactRefDto(
                                artefact_id=parsed_result.get("artefact_id", ""),
                                handle=parsed_result.get("handle") or arguments.get("handle", ""),
                                title=arguments.get("title", ""),
                                artefact_type=arguments.get("type", ""),
                                operation=(
                                    "create" if tc.name == "create_artefact" else "update"
                                ),
                            )

                    # Drain the structured image-generation outcome (if any).
                    # `generate_image` produces image_refs + a moderated_count;
                    # both flow onto the persisted assistant message AND into
                    # the tool_call.completed event so the frontend can render
                    # the inline image block live without a session reload.
                    moderated_count = 0
                    image_refs_for_event: list[ImageRefDto] | None = None
                    image_refs_for_entry: list = []
                    if tc.name == "generate_image":
                        from backend.modules.images._tool_executor import (
                            drain_image_outcome,
                        )
                        outcome = drain_image_outcome(tc.id)
                        if outcome is not None:
                            image_refs_for_entry = list(outcome.image_refs)
                            moderated_count = outcome.moderated_count
                            image_refs_for_event = (
                                list(outcome.image_refs) if outcome.image_refs else None
                            )
                            # All-moderated runs are surfaced as failed tool
                            # calls so the frontend pill can render the error
                            # state and offer a retry. Partial-moderation
                            # batches stay successful — the moderated_count
                            # decoration carries the secondary information.
                            if outcome.all_moderated:
                                tool_success = False

                    await emit_fn(ChatToolCallCompletedEvent(
                        correlation_id=correlation_id,
                        tool_call_id=tc.id,
                        tool_name=tc.name,
                        success=tool_success,
                        artefact_ref=ref_for_event,
                        image_refs=image_refs_for_event,
                        moderated_count=moderated_count,
                        timestamp=datetime.now(timezone.utc),
                    ))

                    # Capture web search/fetch context for metadata + pills.
                    # Each web_search/web_fetch call gets its own timeline
                    # entry carrying only the items returned by THAT call,
                    # so multiple calls in one turn render as multiple pills.
                    web_items_for_entry: list[dict] = []
                    if tc.name in ("web_search", "web_fetch"):
                        try:
                            parsed = json.loads(result_str)
                            if tc.name == "web_search" and isinstance(parsed, list):
                                for r in parsed:
                                    web_items_for_entry.append({
                                        "title": r.get("title", ""),
                                        "url": r.get("url", ""),
                                        "snippet": r.get("snippet", ""),
                                        "source_type": "search",
                                    })
                            elif tc.name == "web_fetch" and isinstance(parsed, dict):
                                content = parsed.get("content", "")
                                snippet = (content[:200] + "...") if len(content) > 200 else content
                                web_items_for_entry.append({
                                    "title": parsed.get("title") or parsed.get("url", ""),
                                    "url": parsed.get("url", ""),
                                    "snippet": snippet,
                                    "source_type": "fetch",
                                })
                            web_search_context.extend(web_items_for_entry)
                            # Emit per-call delta. One ChatWebSearchContextEvent
                            # per tool call → one web_search timeline entry on
                            # the frontend, matching the persisted shape and
                            # the per-call granularity of make_timeline_entry.
                            await emit_fn(ChatWebSearchContextEvent(
                                correlation_id=correlation_id,
                                items=[
                                    WebSearchContextItem(**ctx)
                                    for ctx in web_items_for_entry
                                ],
                            ))
                        except (json.JSONDecodeError, TypeError):
                            pass

                    # Capture knowledge search context for metadata + pills.
                    knowledge_items_for_entry: list = []
                    if tc.name == "knowledge_search":
                        try:
                            parsed = json.loads(result_str)
                            if isinstance(parsed, dict) and "results" in parsed:
                                knowledge_items_for_entry = list(parsed["results"])
                        except (json.JSONDecodeError, TypeError):
                            pass

                    # Map this completed tool call to one timeline entry.
                    events.append(make_timeline_entry(
                        seq=next_seq,
                        tool_name=tc.name,
                        tool_call_id=tc.id,
                        arguments=arguments,
                        success=tool_success,
                        moderated_count=moderated_count,
                        knowledge_results=knowledge_items_for_entry,
                        web_items=web_items_for_entry,
                        artefact_ref=ref_for_event,
                        image_refs=image_refs_for_entry,
                    ))
                    next_seq += 1

                    # Add tool result message for LLM context
                    extra_messages.append(CompletionMessage(
                        role="tool",
                        content=[ContentPart(type="text", text=result_str)],
                        tool_call_id=tc.id,
                    ))

        except Exception as e:
            _log.error("Inference error for session %s: %s", session_id, e)
            status = "error"
            await emit_fn(ChatStreamErrorEvent(
                correlation_id=correlation_id,
                error_code="internal_error",
                recoverable=False,
                user_message="An unexpected error occurred during inference.",
                timestamp=datetime.now(timezone.utc),
            ))

        message_id = None
        # Save whenever the stream produced any useful output — visible
        # content or a thinking block — regardless of whether the run
        # ended cleanly, was cancelled (manual stop, WS disconnect), or
        # errored. Throwing away already-streamed tokens means the
        # user sees them live and then loses them on refresh, which is
        # the worst possible outcome. The ``status`` still travels with
        # ``ChatStreamEndedEvent`` so the frontend can badge the message
        # appropriately.
        # Only persist assistant messages with visible content. Thinking-only
        # streams (e.g. aborted mid-thinking, or ollama_local interrupted by
        # another request) are dropped so the user can simply regenerate.
        # See docs/superpowers/specs/2026-04-08-ollama-local-and-chat-ui-fixes-design.md.
        if full_content or status == "refused":
            resolved_status: Literal["completed", "aborted", "refused"] = (
                "refused" if status == "refused"
                else "aborted" if status == "aborted"
                else "completed"
            )
            message_id = await save_fn(
                content=full_content,
                thinking=full_thinking or None,
                usage=usage,
                events=events or None,
                refusal_text=iter_refusal_text,
                status=resolved_status,
            )

        t_stream_end = time.monotonic()
        total_duration = t_stream_end - t_stream_start

        ttft_ms: int | None = None
        if t_first_token is not None:
            ttft_ms = round((t_first_token - t_stream_start) * 1000)

        tps: float | None = None
        output_tokens = (usage or {}).get("output_tokens")
        if output_tokens and total_duration > 0:
            tps = round(output_tokens / total_duration, 1)

        gen_duration_ms = round(total_duration * 1000)

        await emit_fn(ChatStreamEndedEvent(
            correlation_id=correlation_id,
            session_id=session_id,
            message_id=message_id,
            status=status,
            usage=usage,
            context_status=context_status,
            context_fill_percentage=context_fill_percentage,
            context_used_tokens=context_used_tokens,
            context_max_tokens=context_max_tokens,
            time_to_first_token_ms=ttft_ms,
            tokens_per_second=tps,
            generation_duration_ms=gen_duration_ms,
            provider_name=connection_display_name,
            model_name=model_name,
            events=[e.model_dump() for e in events] if events else None,
            timestamp=datetime.now(timezone.utc),
        ))
