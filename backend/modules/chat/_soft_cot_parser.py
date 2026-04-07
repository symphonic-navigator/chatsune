"""
Soft-CoT stream parser — internal to backend.modules.chat.

Wraps an upstream ProviderStreamEvent async iterator and intercepts inline
``<think>...</think>`` tags emitted by non-reasoning models when Soft-CoT is
active.  Content inside the tags is re-routed as ThinkingDelta events; all
other content and non-ContentDelta events pass through unchanged.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from backend.modules.llm import (
    ContentDelta,
    ProviderStreamEvent,
    StreamDone,
    ThinkingDelta,
)

_OPEN_TAG = "<think>"
_CLOSE_TAG = "</think>"


def _split_safe_and_tail(buffer: str, tag: str) -> tuple[str, str]:
    """Split *buffer* into a safely-emittable prefix and a tail that might
    still grow into *tag*.

    The tail begins at the rightmost ``<`` character whose suffix is still a
    prefix of *tag*. Everything before that ``<`` is safe to flush
    immediately. If no such ``<`` exists, the entire buffer is safe.
    """
    # Scan right-to-left for a ``<`` whose suffix can still become *tag*.
    idx = buffer.rfind("<")
    while idx != -1:
        candidate = buffer[idx:]
        if tag.startswith(candidate):
            return buffer[:idx], candidate
        # This `<` is not a viable tag start; look for one further left.
        idx = buffer.rfind("<", 0, idx)
    return buffer, ""


async def wrap_with_soft_cot_parser(
    upstream: AsyncIterator[ProviderStreamEvent],
) -> AsyncIterator[ProviderStreamEvent]:
    """Yield events from *upstream*, rerouting ``<think>`` content to ThinkingDelta.

    The parser maintains a small lookahead buffer so that tags split across
    chunk boundaries are handled correctly.  Once the buffer can no longer be
    the beginning of either tag, the safe prefix is flushed immediately.
    """
    buffer: str = ""
    inside_think: bool = False

    def _flush_outside(text: str) -> list[ProviderStreamEvent]:
        """Emit safe prefix content as ContentDelta events (may be empty list)."""
        if text:
            return [ContentDelta(delta=text)]
        return []

    def _flush_inside(text: str) -> list[ProviderStreamEvent]:
        """Emit safe prefix content as ThinkingDelta events (may be empty list)."""
        if text:
            return [ThinkingDelta(delta=text)]
        return []

    def _process_buffer() -> list[ProviderStreamEvent]:
        """Drain the buffer as far as possible, returning accumulated events."""
        nonlocal buffer, inside_think
        events: list[ProviderStreamEvent] = []

        while True:
            tag = _OPEN_TAG if not inside_think else _CLOSE_TAG
            flush = _flush_outside if not inside_think else _flush_inside

            idx = buffer.find(tag)
            if idx != -1:
                # Found the full tag — emit prefix, switch state, loop again
                # in case another tag follows in the same buffer.
                if idx > 0:
                    events.extend(flush(buffer[:idx]))
                buffer = buffer[idx + len(tag):]
                inside_think = not inside_think
                continue

            # No full tag found. Split the buffer into a safe prefix that can
            # be emitted immediately and a tail that might still grow into a
            # tag on the next chunk.
            safe, tail = _split_safe_and_tail(buffer, tag)
            if safe:
                events.extend(flush(safe))
            buffer = tail
            break

        return events

    async for event in upstream:
        if isinstance(event, ContentDelta):
            buffer += event.delta
            for ev in _process_buffer():
                yield ev

        elif isinstance(event, StreamDone):
            # Flush remaining buffer before yielding StreamDone.
            if buffer:
                if inside_think:
                    yield ThinkingDelta(delta=buffer)
                else:
                    yield ContentDelta(delta=buffer)
                buffer = ""
            yield event

        else:
            # ToolCallEvent, StreamError, and any future event types pass through.
            yield event
