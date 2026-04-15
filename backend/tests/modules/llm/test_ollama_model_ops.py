import asyncio
import json
from typing import Any

import httpx
import pytest

from backend.modules.llm._ollama_model_ops import (
    OllamaModelOps,
    map_ollama_error,
)
from backend.modules.llm._pull_registry import PullTaskRegistry
from shared.topics import Topics


class FakeBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict, dict[str, Any]]] = []

    async def publish(self, topic, event, **kwargs):
        payload = event.model_dump() if hasattr(event, "model_dump") else dict(event)
        self.events.append((topic, payload, kwargs))


def _stream_lines(lines: list[str]) -> httpx.Response:
    body = ("\n".join(lines) + "\n").encode()
    return httpx.Response(200, content=body)


@pytest.mark.asyncio
async def test_pull_emits_started_progress_completed_in_order():
    bus = FakeBus()
    reg = PullTaskRegistry()

    progress_lines = [
        json.dumps({"status": "pulling manifest"}),
        json.dumps({"status": "downloading", "digest": "sha256:a",
                    "completed": 10, "total": 100}),
        json.dumps({"status": "success"}),
    ]

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/api/pull"
        return _stream_lines(progress_lines)

    transport = httpx.MockTransport(handler)

    ops = OllamaModelOps(
        base_url="http://fake:11434",
        api_key=None,
        scope="admin-local",
        event_bus=bus,
        registry=reg,
        target_user_ids=["u1"],
        http_transport=transport,
        progress_throttle_seconds=0,
    )

    pull_id = await ops.start_pull(slug="llama3.2")
    h = reg.get(pull_id)
    await h.task

    topics = [ev[0] for ev in bus.events]
    assert topics[0] == Topics.LLM_MODEL_PULL_STARTED
    assert Topics.LLM_MODEL_PULL_PROGRESS in topics
    assert topics[-1] == Topics.LLM_MODEL_PULL_COMPLETED


@pytest.mark.asyncio
async def test_pull_cancel_emits_cancelled_event():
    bus = FakeBus()
    reg = PullTaskRegistry()

    async def slow_handler(req: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200, content=b"")

    transport = httpx.MockTransport(slow_handler)

    ops = OllamaModelOps(
        base_url="http://fake:11434",
        api_key=None,
        scope="admin-local",
        event_bus=bus,
        registry=reg,
        target_user_ids=["u1"],
        http_transport=transport,
        progress_throttle_seconds=0,
    )

    pull_id = await ops.start_pull(slug="llama3.2")
    await asyncio.sleep(0.05)
    reg.cancel("admin-local", pull_id)

    h = reg.get(pull_id)
    if h is not None:
        try:
            await h.task
        except asyncio.CancelledError:
            pass

    topics = [ev[0] for ev in bus.events]
    lifecycle_topics = [t for t in topics if t.startswith("llm.model.pull.")]
    assert Topics.LLM_MODEL_PULL_COMPLETED not in topics
    assert lifecycle_topics[-1] == Topics.LLM_MODEL_PULL_CANCELLED


@pytest.mark.asyncio
async def test_pull_in_stream_error_emits_failed_with_model_not_found():
    """Regression: Ollama surfaces a missing manifest as HTTP 200 + {"error": ...}."""
    bus = FakeBus()
    reg = PullTaskRegistry()

    body = (
        b'{"status":"pulling manifest"}\n'
        b'{"error":"pull model manifest: file does not exist"}\n'
    )

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    transport = httpx.MockTransport(handler)

    ops = OllamaModelOps(
        base_url="http://fake:11434",
        api_key=None,
        scope="admin-local",
        event_bus=bus,
        registry=reg,
        target_user_ids=["u1"],
        http_transport=transport,
        progress_throttle_seconds=0,
    )

    pull_id = await ops.start_pull(slug="xyz:123")
    h = reg.get(pull_id)
    await h.task

    topics = [ev[0] for ev in bus.events]
    assert Topics.LLM_MODEL_PULL_COMPLETED not in topics
    failed = [ev for ev in bus.events if ev[0] == Topics.LLM_MODEL_PULL_FAILED]
    assert len(failed) == 1
    assert failed[0][1]["error_code"] == "model_not_found"
    assert "does not exist" in failed[0][1]["user_message"]


