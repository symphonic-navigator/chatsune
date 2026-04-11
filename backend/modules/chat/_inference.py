import asyncio
import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Literal

from backend.jobs import get_user_lock
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
from shared.dtos.chat import ArtefactRefDto
from shared.dtos.inference import CompletionMessage
from shared.events.chat import (
    ChatContentDeltaEvent, ChatStreamEndedEvent, ChatStreamErrorEvent,
    ChatStreamSlowEvent, ChatStreamStartedEvent, ChatThinkingDeltaEvent,
    ChatToolCallCompletedEvent, ChatToolCallStartedEvent,
    ChatWebSearchContextEvent, WebSearchContextItem,
)

_log = logging.getLogger(__name__)

_MAX_TOOL_ITERATIONS = 5
_REFUSAL_FALLBACK_TEXT = "The model declined this request."


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
        tool_executor_fn: Callable | None = None,
    ) -> None:
        lock = get_user_lock(user_id)
        async with lock:
            await self._run_locked(
                user_id, session_id, correlation_id, stream_fn, emit_fn, save_fn,
                cancel_event, context_status, context_fill_percentage,
                tool_executor_fn,
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
        tool_executor_fn: Callable | None = None,
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
        web_search_context: list[dict] = []
        knowledge_context: list[dict] = []
        artefact_refs: list[dict] = []

        # Extra messages accumulated across tool-loop iterations.
        # Each iteration appends: assistant (with tool_calls) + tool result messages.
        extra_messages: list[CompletionMessage] = []

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

                async for event in stream:
                    if cancel_event and cancel_event.is_set():
                        cancelled = True
                        status = "cancelled"
                        break

                    match event:
                        case ContentDelta(delta=delta):
                            iter_content += delta
                            await emit_fn(ChatContentDeltaEvent(
                                correlation_id=correlation_id, delta=delta,
                            ))

                        case ThinkingDelta(delta=delta):
                            iter_thinking += delta
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

                        case StreamError() as err:
                            status = "error"
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
                            iter_refusal_text = refused.refusal_text
                            await emit_fn(ChatStreamErrorEvent(
                                correlation_id=correlation_id,
                                error_code="refusal",
                                recoverable=True,
                                user_message=refused.refusal_text or _REFUSAL_FALLBACK_TEXT,
                                timestamp=datetime.now(timezone.utc),
                            ))

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

                # The content from this iteration was a tool-call turn — the
                # final user-facing content will come from the next iteration.
                # Reset so only the last iteration's content is saved.
                full_content = ""
                full_thinking = ""

                for tc in iter_tool_calls:
                    now = datetime.now(timezone.utc)
                    arguments = json.loads(tc.arguments)

                    await emit_fn(ChatToolCallStartedEvent(
                        correlation_id=correlation_id,
                        tool_call_id=tc.id,
                        tool_name=tc.name,
                        arguments=arguments,
                        timestamp=now,
                    ))

                    result_str = await tool_executor_fn(
                        user_id, tc.name, tc.arguments,
                    )

                    try:
                        parsed_result = json.loads(result_str)
                        tool_success = not (isinstance(parsed_result, dict) and "error" in parsed_result)
                    except (json.JSONDecodeError, TypeError):
                        tool_success = True

                    # Capture artefact tool calls BEFORE emitting the completed event so
                    # the ref can be attached to the event payload.
                    ref_for_event: ArtefactRefDto | None = None
                    if tc.name in ("create_artefact", "update_artefact"):
                        try:
                            parsed = json.loads(result_str)
                            if isinstance(parsed, dict) and parsed.get("ok"):
                                ref_dict = {
                                    "artefact_id": parsed.get("artefact_id", ""),
                                    "handle": parsed.get("handle") or arguments.get("handle", ""),
                                    "title": arguments.get("title", ""),
                                    "artefact_type": arguments.get("type", ""),
                                    "operation": (
                                        "create" if tc.name == "create_artefact" else "update"
                                    ),
                                }
                                artefact_refs.append(ref_dict)
                                ref_for_event = ArtefactRefDto(**ref_dict)
                        except (json.JSONDecodeError, TypeError):
                            pass

                    await emit_fn(ChatToolCallCompletedEvent(
                        correlation_id=correlation_id,
                        tool_call_id=tc.id,
                        tool_name=tc.name,
                        success=tool_success,
                        artefact_ref=ref_for_event,
                        timestamp=datetime.now(timezone.utc),
                    ))

                    # Capture web search/fetch context for metadata + pills
                    if tc.name in ("web_search", "web_fetch"):
                        try:
                            parsed = json.loads(result_str)
                            if tc.name == "web_search" and isinstance(parsed, list):
                                for r in parsed:
                                    web_search_context.append({
                                        "title": r.get("title", ""),
                                        "url": r.get("url", ""),
                                        "snippet": r.get("snippet", ""),
                                        "source_type": "search",
                                    })
                            elif tc.name == "web_fetch" and isinstance(parsed, dict):
                                content = parsed.get("content", "")
                                snippet = (content[:200] + "...") if len(content) > 200 else content
                                web_search_context.append({
                                    "title": parsed.get("title") or parsed.get("url", ""),
                                    "url": parsed.get("url", ""),
                                    "snippet": snippet,
                                    "source_type": "fetch",
                                })
                            # Emit full accumulated list so frontend stays in sync
                            await emit_fn(ChatWebSearchContextEvent(
                                correlation_id=correlation_id,
                                items=[
                                    WebSearchContextItem(**ctx)
                                    for ctx in web_search_context
                                ],
                            ))
                        except (json.JSONDecodeError, TypeError):
                            pass

                    # Capture knowledge search context for metadata + pills
                    if tc.name == "knowledge_search":
                        try:
                            parsed = json.loads(result_str)
                            if isinstance(parsed, dict) and "results" in parsed:
                                for r in parsed["results"]:
                                    knowledge_context.append(r)
                        except (json.JSONDecodeError, TypeError):
                            pass

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
                web_search_context=web_search_context or None,
                knowledge_context=knowledge_context or None,
                artefact_refs=artefact_refs or None,
                refusal_text=iter_refusal_text,
                status=resolved_status,
            )

        await emit_fn(ChatStreamEndedEvent(
            correlation_id=correlation_id,
            session_id=session_id,
            message_id=message_id,
            status=status,
            usage=usage,
            context_status=context_status,
            context_fill_percentage=context_fill_percentage,
            timestamp=datetime.now(timezone.utc),
        ))
