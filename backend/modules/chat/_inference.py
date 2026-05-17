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
from backend.modules.llm._adapters._events import StreamWarning, ToolCallArgsDelta
from backend.modules.tools import ToolNotFoundError
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
    ChatStreamSlowEvent, ChatStreamStartedEvent, ChatStreamWarningEvent,
    ChatThinkingDeltaEvent,
    ChatToolCallCompletedEvent, ChatToolCallDeltaEvent, ChatToolCallStartedEvent,
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


def _append_thinking_delta(
    blocks: list[dict], td: "ThinkingDelta",
) -> None:
    """Group an incoming ``ThinkingDelta`` into the per-iteration block list.

    Rules:

    * A delta with ``signature`` always starts a new block (Anthropic
      forwards one ``reasoning_details`` entry per discrete reasoning
      segment, each with its own signature; the parse path emits one
      ``ThinkingDelta`` per entry, so this case is one-block-per-event
      with no concatenation).
    * A delta without ``signature`` is concatenated onto the most
      recent anonymous (no-signature) block, OR starts a new anonymous
      block if the most recent entry has a signature or the list is
      empty. This matches the OpenAI-compat soft-CoT shape where a
      stream of small ``delta.reasoning`` fragments collectively
      represents one block.
    """
    sig = td.signature
    raw = td.raw
    text = td.delta or ""
    if sig:
        # One block per signature-carrying event.
        blocks.append({"text": text, "signature": sig, "raw": raw})
        return
    # Anonymous fragment — extend the current anonymous block if the
    # tail is also anonymous; otherwise start a new one.
    if blocks and blocks[-1].get("signature") is None:
        blocks[-1]["text"] = (blocks[-1].get("text") or "") + text
        # ``raw`` from the very first fragment wins. Later anonymous
        # fragments carry no provider-specific metadata worth merging.
    else:
        blocks.append({"text": text, "signature": None, "raw": raw})

# When iteration 0 of a completion ends cleanly (no error, no abort, no
# refusal) but produces zero content / zero thinking / zero tool_calls,
# retry the iteration up to ``_EMPTY_RESPONSE_MAX_RETRIES`` more times
# with exponential backoff. Provider-side intermittent glitches (observed
# on Novita DSv4 Flash, 2026-05-10) produce HTTP-200 streams that the
# existing 429/5xx retry path doesn't catch. Only iteration 0 is retried —
# legitimately-empty assistant turns inside the tool loop are out of scope.
_EMPTY_RESPONSE_MAX_RETRIES = 2  # 3 total attempts
_EMPTY_RESPONSE_BACKOFF_BASE = 1.0  # seconds; sleeps 1s, then 2s


