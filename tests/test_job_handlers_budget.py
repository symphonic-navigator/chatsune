"""Task 17 — daily-token-budget enforcement inside background-job handlers.

These tests pin the three invariants for every handler that spends
tokens on behalf of the user:

    1. The budget is checked BEFORE the LLM call. When the cap has been
       hit the handler aborts with ``UnrecoverableJobError`` and the LLM
       client is never invoked.
    2. After a successful stream the handler records the real spend into
       the user's daily Redis counter.
    3. A Redis hiccup in the recording path must NOT break the handler —
       the LLM call has already succeeded and losing a single accounting
       update is acceptable; the handler logs a warning and carries on.

We use the title-generation handler as the probe because it has the
smallest infrastructure surface (no Mongo, no memory repositories, no
event-bus fan-out) while still exercising the exact same budget helpers
that the other two handlers use.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from backend.jobs._errors import UnrecoverableJobError
from backend.jobs._models import JobConfig, JobEntry, JobType
from backend.modules.llm._adapters._events import ContentDelta, StreamDone


# ---------------------------------------------------------------------------
# Fake redis — only the subset our helpers actually touch.
# ---------------------------------------------------------------------------


class _FakePipeline:
    def __init__(self, store: dict) -> None:
        self._store = store
        self._ops: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def incrby(self, key: str, amount: int):
        self._ops.append(("incrby", key, amount))
        return self

    def expire(self, key: str, seconds: int, nx: bool = False):
        self._ops.append(("expire", key, seconds, nx))
        return self

    async def execute(self):
        results = []
        for op in self._ops:
            if op[0] == "incrby":
                _, key, amount = op
                new_val = int(self._store.get(key, 0)) + amount
                self._store[key] = new_val
                results.append(new_val)
            elif op[0] == "expire":
                results.append(True)
        self._ops.clear()
        return results


class FakeRedis:
    """Minimal in-memory redis standing in for the real client."""

    def __init__(self) -> None:
        self.store: dict = {}

    async def get(self, key: str):
        v = self.store.get(key)
        if v is None:
            return None
        return str(v).encode() if not isinstance(v, bytes) else v

    async def set(self, key: str, value, nx: bool = False, ex: int | None = None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def pipeline(self, transaction: bool = False):
        return _FakePipeline(self.store)

    # Some handlers call hset on tracking keys. Title generation does not,
    # but keep this here for symmetry.
    async def hset(self, key: str, mapping: dict):
        self.store[key] = mapping
        return len(mapping)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _budget_key(user_id: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"safeguard:budget:{user_id}:{today}"


def _make_job() -> JobEntry:
    return JobEntry(
        id="job-1",
        job_type=JobType.TITLE_GENERATION,
        user_id="user-budget",
        model_unique_id="ollama_cloud:llama3.2",
        payload={
            "session_id": "sess-1",
            "messages": [
                {"role": "user", "content": "Tell me about black holes in great detail"},
                {"role": "assistant", "content": "Black holes are regions of spacetime..."},
            ],
        },
        correlation_id="corr-1",
        created_at=datetime(2026, 4, 4, tzinfo=timezone.utc),
    )


def _make_config() -> JobConfig:
    from backend.jobs.handlers._title_generation import handle_title_generation
    return JobConfig(
        handler=handle_title_generation,
        execution_timeout_seconds=60.0,
        reasoning_enabled=False,
        notify=False,
        notify_error=True,
    )


# ---------------------------------------------------------------------------
# 1. Budget check fires BEFORE the LLM call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_check_blocks_llm_call_when_cap_hit(monkeypatch):
    """Pre-load the user's counter to 999/1000; even a 1-token prompt trips."""
    monkeypatch.setenv("JOB_DAILY_TOKEN_BUDGET", "1000")

    redis = FakeRedis()
    redis.store[_budget_key("user-budget")] = 999

    llm_mock = AsyncMock()

    async def _mock_stream(*args, **kwargs):
        llm_mock()  # should never execute
        yield ContentDelta(delta="nope")
        yield StreamDone()

    from backend.jobs.handlers._title_generation import handle_title_generation

    with patch(
        "backend.modules.llm.stream_completion", side_effect=_mock_stream,
    ), patch(
        "backend.modules.chat.update_session_title", AsyncMock(),
    ), patch(
        "backend.modules.llm.get_model_supports_reasoning", return_value=False,
    ):
        with pytest.raises(UnrecoverableJobError):
            await handle_title_generation(
                job=_make_job(),
                config=_make_config(),
                redis=redis,
                event_bus=AsyncMock(),
            )

    llm_mock.assert_not_called()


