"""Terminal output formatter for the LLM test harness.

Receives stream events from an LLM provider adapter and renders them as
structured, human-readable terminal output suitable for inspection by
both humans and tooling (e.g. Claude Code).
"""

import json
import sys
from collections.abc import AsyncIterator

from backend.modules.llm import (
    ContentDelta,
    ProviderStreamEvent,
    StreamDone,
    StreamError,
    ThinkingDelta,
    ToolCallEvent,
)


class StreamPrinter:
    """Formats provider stream events for clear terminal output."""

    def __init__(self) -> None:
        self._in_thinking = False
        self._in_content = False
        self._thinking_parts: list[str] = []
        self._content_parts: list[str] = []

    async def process(self, events: AsyncIterator[ProviderStreamEvent]) -> None:
        """Iterate over stream events and print them as they arrive."""
        async for event in events:
            match event:
                case ThinkingDelta(delta=delta):
                    if not self._in_thinking:
                        self._in_thinking = True
                        self._in_content = False
                        self._write("\n--- THINKING ---\n")
                    self._thinking_parts.append(delta)
                    self._write(delta)

                case ContentDelta(delta=delta):
                    if not self._in_content:
                        self._in_content = True
                        self._in_thinking = False
                        self._write("\n--- CONTENT ---\n")
                    self._content_parts.append(delta)
                    self._write(delta)

                case ToolCallEvent(name=name, arguments=arguments):
                    self._in_thinking = False
                    self._in_content = False
                    try:
                        pretty_args = json.dumps(
                            json.loads(arguments), indent=2,
                        )
                    except (json.JSONDecodeError, TypeError):
                        pretty_args = arguments
                    self._write(
                        f"\n--- TOOL CALL ---\n"
                        f"Name: {name}\n"
                        f"Arguments: {pretty_args}\n",
                    )

                case StreamDone(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                ):
                    self._write(
                        f"\n--- DONE ---\n"
                        f"Input tokens: {input_tokens if input_tokens is not None else 'unknown'}\n"
                        f"Output tokens: {output_tokens if output_tokens is not None else 'unknown'}\n",
                    )

                case StreamError(error_code=code, message=message):
                    self._write(
                        f"\n--- ERROR ---\n"
                        f"Code: {code}\n"
                        f"Message: {message}\n",
                    )

        # Trailing blank line for separation from whatever comes next.
        self._write("\n")

    def get_full_content(self) -> str:
        """Return all content deltas joined together."""
        return "".join(self._content_parts)

    def get_full_thinking(self) -> str:
        """Return all thinking deltas joined together."""
        return "".join(self._thinking_parts)

    @staticmethod
    def _write(text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()
