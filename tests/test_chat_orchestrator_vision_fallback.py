"""Tests for the _resolve_image_attachments_for_inference helper.

These tests bypass run_inference entirely — they import and invoke the helper
directly so they can be run without a running database or event bus.
"""

import pytest
from shared.dtos.inference import ContentPart
from shared.events.chat import ChatVisionDescriptionEvent
from backend.modules.chat._orchestrator import _resolve_image_attachments_for_inference
from backend.modules.chat._vision_fallback import VisionFallbackError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_file(
    file_id: str = "file-1",
    media_type: str = "image/png",
    data: bytes | None = b"\x89PNG",
    display_name: str = "test.png",
) -> dict:
    return {
        "_id": file_id,
        "media_type": media_type,
        "data": data,
        "display_name": display_name,
    }


def _capture(bucket: list):
    async def _emit(event):
        bucket.append(event)
    return _emit


def _async_return(value):
    async def _fn(*args, **kwargs):
        return value
    return _fn


def _async_raise(exc):
    async def _fn(*args, **kwargs):
        raise exc
    return _fn


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_no_fallback_returns_placeholder_text_part():
    """Non-vision model, no fallback configured → placeholder text part, no events."""
    events: list = []
    parts, snapshots, _ = await _resolve_image_attachments_for_inference(
        user_id="u1",
        files=[_make_file()],
        supports_vision=False,
        vision_fallback_model=None,
        emit_event=_capture(events),
        correlation_id="cid-1",
    )

    assert len(parts) == 1
    assert parts[0].type == "text"
    assert "test.png" in parts[0].text
    assert "omitted" in parts[0].text.lower() or "image" in parts[0].text.lower()
    assert snapshots == []
    assert events == []


async def test_main_model_supports_vision_uses_image_part():
    """Vision-capable model → image ContentPart, fallback not used, no events."""
    events: list = []
    parts, snapshots, _ = await _resolve_image_attachments_for_inference(
        user_id="u1",
        files=[_make_file()],
        supports_vision=True,
        vision_fallback_model="ollama_cloud:llava",
        emit_event=_capture(events),
        correlation_id="cid-2",
    )

    assert len(parts) == 1
    assert parts[0].type == "image"
    assert snapshots == []
    assert events == []


async def test_cache_hit_skips_describe_call(monkeypatch):
    """Cache hit → describe_image never called, text part contains cached description, one success event."""
    describe_calls: list = []

    async def _fake_describe(*args, **kwargs):
        describe_calls.append(args)
        return "should not be used"

    monkeypatch.setattr(
        "backend.modules.chat._orchestrator.get_cached_vision_description",
        _async_return("cached description"),
    )
    monkeypatch.setattr(
        "backend.modules.chat._orchestrator.describe_image",
        _fake_describe,
    )

    events: list = []
    parts, snapshots, _ = await _resolve_image_attachments_for_inference(
        user_id="u1",
        files=[_make_file()],
        supports_vision=False,
        vision_fallback_model="ollama_cloud:llava",
        emit_event=_capture(events),
        correlation_id="cid-3",
    )

    assert len(describe_calls) == 0
    assert len(parts) == 1
    assert parts[0].type == "text"
    assert "cached description" in parts[0].text
    assert len(snapshots) == 1
    assert snapshots[0]["text"] == "cached description"
    assert len(events) == 1
    assert isinstance(events[0], ChatVisionDescriptionEvent)
    assert events[0].status == "success"


async def test_cache_miss_calls_describe_and_stores(monkeypatch):
    """Cache miss → describe_image called once, result stored, pending+success events emitted."""
    store_calls: list = []

    async def _fake_store(*args, **kwargs):
        store_calls.append(args)

    describe_calls: list = []

    async def _fake_describe(*args, **kwargs):
        describe_calls.append(args)
        return "fresh description"

    monkeypatch.setattr(
        "backend.modules.chat._orchestrator.get_cached_vision_description",
        _async_return(None),
    )
    monkeypatch.setattr(
        "backend.modules.chat._orchestrator.describe_image",
        _fake_describe,
    )
    monkeypatch.setattr(
        "backend.modules.chat._orchestrator.store_vision_description",
        _fake_store,
    )

    events: list = []
    parts, snapshots, _ = await _resolve_image_attachments_for_inference(
        user_id="u1",
        files=[_make_file()],
        supports_vision=False,
        vision_fallback_model="ollama_cloud:llava",
        emit_event=_capture(events),
        correlation_id="cid-4",
    )

    assert len(describe_calls) == 1
    assert len(store_calls) == 1
    assert len(parts) == 1
    assert "fresh description" in parts[0].text
    assert len(snapshots) == 1
    assert snapshots[0]["text"] == "fresh description"
    assert [e.status for e in events] == ["pending", "success"]


async def test_describe_failure_emits_error_event_and_continues(monkeypatch):
    """describe_image raises VisionFallbackError → placeholder text part, pending+error events."""
    monkeypatch.setattr(
        "backend.modules.chat._orchestrator.get_cached_vision_description",
        _async_return(None),
    )
    monkeypatch.setattr(
        "backend.modules.chat._orchestrator.describe_image",
        _async_raise(VisionFallbackError("boom")),
    )

    events: list = []
    parts, snapshots, _ = await _resolve_image_attachments_for_inference(
        user_id="u1",
        files=[_make_file()],
        supports_vision=False,
        vision_fallback_model="ollama_cloud:llava",
        emit_event=_capture(events),
        correlation_id="cid-5",
    )

    assert len(parts) == 1
    assert parts[0].type == "text"
    text_lower = parts[0].text.lower()
    assert "vision fallback failed" in text_lower or "image:" in text_lower
    assert snapshots == []
    assert [e.status for e in events] == ["pending", "error"]
    assert events[1].error == "boom"


async def test_multiple_images_one_call_per_image(monkeypatch):
    """Two cache-miss images → describe called twice, two snapshots in order, both texts present."""
    descriptions = ["desc 1", "desc 2"]
    call_index = [0]

    async def _fake_describe(*args, **kwargs):
        idx = call_index[0]
        call_index[0] += 1
        return descriptions[idx]

    monkeypatch.setattr(
        "backend.modules.chat._orchestrator.get_cached_vision_description",
        _async_return(None),
    )
    monkeypatch.setattr(
        "backend.modules.chat._orchestrator.describe_image",
        _fake_describe,
    )
    monkeypatch.setattr(
        "backend.modules.chat._orchestrator.store_vision_description",
        _async_return(None),
    )

    files = [
        _make_file(file_id="f1", display_name="a.png"),
        _make_file(file_id="f2", display_name="b.png"),
    ]

    events: list = []
    parts, snapshots, _ = await _resolve_image_attachments_for_inference(
        user_id="u1",
        files=files,
        supports_vision=False,
        vision_fallback_model="ollama_cloud:llava",
        emit_event=_capture(events),
        correlation_id="cid-6",
    )

    assert call_index[0] == 2
    assert len(snapshots) == 2
    assert snapshots[0]["text"] == "desc 1"
    assert snapshots[1]["text"] == "desc 2"
    assert any("desc 1" in p.text for p in parts)
    assert any("desc 2" in p.text for p in parts)
