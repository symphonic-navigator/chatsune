"""Internal event models for the LLM adapter streaming layer.

These types represent the normalised stream of events that any provider adapter
may emit. Consumers (e.g. the chat module) receive a ``ProviderStreamEvent``
and dispatch on the concrete type.
"""

from pydantic import BaseModel


class ContentDelta(BaseModel):
    """A fragment of generated text content."""

    delta: str


class ThinkingDelta(BaseModel):
    """A fragment of the model's internal reasoning / thinking step."""

    delta: str


class ToolCallArgsDelta(BaseModel):
    """Provider-stream event: a fragment of a not-yet-finalised tool call.

    Streaming adapters emit one of these per upstream fragment for each tool
    call still being assembled. ``id`` and ``name`` are filled in as soon as
    the provider supplies them; deltas emitted before either field is known
    carry ``None`` and the inference loop performs late backfill.

    ``arguments_delta`` is NOT cumulative — it is the new fragment only.
    """
    index: int
    id: str | None = None
    name: str | None = None
    arguments_delta: str


class ToolCallEvent(BaseModel):
    """A tool call emitted by the model during a streaming response."""

    id: str       # tool-call ID (from provider where available, else synthesised)
    name: str
    arguments: str  # JSON-encoded argument object
    index: int      # OpenAI-style index for parallel calls; used by the
                    # inference loop for late-id backfill


class StreamDone(BaseModel):
    """Signals the end of a successful stream, with optional token-usage data."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None


class StreamError(BaseModel):
    """A terminal error from the upstream provider."""

    # Normalised error codes understood by all consumers:
    #   "invalid_api_key"      — authentication failure
    #   "provider_unavailable" — upstream is down or unreachable
    #   "model_not_found"      — requested model does not exist on the provider
    error_code: str
    message: str


class StreamSlow(BaseModel):
    """Emitted when the upstream stream has been idle for longer than
    ``GUTTER_SLOW_SECONDS`` but has not yet been declared aborted.

    Purely informational — the chat layer propagates a
    ``ChatStreamSlowEvent`` and the frontend shows a subtle "model still
    working" hint until the next content or thinking delta arrives.
    """


class StreamAborted(BaseModel):
    """Emitted when the upstream stream has been idle for longer than
    ``GUTTER_ABORT_SECONDS``. The stream is dead — any previously
    accumulated content should be persisted with ``status="aborted"``.
    """

    # Known values:
    #   "gutter_timeout" — idle abort triggered by the adapter's gutter timer
    reason: str = "gutter_timeout"


class StreamRefused(BaseModel):
    """Provider explicitly signalled a refusal. Terminal event on this stream.

    Either the provider emitted a known refusal marker in done_reason
    (e.g. content_filter), or a dedicated refusal field was present in
    the final chunk. Refusals are distinct from errors: the stream
    itself was healthy, the model simply declined.
    """
    reason: str
    refusal_text: str | None = None


# Union type used as the return type for adapter stream generators.
ProviderStreamEvent = (
    ContentDelta
    | ThinkingDelta
    | ToolCallEvent
    | ToolCallArgsDelta
    | StreamDone
    | StreamError
    | StreamSlow
    | StreamAborted
    | StreamRefused
)