def _should_retry_empty_response(
    *,
    iteration: int,
    cancelled: bool,
    status: str,
    iter_content: str,
    iter_thinking: str,
    iter_tool_calls: list,
    empty_attempt: int,
) -> bool:
    """Predicate for the empty-response retry decision.

    Returns True when:
      - we are on iteration 0 (later iterations may legitimately be empty
        after a tool call — out of scope for this fix);
      - the stream ended cleanly (not cancelled / not in error / not
        aborted / not refused);
      - none of {content, thinking, tool_calls} produced any output;
      - the per-iteration retry budget has not been exhausted.

    The conditions match the precise pattern observed on Novita DSv4 Flash
    on 2026-05-10: HTTP 200, ``[DONE]`` received, zero deltas of any kind.
    """
    if iteration != 0:
        return False
    if cancelled:
        return False
    if status in ("error", "aborted", "refused"):
        return False
    if iter_content or iter_thinking or iter_tool_calls:
        return False
    if empty_attempt >= _EMPTY_RESPONSE_MAX_RETRIES:
        return False
    return True


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
    result_content: str | None = None,
):
    """Map one completed tool call to its TimelineEntry variant.

    A failed tool always becomes a generic ``tool_call`` entry, regardless
    of which tool it was — empty knowledge/web pills would be confusing
    and a failed image generation has no refs to render.

    ``result_content`` is the text the tool returned (or its error
    message). Only carried on the generic ``tool_call`` entry — typed
    entries (knowledge / web / artefact / image) render their own
    structured payload and ignore the parameter.
    """
    if not success:
        return TimelineEntryToolCall(
            seq=seq,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments=arguments,
            success=False,
            moderated_count=moderated_count,
            result_content=result_content,
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
        result_content=result_content,
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
        total_session_tokens: int | None = None,
        tokens_actually_sent: int | None = None,
    ) -> None:
        lock = get_user_lock(user_id)
        async with lock:
            await self._run_locked(
                user_id, session_id, correlation_id, stream_fn, emit_fn, save_fn,
                cancel_event, context_status, context_fill_percentage,
                context_used_tokens, context_max_tokens,
                tool_executor_fn, connection_display_name, model_name, adapter_type, model_slug,
                total_session_tokens, tokens_actually_sent,
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
        total_session_tokens: int | None = None,
        tokens_actually_sent: int | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        await emit_fn(ChatStreamStartedEvent(
            session_id=session_id, correlation_id=correlation_id, timestamp=now,
        ))

        full_content = ""
        full_thinking = ""
        # Structured per-block accumulator. One entry per upstream
        # thinking segment in chronological order. Hard-CoT providers
        # (Anthropic, xAI Grok, Mistral Magistral) supply discrete
        # blocks — each with its own signature where applicable. Soft-
        # CoT and string-only streams collapse into a single anonymous
        # block. The legacy ``full_thinking`` string mirror is kept for
        # human-readable display and backwards-compat reads.
        full_thinking_blocks: list[dict] = []
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
                # Empty-response retry counter: scoped to this iteration.
                # Reset on every outer-loop turn so iteration 1+ starts fresh
                # (defensive — we don't actually retry past iteration 0).
                empty_attempt = 0
                while True:
                    stream = (
                        await stream_fn(extra_messages)
                        if asyncio.iscoroutinefunction(stream_fn)
                        else stream_fn(extra_messages)
                    )

                    # Per-iteration accumulators. Reset on every retry —
                    # that's correct, because the empty-retry path only
                    # fires when iter_content/iter_thinking/iter_tool_calls
                    # are all empty by definition, so nothing is lost.
                    iter_content = ""
                    iter_thinking = ""
                    # Per-iteration structured-thinking accumulator.
                    # See ``_append_thinking_delta`` for the grouping
                    # rules (one block per Anthropic-signature, single
                    # anonymous block for OpenAI-compat streams).
                    iter_thinking_blocks: list[dict] = []
                    iter_refusal_text: str | None = None
                    iter_tool_calls: list[ToolCallEvent] = []
                    iter_reasoning_tokens: int | None = None
                    iter_input_tokens: int | None = None
                    iter_output_tokens: int | None = None
                    cancelled = False
                    stream_end_reason: str = "unknown"

                    # Per-iteration buffer for tool-call delta events whose tool_call_id is
                    # not yet known. Keys are the OpenAI-style index. Backfilled when the id
                    # arrives in a later fragment, or in the finally-block drain if it never
                    # arrives mid-stream (e.g. xAI synthesises ids only at finalisation).
                    tool_call_id_buffer: dict[int, dict] = {}

                    if settings.inference_logging:
                        _log.info(
                            "inference.stream.begin session=%s correlation_id=%s iteration=%d",
                            session_id, correlation_id, iteration,
                        )

                    # If the stream raises mid-iteration we still want any
                    # partial content/thinking the user already saw to be
                    # rolled up so the persistence guard (further down) can
                    # save them. Without this, a hard internal error after
                    # streaming begins drops every token between the last
                    # successful event and the exception.
                    try:
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

                                case ThinkingDelta() as td:
                                    delta = td.delta
                                    if t_first_token is None:
                                        t_first_token = time.monotonic()
                                    iter_thinking += delta
                                    _append_thinking_delta(
                                        iter_thinking_blocks, td,
                                    )
                                    if _TRACE_DELTAS:
                                        _log.info(
                                            "LLM_TRACE path=inference-emit kind=thinking "
                                            "correlation_id=%s len=%d preview=%r sig=%s",
                                            correlation_id, len(delta), delta[:40],
                                            "yes" if td.signature else "no",
                                        )
                                    await emit_fn(ChatThinkingDeltaEvent(
                                        correlation_id=correlation_id, delta=delta,
                                    ))

                                case ToolCallArgsDelta(index=idx, id=tc_id, name=tc_name, arguments_delta=frag):
                                    slot = tool_call_id_buffer.setdefault(idx, {
                                        "id": None, "name": None, "pending_events": [],
                                        "chars": 0, "deltas": 0,
                                    })
                                    if tc_id and slot["id"] is None:
                                        slot["id"] = tc_id
                                        # Backfill all previously-queued events for this index.
                                        for pending in slot["pending_events"]:
                                            pending.tool_call_id = tc_id
                                            await emit_fn(pending)
                                        slot["pending_events"] = []
                                    if tc_name and slot["name"] is None:
                                        slot["name"] = tc_name

                                    resolved_id = slot["id"] or tc_id
                                    slot["chars"] += len(frag)
                                    slot["deltas"] += 1

                                    event_out = ChatToolCallDeltaEvent(
                                        correlation_id=correlation_id,
                                        tool_call_id=resolved_id or "",
                                        tool_index=idx,
                                        tool_name=slot["name"],
                                        args_delta=frag,
                                        timestamp=datetime.now(timezone.utc),
                                    )
                                    if resolved_id:
                                        await emit_fn(event_out)
                                    else:
                                        slot["pending_events"].append(event_out)

                                case ToolCallEvent() as tc:
                                    iter_tool_calls.append(tc)

                                case StreamDone() as done:
                                    usage = {}
                                    if done.input_tokens is not None:
                                        usage["input_tokens"] = done.input_tokens
                                    if done.output_tokens is not None:
                                        usage["output_tokens"] = done.output_tokens
                                    if done.reasoning_tokens is not None:
                                        usage["reasoning_tokens"] = done.reasoning_tokens
                                    iter_reasoning_tokens = done.reasoning_tokens
                                    iter_input_tokens = done.input_tokens
                                    iter_output_tokens = done.output_tokens
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

                                case StreamWarning() as warn:
                                    # Adapter-applied workaround
                                    # (today: Anthropic strip-and-retry).
                                    # Non-terminal — the stream
                                    # continues normally.
                                    await emit_fn(ChatStreamWarningEvent(
                                        correlation_id=correlation_id,
                                        code=warn.code,
                                        detail=warn.detail,
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
                    finally:
                        # Accumulate per-iteration content/thinking onto the
                        # full transcript even when the inner stream raised.
                        # The outer ``except`` handler will then map the
                        # exception to ``status="error"`` and the persistence
                        # guard will save what the user already saw.
                        full_content += iter_content
                        if iter_thinking:
                            full_thinking += iter_thinking
                        # Merge per-iteration thinking blocks onto the
                        # full list. Across tool-loop iterations the
                        # blocks land in chronological order; the
                        # orchestrator collapses them into one assistant
                        # message at replay time.
                        if iter_thinking_blocks:
                            full_thinking_blocks.extend(iter_thinking_blocks)

                        # Pending-Drain: any deltas emitted before the provider supplied an id
                        # are now matchable against iter_tool_calls (which carries the
                        # accumulator's index). Backfill and emit them in order.
                        for tc in iter_tool_calls:
                            slot = tool_call_id_buffer.get(tc.index)
                            if slot and slot["pending_events"]:
                                for pending in slot["pending_events"]:
                                    pending.tool_call_id = tc.id
                                    await emit_fn(pending)
                                slot["pending_events"] = []

                        if settings.inference_logging:
                            for tc in iter_tool_calls:
                                slot = tool_call_id_buffer.get(tc.index, {})
                                _log.info(
                                    "inference.tool_call.stream session=%s correlation_id=%s "
                                    "tool_call_id=%s tool=%s args_chars=%d deltas=%d",
                                    session_id, correlation_id, tc.id, tc.name,
                                    slot.get("chars", 0), slot.get("deltas", 0),
                                )

                    if settings.inference_logging:
                        _log.info(
                            "inference.stream.end session=%s correlation_id=%s iteration=%d "
                            "reason=%s tool_calls=%d content_chars=%d thinking_chars=%d "
                            "input_tokens=%s output_tokens=%s reasoning_tokens=%s",
                            session_id, correlation_id, iteration, stream_end_reason,
                            len(iter_tool_calls), len(iter_content), len(iter_thinking),
                            iter_input_tokens if iter_input_tokens is not None else "n/a",
                            iter_output_tokens if iter_output_tokens is not None else "n/a",
                            iter_reasoning_tokens if iter_reasoning_tokens is not None else "n/a",
                        )

                    # Empty-response retry decision. Sits between the
                    # stream.end log and the existing post-iteration
                    # break checks (which must keep their relative order).
                    # The predicate is extracted to a module-level helper
                    # so it can be unit-tested in isolation.
                    if _should_retry_empty_response(
                        iteration=iteration,
                        cancelled=cancelled,
                        status=status,
                        iter_content=iter_content,
                        iter_thinking=iter_thinking,
                        iter_tool_calls=iter_tool_calls,
                        empty_attempt=empty_attempt,
                    ):
                        empty_attempt += 1
                        backoff = _EMPTY_RESPONSE_BACKOFF_BASE * (
                            2 ** (empty_attempt - 1)
                        )
                        _log.info(
                            "inference.empty_response.retry session=%s "
                            "correlation_id=%s attempt=%d/%d backoff=%.1fs",
                            session_id, correlation_id,
                            empty_attempt, _EMPTY_RESPONSE_MAX_RETRIES, backoff,
                        )
                        await asyncio.sleep(backoff)
                        continue  # re-execute the iteration body
                    break  # exit while; fall through to existing logic

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

                # Content accumulates across iterations: every ``iter_content``
                # has already been folded into ``full_content`` in the finally
                # block above, and the next iteration will append more on top.
                # We deliberately do NOT reset between iterations — what the
                # user sees streamed live (the running concatenation) is what
                # gets persisted. Any redundant narration the model produces
                # before and after a tool call (e.g. "let me search…" / "I
                # searched…") is accepted as a minor cost of consistency.

                for tc in iter_tool_calls:
                    now = datetime.now(timezone.utc)

                    # Parse the model-supplied arguments. Malformed JSON here
                    # is a model mistake — feed the parse error back so the
                    # next iteration can self-correct, rather than aborting
                    # the whole turn.
                    try:
                        arguments = json.loads(tc.arguments) if tc.arguments else {}
                        args_parse_error: str | None = None
                    except json.JSONDecodeError as e:
                        arguments = {}
                        args_parse_error = str(e)

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

                    # Recoverable failure path: the model produced something
                    # invalid (unknown tool, malformed args). Feed a short
                    # error back as the tool result, mark the call failed,
                    # and continue the loop so the model can react. We catch
                    # ToolNotFoundError and JSONDecodeError narrowly — broad
                    # exceptions (DB errors, network drops) should still
                    # bubble up to the outer handler and hard-abort.
                    recoverable_error: str | None = None
                    if args_parse_error is not None:
                        recoverable_error = (
                            f"Error: tool arguments are not valid JSON: "
                            f"{args_parse_error}"
                        )
                        result_str = recoverable_error
                    else:
                        try:
                            result_str = await tool_executor_fn(
                                user_id, tc.name, tc.arguments,
                                tool_call_id=tc.id,
                            )
                        except ToolNotFoundError as e:
                            recoverable_error = (
                                f"Error: tool '{tc.name}' is not available. "
                                f"Pick a tool from the provided list, or answer "
                                f"directly without calling a tool."
                            )
                            result_str = recoverable_error
                            _log.warning(
                                "inference.tool_call.unknown session=%s correlation_id=%s "
                                "tool_call_id=%s tool=%s detail=%s",
                                session_id, correlation_id, tc.id, tc.name, e,
                            )
                        except json.JSONDecodeError as e:
                            # execute_tool itself parses arguments_json; if we
                            # got past the local parse but it raises here, the
                            # downstream parser disagreed — treat the same.
                            recoverable_error = (
                                f"Error: tool arguments are not valid JSON: {e}"
                            )
                            result_str = recoverable_error

                    if settings.inference_logging:
                        _log.info(
                            "inference.tool_call.end session=%s correlation_id=%s "
                            "tool_call_id=%s tool=%s result_chars=%d",
                            session_id, correlation_id, tc.id, tc.name,
                            len(result_str) if result_str else 0,
                        )

                    if recoverable_error is not None:
                        parsed_result = None
                        tool_success = False
                    else:
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
                        result_content=result_str,
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

                    # generate_image is the only tool that produces a non-
                    # tool_call typed entry AND requires a separate tool_call
                    # entry for the pill. Prepend a TimelineEntryToolCall so
                    # the pill renders above the image block. Failure path is
                    # already covered: make_timeline_entry collapses any
                    # failed call to TimelineEntryToolCall regardless of
                    # tool name — adding another here would double-render.
                    if tc.name == "generate_image" and tool_success:
                        events.append(TimelineEntryToolCall(
                            seq=next_seq,
                            tool_call_id=tc.id,
                            tool_name=tc.name,
                            arguments=arguments,
                            success=True,
                            moderated_count=moderated_count,
                            result_content=result_str,
                        ))
                        next_seq += 1

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
                        result_content=result_str,
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
        if full_content or full_thinking or status == "refused":
            resolved_status: Literal["completed", "aborted", "refused"] = (
                "refused" if status == "refused"
                else "aborted" if status == "aborted"
                else "completed"
            )
            # Persistence is best-effort: a DB blip or validation failure must
            # not crash the runner, otherwise the terminal ChatStreamEndedEvent
            # never fires and the frontend "thinking" indicator hangs forever.
            # On failure we surface a non-recoverable error event to the user
            # and fall through to the normal stream-ended path with status=error
            # and message_id=None so the UI releases its streaming state.
            try:
                message_id = await save_fn(
                    content=full_content,
                    thinking=full_thinking or None,
                    thinking_blocks=full_thinking_blocks or None,
                    usage=usage,
                    events=events or None,
                    refusal_text=iter_refusal_text,
                    status=resolved_status,
                )
            except Exception as exc:
                _log.exception(
                    "inference.save.failed session=%s correlation_id=%s "
                    "message_id=%s exc_type=%s exc_message=%s",
                    session_id, correlation_id, message_id,
                    type(exc).__name__, exc,
                )
                status = "error"
                message_id = None
                await emit_fn(ChatStreamErrorEvent(
                    correlation_id=correlation_id,
                    error_code="persistence_failed",
                    recoverable=False,
                    user_message=(
                        "The response could not be saved. Please regenerate."
                    ),
                    timestamp=datetime.now(timezone.utc),
                ))

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
            total_session_tokens=total_session_tokens,
            tokens_actually_sent=tokens_actually_sent,
            time_to_first_token_ms=ttft_ms,
            tokens_per_second=tps,
            generation_duration_ms=gen_duration_ms,
            provider_name=connection_display_name,
            model_name=model_name,
            events=[e.model_dump() for e in events] if events else None,
            # Carry the raw assistant content (including unprocessed
            # integration tags) so the frontend can populate its persisted
            # message in raw form. This lets ReadAloud re-parse the tags
            # without a DB round-trip after a continuous-voice run. None
            # when nothing was persisted (no message_id).
            raw_content=full_content if message_id else None,
            timestamp=datetime.now(timezone.utc),
        ))
