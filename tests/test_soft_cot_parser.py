import pytest

from backend.modules.llm import ContentDelta, StreamDone, StreamError, ThinkingDelta, ToolCallEvent
from backend.modules.chat._soft_cot_parser import wrap_with_soft_cot_parser


async def _collect(gen):
    out = []
    async for ev in gen:
        out.append(ev)
    return out


async def _stream(*events):
    for ev in events:
        yield ev


@pytest.mark.asyncio
async def test_passthrough_when_no_tags():
    src = _stream(
        ContentDelta(delta="hello "),
        ContentDelta(delta="world"),
        StreamDone(input_tokens=1, output_tokens=2),
    )
    out = await _collect(wrap_with_soft_cot_parser(src))
    assert [type(e).__name__ for e in out] == ["ContentDelta", "ContentDelta", "StreamDone"]
    assert out[0].delta == "hello "
    assert out[1].delta == "world"


@pytest.mark.asyncio
async def test_whole_think_block_in_one_chunk():
    src = _stream(
        ContentDelta(delta="<think>reasoning here</think>final"),
        StreamDone(input_tokens=1, output_tokens=2),
    )
    out = await _collect(wrap_with_soft_cot_parser(src))
    types = [type(e).__name__ for e in out]
    assert "ThinkingDelta" in types
    assert "ContentDelta" in types
    thinking = "".join(e.delta for e in out if isinstance(e, ThinkingDelta))
    content = "".join(e.delta for e in out if isinstance(e, ContentDelta))
    assert thinking == "reasoning here"
    assert content == "final"


@pytest.mark.asyncio
async def test_tag_split_across_chunks():
    src = _stream(
        ContentDelta(delta="<thi"),
        ContentDelta(delta="nk>hello"),
        ContentDelta(delta="</thi"),
        ContentDelta(delta="nk>world"),
        StreamDone(),
    )
    out = await _collect(wrap_with_soft_cot_parser(src))
    thinking = "".join(e.delta for e in out if isinstance(e, ThinkingDelta))
    content = "".join(e.delta for e in out if isinstance(e, ContentDelta))
    assert thinking == "hello"
    assert content == "world"


@pytest.mark.asyncio
async def test_multiple_think_blocks():
    src = _stream(
        ContentDelta(delta="<think>first</think>between<think>second</think>after"),
        StreamDone(),
    )
    out = await _collect(wrap_with_soft_cot_parser(src))
    thinking = "".join(e.delta for e in out if isinstance(e, ThinkingDelta))
    content = "".join(e.delta for e in out if isinstance(e, ContentDelta))
    assert thinking == "firstsecond"
    assert content == "betweenafter"


@pytest.mark.asyncio
async def test_lookalike_tag_passes_through():
    src = _stream(
        ContentDelta(delta="<thirsty> dragon </thirsty> not a think tag"),
        StreamDone(),
    )
    out = await _collect(wrap_with_soft_cot_parser(src))
    content = "".join(e.delta for e in out if isinstance(e, ContentDelta))
    thinking = "".join(e.delta for e in out if isinstance(e, ThinkingDelta))
    assert "thirsty" in content
    assert thinking == ""


@pytest.mark.asyncio
async def test_unclosed_think_flushed_on_done():
    src = _stream(
        ContentDelta(delta="<think>I never finish"),
        StreamDone(),
    )
    out = await _collect(wrap_with_soft_cot_parser(src))
    thinking = "".join(e.delta for e in out if isinstance(e, ThinkingDelta))
    assert thinking == "I never finish"


@pytest.mark.asyncio
async def test_other_event_types_pass_through():
    src = _stream(
        ContentDelta(delta="before "),
        ToolCallEvent(id="t1", name="x", arguments="{}"),
        ContentDelta(delta="after"),
        StreamError(error_code="boom", message="x"),
        StreamDone(),
    )
    out = await _collect(wrap_with_soft_cot_parser(src))
    type_names = [type(e).__name__ for e in out]
    assert "ToolCallEvent" in type_names
    assert "StreamError" in type_names
    assert "StreamDone" in type_names
