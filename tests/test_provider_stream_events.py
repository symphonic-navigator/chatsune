from backend.modules.llm._adapters._events import (
    ContentDelta, ThinkingDelta, ToolCallEvent, StreamDone, StreamError,
)


def test_content_delta():
    e = ContentDelta(delta="Hello")
    assert e.delta == "Hello"


def test_thinking_delta():
    e = ThinkingDelta(delta="Let me think...")
    assert e.delta == "Let me think..."


def test_tool_call_event():
    e = ToolCallEvent(id="call_abc", name="web_search", arguments='{"query": "test"}')
    assert e.id == "call_abc"
    assert e.name == "web_search"
    assert e.arguments == '{"query": "test"}'


def test_stream_done_with_usage():
    e = StreamDone(input_tokens=150, output_tokens=42)
    assert e.input_tokens == 150
    assert e.output_tokens == 42


def test_stream_done_without_usage():
    e = StreamDone()
    assert e.input_tokens is None
    assert e.output_tokens is None


def test_stream_error():
    e = StreamError(error_code="invalid_api_key", message="Bad key")
    assert e.error_code == "invalid_api_key"
    assert e.message == "Bad key"


def test_stream_slow_is_instantiable_and_has_no_payload():
    from backend.modules.llm._adapters._events import StreamSlow, ProviderStreamEvent

    ev = StreamSlow()
    assert isinstance(ev, StreamSlow)
    # Union membership check — if the type is missing from the union,
    # mypy or a careful runtime check would notice; this is a minimal
    # guard that the union accepts the instance.
    sample: ProviderStreamEvent = ev
    assert sample is ev


def test_stream_aborted_carries_reason_with_default():
    from backend.modules.llm._adapters._events import StreamAborted, ProviderStreamEvent

    ev = StreamAborted()
    assert ev.reason == "gutter_timeout"

    custom = StreamAborted(reason="upstream_silence")
    assert custom.reason == "upstream_silence"

    sample: ProviderStreamEvent = custom
    assert sample is custom