@pytest.mark.asyncio
async def test_pull_cancel_after_stream_finished_does_not_emit_cancelled():
    """Regression: cancel after stream finished must not flip COMPLETED to CANCELLED."""
    bus = FakeBus()
    reg = PullTaskRegistry()

    # Minimal body: immediate "success" line — stream ends right away.
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'{"status":"success"}\n')

    transport = httpx.MockTransport(handler)

    ops = OllamaModelOps(
        base_url="http://fake:11434",
        api_key=None,
        scope="admin-local",
        event_bus=bus,
        registry=reg,
        target_user_ids=["u1"],
        http_transport=transport,
        progress_throttle_seconds=0,
    )

    pull_id = await ops.start_pull(slug="llama3.2")
    h = reg.get(pull_id)
    # Wait for the task to finish cleanly BEFORE cancelling — this exercises
    # the "cancel after completion" path (covers the race window). The shield
    # guarantees that even if cancel had arrived a hair earlier, COMPLETED
    # still wins.
    await h.task
    # Best-effort cancel after completion is a no-op; registry has cleaned up.
    cancelled = reg.cancel("admin-local", pull_id)
    assert cancelled is False

    topics = [ev[0] for ev in bus.events]
    assert Topics.LLM_MODEL_PULL_COMPLETED in topics
    assert Topics.LLM_MODEL_PULL_CANCELLED not in topics


@pytest.mark.asyncio
async def test_pull_network_error_emits_failed_with_unreachable_code():
    bus = FakeBus()
    reg = PullTaskRegistry()

    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    transport = httpx.MockTransport(handler)

    ops = OllamaModelOps(
        base_url="http://fake:11434",
        api_key=None,
        scope="admin-local",
        event_bus=bus,
        registry=reg,
        target_user_ids=["u1"],
        http_transport=transport,
        progress_throttle_seconds=0,
    )

    pull_id = await ops.start_pull(slug="llama3.2")
    h = reg.get(pull_id)
    await h.task

    failed = [ev for ev in bus.events if ev[0] == Topics.LLM_MODEL_PULL_FAILED]
    assert len(failed) == 1
    assert failed[0][1]["error_code"] == "ollama_unreachable"


@pytest.mark.asyncio
async def test_delete_emits_model_deleted_event():
    bus = FakeBus()
    reg = PullTaskRegistry()

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "DELETE"
        assert req.url.path == "/api/delete"
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)

    ops = OllamaModelOps(
        base_url="http://fake:11434",
        api_key=None,
        scope="admin-local",
        event_bus=bus,
        registry=reg,
        target_user_ids=["u1"],
        http_transport=transport,
    )

    await ops.delete("llama3.2:3b")

    topics = [ev[0] for ev in bus.events]
    assert topics == [Topics.LLM_MODEL_DELETED]
    assert bus.events[0][1]["name"] == "llama3.2:3b"


def test_map_ollama_error_connect_error():
    code, msg = map_ollama_error(httpx.ConnectError("refused"))
    assert code == "ollama_unreachable"
    assert msg


def test_map_ollama_error_http_401():
    exc = httpx.HTTPStatusError(
        "u", request=httpx.Request("GET", "http://x"),
        response=httpx.Response(401),
    )
    code, _ = map_ollama_error(exc)
    assert code == "ollama_auth_failed"


def test_map_ollama_error_http_404():
    exc = httpx.HTTPStatusError(
        "u", request=httpx.Request("GET", "http://x"),
        response=httpx.Response(404),
    )
    code, _ = map_ollama_error(exc)
    assert code == "model_not_found"


def test_map_ollama_error_http_other():
    exc = httpx.HTTPStatusError(
        "u", request=httpx.Request("GET", "http://x"),
        response=httpx.Response(500),
    )
    code, _ = map_ollama_error(exc)
    assert code == "pull_stream_error"


def test_map_ollama_error_read_error():
    code, _ = map_ollama_error(httpx.ReadError("truncated"))
    assert code == "pull_stream_error"


def test_map_ollama_error_unknown():
    code, _ = map_ollama_error(RuntimeError("boom"))
    assert code == "unknown"