# ---------------------------------------------------------------------------
# 2. Token recording happens AFTER success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tokens_recorded_after_successful_stream(monkeypatch):
    monkeypatch.setenv("JOB_DAILY_TOKEN_BUDGET", "5000000")

    redis = FakeRedis()

    async def _mock_stream(*args, **kwargs):
        yield ContentDelta(delta="Black Holes Explained")
        # Deliberately omit real usage so the handler falls back to estimates.
        yield StreamDone()

    from backend.jobs.handlers._title_generation import handle_title_generation

    with patch(
        "backend.modules.llm.stream_completion", side_effect=_mock_stream,
    ), patch(
        "backend.modules.chat.update_session_title", AsyncMock(),
    ), patch(
        "backend.modules.llm.get_model_supports_reasoning", return_value=False,
    ):
        await handle_title_generation(
            job=_make_job(),
            config=_make_config(),
            redis=redis,
            event_bus=AsyncMock(),
        )

    stored = redis.store.get(_budget_key("user-budget"))
    assert stored is not None, "budget counter was not updated"
    # The handler records estimate(prompt) + estimate(output) (both > 0).
    assert int(stored) > 0


@pytest.mark.asyncio
async def test_tokens_recorded_uses_adapter_usage_when_present(monkeypatch):
    """When StreamDone carries real counts, those are used verbatim."""
    monkeypatch.setenv("JOB_DAILY_TOKEN_BUDGET", "5000000")

    redis = FakeRedis()

    async def _mock_stream(*args, **kwargs):
        yield ContentDelta(delta="Title")
        yield StreamDone(input_tokens=123, output_tokens=7)

    from backend.jobs.handlers._title_generation import handle_title_generation

    with patch(
        "backend.modules.llm.stream_completion", side_effect=_mock_stream,
    ), patch(
        "backend.modules.chat.update_session_title", AsyncMock(),
    ), patch(
        "backend.modules.llm.get_model_supports_reasoning", return_value=False,
    ):
        await handle_title_generation(
            job=_make_job(),
            config=_make_config(),
            redis=redis,
            event_bus=AsyncMock(),
        )

    assert int(redis.store[_budget_key("user-budget")]) == 130


# ---------------------------------------------------------------------------
# 3. Recording failure is non-fatal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recording_failure_does_not_break_handler(monkeypatch, caplog):
    monkeypatch.setenv("JOB_DAILY_TOKEN_BUDGET", "5000000")

    redis = FakeRedis()

    async def _mock_stream(*args, **kwargs):
        yield ContentDelta(delta="Good Title")
        yield StreamDone()

    from backend.jobs.handlers._title_generation import handle_title_generation

    mock_update = AsyncMock()

    async def _boom(*args, **kwargs):
        raise RuntimeError("redis down")

    with patch(
        "backend.modules.llm.stream_completion", side_effect=_mock_stream,
    ), patch(
        "backend.modules.chat.update_session_title", mock_update,
    ), patch(
        "backend.modules.llm.get_model_supports_reasoning", return_value=False,
    ), patch(
        "backend.jobs.handlers._budget_helpers.record_tokens", side_effect=_boom,
    ):
        with caplog.at_level(logging.WARNING):
            await handle_title_generation(
                job=_make_job(),
                config=_make_config(),
                redis=redis,
                event_bus=AsyncMock(),
            )

    # Handler completed — title was saved despite the recording failure.
    mock_update.assert_awaited_once()
    assert any(
        "budget.record_tokens_failed" in rec.message for rec in caplog.records
    ), "expected a warning log entry about the token-recording failure"
