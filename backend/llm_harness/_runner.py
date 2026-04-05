"""Core runner for the LLM test harness.

Builds CompletionRequests and calls the OllamaCloudAdapter directly —
no database, no authentication layer, no event bus.
"""

import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path

from backend.modules.llm._adapters._ollama_cloud import OllamaCloudAdapter
from backend.modules.llm._adapters._events import (
    ContentDelta,
    ProviderStreamEvent,
    StreamDone,
    StreamError,
    ToolCallEvent,
)
from shared.dtos.inference import (
    CompletionMessage,
    CompletionRequest,
    ContentPart,
    ToolCallResult,
    ToolDefinition,
)


class HarnessRunner:
    """Lightweight runner that builds requests and streams completions."""

    def __init__(self, api_key: str, base_url: str = "https://ollama.com") -> None:
        self._api_key = api_key
        self._base_url = base_url

    def build_messages(
        self,
        system: str | None,
        messages: list[dict],
    ) -> list[CompletionMessage]:
        """Convert raw message dicts into a list of CompletionMessages.

        Each dict must have ``role`` and ``content``. Content may be a plain
        string (wrapped in a single text ContentPart) or a list of part dicts
        with ``type``, ``text``, ``data``, and ``media_type`` fields.
        """
        result: list[CompletionMessage] = []

        if system is not None:
            result.append(CompletionMessage(
                role="system",
                content=[ContentPart(type="text", text=system)],
            ))

        for msg in messages:
            role = msg["role"]
            raw_content = msg["content"]

            if isinstance(raw_content, str):
                parts = [ContentPart(type="text", text=raw_content)]
            else:
                parts = [ContentPart(**part) for part in raw_content]

            result.append(CompletionMessage(role=role, content=parts))

        return result

    def build_request(
        self,
        model: str,
        messages: list[CompletionMessage],
        temperature: float | None = None,
        reasoning: bool = False,
        supports_reasoning: bool = False,
        tools: list[dict] | None = None,
    ) -> CompletionRequest:
        """Assemble a CompletionRequest from the given parameters."""
        tool_defs: list[ToolDefinition] | None = None
        if tools:
            tool_defs = [ToolDefinition(**t) for t in tools]

        return CompletionRequest(
            model=model,
            messages=messages,
            temperature=temperature,
            reasoning_enabled=reasoning,
            supports_reasoning=supports_reasoning,
            tools=tool_defs,
        )

    async def run(
        self,
        request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        """Stream completion events from the adapter without any processing."""
        adapter = OllamaCloudAdapter(base_url=self._base_url)
        async for event in adapter.stream_completion(self._api_key, request):
            yield event

    async def run_with_tools(
        self,
        request: CompletionRequest,
        tool_handler: Callable | None = None,
        max_iterations: int = 5,
    ) -> AsyncIterator[ProviderStreamEvent]:
        """Run the inference loop with optional tool call handling.

        When the model emits tool calls and a ``tool_handler`` is provided,
        each call is executed via ``await tool_handler(name, arguments_dict)``,
        the results are appended to the conversation, and inference re-runs
        (up to ``max_iterations``).

        All events from every iteration are yielded.
        """
        adapter = OllamaCloudAdapter(base_url=self._base_url)
        current_request = request

        for _ in range(max_iterations):
            tool_calls: list[ToolCallEvent] = []
            content_parts: list[str] = []

            async for event in adapter.stream_completion(self._api_key, current_request):
                yield event

                match event:
                    case ToolCallEvent():
                        tool_calls.append(event)
                    case ContentDelta(delta=delta):
                        content_parts.append(delta)
                    case StreamError():
                        return
                    case StreamDone():
                        pass

            # No tool calls or no handler — we are done.
            if not tool_calls or tool_handler is None:
                return

            # Build assistant message with tool calls and collected content.
            assistant_content = "".join(content_parts)
            assistant_msg = CompletionMessage(
                role="assistant",
                content=[ContentPart(type="text", text=assistant_content)] if assistant_content else [],
                tool_calls=[
                    ToolCallResult(id=tc.id, name=tc.name, arguments=tc.arguments)
                    for tc in tool_calls
                ],
            )

            new_messages = list(current_request.messages) + [assistant_msg]

            # Execute each tool call and append the result as a tool message.
            for tc in tool_calls:
                arguments_dict = json.loads(tc.arguments)
                result_str = await tool_handler(tc.name, arguments_dict)
                new_messages.append(CompletionMessage(
                    role="tool",
                    content=[ContentPart(type="text", text=result_str)],
                    tool_call_id=tc.id,
                ))

            current_request = current_request.model_copy(
                update={"messages": new_messages},
            )

        # Exhausted max_iterations — final stream already yielded above.


def load_api_key(path: str = ".llm-test-key") -> str:
    """Read the API key from a local file.

    Raises FileNotFoundError with an informative message if the file
    does not exist.
    """
    key_path = Path(path)
    if not key_path.exists():
        msg = (
            f"API key file not found at '{key_path.resolve()}'. "
            f"Create '{path}' containing your Ollama Cloud API key."
        )
        raise FileNotFoundError(msg)
    return key_path.read_text().strip()
