"""
Soft-CoT stream parser — internal to backend.modules.chat.

Wraps an upstream ProviderStreamEvent async iterator and intercepts inline
``<think>...</think>`` and ``<thinking>...</thinking>`` tags emitted by
non-reasoning models.  Content inside the tags is re-routed as ThinkingDelta
events; all other content and non-ContentDelta events pass through unchanged.

Both tag pairs are recognised because models in the wild emit either form
regardless of system-prompt instructions.  Each opening tag is strictly
matched with its corresponding closing tag (``<think>`` with ``</think>``,
``<thinking>`` with ``</thinking>``); a mismatched closer leaves the parser
in the inside-think state and any remaining buffered content is flushed as
ThinkingDelta when the stream ends — the visible answer is never corrupted.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from backend.modules.llm import (
    ContentDelta,
    ProviderStreamEvent,
    StreamDone,
    ThinkingDelta,
)

_OPEN_TAGS: tuple[str, ...] = ("<think>", "<thinking>")
_CLOSE_TAGS: tuple[str, ...] = ("</think>", "</thinking>")
# Map each opening tag to its corresponding closing tag (strict matching).
_CLOSE_FOR_OPEN: dict[str, str] = {
    "<think>": "</think>",
    "<thinking>": "</thinking>",
}


def _split_safe_and_tail(buffer: str, tags: tuple[str, ...]) -> tuple[str, str]:
    """Split *buffer* into a safely-emittable prefix and a tail that might
    still grow into any tag in *tags*.

    The tail begins at the rightmost ``<`` character whose suffix is still a
    prefix of at least one tag in *tags*. Everything before that ``<`` is
    safe to flush immediately. If no such ``<`` exists, the entire buffer is
    safe.
    """
    # Scan right-to-left for a ``<`` whose suffix can still become any tag.
    idx = buffer.rfind("<")
    while idx != -1:
        candidate = buffer[idx:]
        if any(tag.startswith(candidate) for tag in tags):
            return buffer[:idx], candidate
        # This `<` is not a viable tag start; look for one further left.
        idx = buffer.rfind("<", 0, idx)
    return buffer, ""


def _find_earliest_tag(buffer: str, tags: tuple[str, ...]) -> tuple[int, str]:
    """Return ``(idx, tag)`` for the earliest fully-matched tag in *buffer*.

    If two tags match at the same position, the longer one is preferred (so
    ``<thinking>`` wins over ``<think>`` when both are full matches at the
    same index — though in practice their seventh character differs).
    Returns ``(-1, "")`` if no tag is found.
    """
    best_idx = -1
    best_tag = ""
    for tag in tags:
        i = buffer.find(tag)
        if i == -1:
            continue
        if best_idx == -1 or i < best_idx or (i == best_idx and len(tag) > len(best_tag)):
            best_idx = i
            best_tag = tag
    return best_idx, best_tag


async def wrap_with_soft_cot_parser(
    upstream: AsyncIterator[ProviderStreamEvent],
) -> AsyncIterator[ProviderStreamEvent]:
    """Yield events from *upstream*, rerouting thinking-tag content to
    ThinkingDelta.

    The parser maintains a small lookahead buffer so that tags split across
    chunk boundaries are handled correctly.  Once the buffer can no longer be
    the beginning of any recognised tag, the safe prefix is flushed
    immediately.
    """
    buffer: str = ""
    inside_think: bool = False
    # When inside_think, the specific close tag we are waiting for. Set when
    # an open tag is consumed; cleared when the matching close tag is seen.
    expected_close: str = ""

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
        nonlocal buffer, inside_think, expected_close
        events: list[ProviderStreamEvent] = []

        while True:
            if not inside_think:
                # Look for any opening tag.
                idx, matched = _find_earliest_tag(buffer, _OPEN_TAGS)
                if idx != -1:
                    if idx > 0:
                        events.extend(_flush_outside(buffer[:idx]))
                    buffer = buffer[idx + len(matched):]
                    inside_think = True
                    expected_close = _CLOSE_FOR_OPEN[matched]
                    continue

                # No full open tag found. Split into safe prefix + tail.
                safe, tail = _split_safe_and_tail(buffer, _OPEN_TAGS)
                if safe:
                    events.extend(_flush_outside(safe))
                buffer = tail
                break
            else:
                # Inside thinking: look strictly for the matching close tag.
                tag = expected_close
                idx = buffer.find(tag)
                if idx != -1:
                    if idx > 0:
                        events.extend(_flush_inside(buffer[:idx]))
                    buffer = buffer[idx + len(tag):]
                    inside_think = False
                    expected_close = ""
                    continue

                # No full close tag yet. The tail guards only the expected
                # close tag — strict matching means a partial of the *other*
                # close tag is genuine thinking text.
                safe, tail = _split_safe_and_tail(buffer, (tag,))
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
