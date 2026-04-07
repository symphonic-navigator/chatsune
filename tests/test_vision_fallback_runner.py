import pytest

from backend.modules.chat._vision_fallback import describe_image, VisionFallbackError


def _async_return(value):
    async def _f(*args, **kwargs):
        return value
    return _f


class _FakeAdapter:
    """Adapter stub where each call delegates to a behaviour fn returning either
    an iterable of events to yield, or an exception to raise."""

    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.calls = 0

    async def stream_completion(self, api_key, request):
        self.calls += 1
        action = self.behaviour(self.calls)
        if isinstance(action, Exception):
            raise action
        for ev in action:
            yield ev


@pytest.mark.asyncio
async def test_success_first_try(monkeypatch):
    from backend.modules.llm import ContentDelta, StreamDone

    def behaviour(call_no):
        return [ContentDelta(delta="a flower"), StreamDone()]

    fake = _FakeAdapter(behaviour)
    monkeypatch.setattr(
        "backend.modules.chat._vision_fallback._get_adapter_for",
        lambda mid: fake,
    )
    monkeypatch.setattr(
        "backend.modules.chat._vision_fallback._get_api_key_for",
        _async_return("k"),
    )

    text = await describe_image("u1", "ollama_cloud:mistral", b"\x89PNG", "image/png")
    assert text == "a flower"
    assert fake.calls == 1


@pytest.mark.asyncio
async def test_retry_once_on_first_failure(monkeypatch):
    from backend.modules.llm import ContentDelta, StreamDone

    def behaviour(call_no):
        if call_no == 1:
            return RuntimeError("cold start")
        return [ContentDelta(delta="success after retry"), StreamDone()]

    fake = _FakeAdapter(behaviour)
    monkeypatch.setattr(
        "backend.modules.chat._vision_fallback._get_adapter_for",
        lambda mid: fake,
    )
    monkeypatch.setattr(
        "backend.modules.chat._vision_fallback._get_api_key_for",
        _async_return("k"),
    )

    text = await describe_image("u1", "ollama_cloud:mistral", b"\x89PNG", "image/png")
    assert text == "success after retry"
    assert fake.calls == 2


@pytest.mark.asyncio
async def test_raises_after_two_failures(monkeypatch):
    def behaviour(call_no):
        return RuntimeError("still cold")

    fake = _FakeAdapter(behaviour)
    monkeypatch.setattr(
        "backend.modules.chat._vision_fallback._get_adapter_for",
        lambda mid: fake,
    )
    monkeypatch.setattr(
        "backend.modules.chat._vision_fallback._get_api_key_for",
        _async_return("k"),
    )

    with pytest.raises(VisionFallbackError):
        await describe_image("u1", "ollama_cloud:mistral", b"\x89PNG", "image/png")
    assert fake.calls == 2
