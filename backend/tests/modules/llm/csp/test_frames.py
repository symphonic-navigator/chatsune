import pytest

from backend.modules.llm._csp._frames import (
    AuthRevokedFrame,
    CancelFrame,
    EngineInfo,
    ErrFrame,
    HandshakeAckFrame,
    HandshakeFrame,
    ModelMeta,
    PingFrame,
    PongFrame,
    ReqFrame,
    ResFrame,
    StreamDelta,
    StreamEndFrame,
    StreamFrame,
    SupersededFrame,
    parse_frame,
)


def test_handshake_roundtrip():
    f = HandshakeFrame(
        csp_version="1.0",
        sidecar_version="1.0.0",
        engine=EngineInfo(type="ollama", version="0.5.0"),
        max_concurrent_requests=2,
        capabilities=["chat_streaming", "tool_calls"],
    )
    raw = f.model_dump_json()
    parsed = parse_frame(raw)
    assert isinstance(parsed, HandshakeFrame)
    assert parsed.engine.type == "ollama"
    assert parsed.max_concurrent_requests == 2


def test_parse_req_list_models():
    raw = '{"type":"req","id":"abc","op":"list_models"}'
    parsed = parse_frame(raw)
    assert isinstance(parsed, ReqFrame)
    assert parsed.op == "list_models"
    assert parsed.body is None


def test_parse_stream_content_delta():
    raw = '{"type":"stream","id":"r1","delta":{"content":"Hel"}}'
    parsed = parse_frame(raw)
    assert isinstance(parsed, StreamFrame)
    assert parsed.delta.content == "Hel"
    assert parsed.delta.reasoning is None
    assert parsed.delta.tool_calls is None


def test_parse_stream_reasoning_delta():
    raw = '{"type":"stream","id":"r1","delta":{"reasoning":"Let me think"}}'
    parsed = parse_frame(raw)
    assert parsed.delta.reasoning == "Let me think"
    assert parsed.delta.content is None


def test_parse_stream_tool_call_fragment():
    raw = (
        '{"type":"stream","id":"r1",'
        '"delta":{"tool_calls":[{"index":0,"id":"call_a","type":"function",'
        '"function":{"name":"get_weather","arguments":"{\\"loc\\":\\"V"}}]}}'
    )
    parsed = parse_frame(raw)
    assert parsed.delta.tool_calls[0]["index"] == 0
    assert parsed.delta.tool_calls[0]["function"]["name"] == "get_weather"


def test_parse_stream_end_with_usage():
    raw = (
        '{"type":"stream_end","id":"r1","finish_reason":"stop",'
        '"usage":{"prompt_tokens":5,"completion_tokens":7,"total_tokens":12}}'
    )
    parsed = parse_frame(raw)
    assert isinstance(parsed, StreamEndFrame)
    assert parsed.finish_reason == "stop"
    assert parsed.usage["total_tokens"] == 12


def test_parse_err_required_fields():
    raw = (
        '{"type":"err","id":"r1","code":"engine_unavailable",'
        '"message":"no engine","recoverable":true}'
    )
    parsed = parse_frame(raw)
    assert isinstance(parsed, ErrFrame)
    assert parsed.recoverable is True


def test_parse_ping_has_no_id():
    parsed = parse_frame('{"type":"ping"}')
    assert isinstance(parsed, PingFrame)


def test_parse_unknown_type_raises():
    with pytest.raises(ValueError):
        parse_frame('{"type":"martian"}')


def test_model_meta_drops_model_without_context_length_validation():
    # The frame model requires context_length; missing → validation error
    with pytest.raises(Exception):
        ModelMeta(slug="x", display_name="X", context_length=None)


from backend.modules.llm._csp._frames import negotiate_version


def test_negotiate_matching_versions():
    assert negotiate_version("1.0", "1.0") == (True, "1.0", [])


def test_negotiate_minor_downgrade_uses_min():
    ok, v, notices = negotiate_version("1.3", "1.1")
    assert ok is True
    assert v == "1.1"
    assert notices == []


def test_negotiate_major_mismatch_rejects():
    ok, v, notices = negotiate_version("2.0", "1.0")
    assert ok is False
    assert v == "1.0"
    assert any("version_unsupported" in n for n in notices)


def test_negotiate_malformed_rejects():
    ok, _, notices = negotiate_version("banana", "1.0")
    assert ok is False
    assert any("version_unsupported" in n for n in notices)
