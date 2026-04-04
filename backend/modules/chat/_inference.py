import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timezone

from backend.jobs import get_user_lock
from backend.modules.llm import ContentDelta, StreamDone, StreamError, ThinkingDelta
from shared.events.chat import (
    ChatContentDeltaEvent, ChatStreamEndedEvent, ChatStreamErrorEvent,
    ChatStreamStartedEvent, ChatThinkingDeltaEvent,
)

_log = logging.getLogger(__name__)


class InferenceRunner:
    """Orchestrates a single inference stream with per-user serialisation."""

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
    ) -> None:
        lock = get_user_lock(user_id)
        async with lock:
            await self._run_locked(
                session_id, correlation_id, stream_fn, emit_fn, save_fn, cancel_event,
                context_status, context_fill_percentage,
            )

    async def _run_locked(
        self,
        session_id: str,
        correlation_id: str,
        stream_fn: Callable,
        emit_fn: Callable,
        save_fn: Callable,
        cancel_event: asyncio.Event | None,
        context_status: str = "green",
        context_fill_percentage: float = 0.0,
    ) -> None:
        now = datetime.now(timezone.utc)
        await emit_fn(ChatStreamStartedEvent(
            session_id=session_id, correlation_id=correlation_id, timestamp=now,
        ))

        full_content = ""
        full_thinking = ""
        usage = None
        status = "completed"

        try:
            stream = await stream_fn() if asyncio.iscoroutinefunction(stream_fn) else stream_fn()

            async for event in stream:
                if cancel_event and cancel_event.is_set():
                    status = "cancelled"
                    break

                match event:
                    case ContentDelta(delta=delta):
                        full_content += delta
                        await emit_fn(ChatContentDeltaEvent(
                            correlation_id=correlation_id, delta=delta,
                        ))

                    case ThinkingDelta(delta=delta):
                        full_thinking += delta
                        await emit_fn(ChatThinkingDeltaEvent(
                            correlation_id=correlation_id, delta=delta,
                        ))

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

        if status == "completed" and full_content:
            await save_fn(
                content=full_content,
                thinking=full_thinking or None,
                usage=usage,
            )

        await emit_fn(ChatStreamEndedEvent(
            correlation_id=correlation_id,
            session_id=session_id,
            status=status,
            usage=usage,
            context_status=context_status,
            context_fill_percentage=context_fill_percentage,
            timestamp=datetime.now(timezone.utc),
        ))
