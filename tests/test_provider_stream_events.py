from backend.modules.llm._adapters._events import (
    ContentDelta, ThinkingDelta, ToolCallEvent, StreamDone, StreamError,
    StreamSlow, StreamAborted, ProviderStreamEvent,
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
    ev = StreamSlow()
    assert isinstance(ev, StreamSlow)
    # Truly no payload — guards against accidental field additions.
    assert StreamSlow.model_fields == {}
    # Union membership check.
    sample: ProviderStreamEvent = ev
    assert sample is ev


def test_stream_aborted_carries_reason_with_default():
    ev = StreamAborted()
    assert ev.reason == "gutter_timeout"

    custom = StreamAborted(reason="upstream_silence")
    assert custom.reason == "upstream_silence"

    sample: ProviderStreamEvent = custom
    assert sample is custom


def test_stream_refused_event_fields():
    from backend.modules.llm._adapters._events import StreamRefused
    ev = StreamRefused(reason="content_filter")
    assert ev.reason == "content_filter"
    assert ev.refusal_text is None

    ev2 = StreamRefused(reason="refusal", refusal_text="no can do")
    assert ev2.refusal_text == "no can do"


def test_stream_refused_is_member_of_provider_stream_event_union():
    from backend.modules.llm._adapters._events import (
        ProviderStreamEvent,
        StreamRefused,
    )
    import typing
    args = typing.get_args(ProviderStreamEvent)
    assert StreamRefused in args
