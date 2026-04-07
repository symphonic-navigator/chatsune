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
# Maximum number of buffered characters that can still be the start of a tag.
# Equal to len(longest_tag) - 1 so we never over-eagerly flush a partial tag.
_MAX_LOOKAHEAD = max(len(_OPEN_TAG), len(_CLOSE_TAG)) - 1


def _is_tag_prefix(text: str, tag: str) -> bool:
    """Return True if *text* is a non-empty prefix of *tag*."""
    return bool(text) and tag.startswith(text)


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
            if not inside_think:
                tag = _OPEN_TAG
                idx = buffer.find(tag)
                if idx != -1:
                    # Found the full open tag — emit prefix, switch state.
                    if idx > 0:
                        events.extend(_flush_outside(buffer[:idx]))
                    buffer = buffer[idx + len(tag):]
                    inside_think = True
                    # Continue the loop to process content after the tag.
                    continue

                # No full tag found.  Flush everything except the last
                # _MAX_LOOKAHEAD chars, which might be the start of a tag.
                tail_start = max(0, len(buffer) - _MAX_LOOKAHEAD)
                safe = buffer[:tail_start]
                tail = buffer[tail_start:]

                # If the tail cannot be a prefix of the open tag, flush it too.
                if not _is_tag_prefix(tail, tag):
                    safe += tail
                    tail = ""

                if safe:
                    events.extend(_flush_outside(safe))
                buffer = tail
                break

            else:
                tag = _CLOSE_TAG
                idx = buffer.find(tag)
                if idx != -1:
                    # Found the full close tag — emit thinking content, switch state.
                    if idx > 0:
                        events.extend(_flush_inside(buffer[:idx]))
                    buffer = buffer[idx + len(tag):]
                    inside_think = False
                    # Continue the loop — there may be more content or another open tag.
                    continue

                # No full close tag yet.  Keep up to _MAX_LOOKAHEAD chars as tail.
                tail_start = max(0, len(buffer) - _MAX_LOOKAHEAD)
                safe = buffer[:tail_start]
                tail = buffer[tail_start:]

                if not _is_tag_prefix(tail, tag):
                    safe += tail
                    tail = ""

                if safe:
                    events.extend(_flush_inside(safe))
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
