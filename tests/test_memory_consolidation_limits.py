"""Tests for H-001 token-length guard in the memory consolidation handler."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from backend.jobs._errors import UnrecoverableJobError
from backend.jobs._models import JobConfig, JobEntry, JobType
from backend.modules.llm._adapters._events import ContentDelta, StreamDone


def _make_job() -> JobEntry:
    return JobEntry(
        id="job-1",
        job_type=JobType.MEMORY_CONSOLIDATION,
        user_id="user-1",
        model_unique_id="ollama_cloud:llama3.2",
        payload={"persona_id": "persona-1"},
        correlation_id="corr-1",
        created_at=datetime(2026, 4, 4, tzinfo=timezone.utc),
    )


def _make_config() -> JobConfig:
    from backend.jobs.handlers._memory_consolidation import handle_memory_consolidation
    return JobConfig(
        handler=handle_memory_consolidation,
        execution_timeout_seconds=300.0,
        reasoning_enabled=False,
        notify=True,
        notify_error=True,
    )


class _FakeRepo:
    def __init__(
        self,
        *,
        existing_body: str | None,
        entries: list[dict],
    ) -> None:
        self._existing_body = existing_body
        self._entries = entries
        self.save_memory_body = AsyncMock(return_value=1)
        self.archive_entries = AsyncMock(return_value=len(entries))

    async def list_journal_entries(self, user_id, persona_id, state):
        return self._entries

    async def get_current_memory_body(self, user_id, persona_id):
        if self._existing_body is None:
            return None
        return {"content": self._existing_body}


def _make_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)  # first execution
    redis.hset = AsyncMock()
    return redis


def _stream_factory(text: str):
    async def _mock_stream(*args, **kwargs):
        yield ContentDelta(delta=text)
        yield StreamDone(input_tokens=10, output_tokens=5)
    return _mock_stream


@pytest.mark.asyncio
async def test_small_body_proceeds_normally():
    from backend.jobs.handlers._memory_consolidation import handle_memory_consolidation

    repo = _FakeRepo(
        existing_body="Chris prefers dark mode.",
        entries=[{"content": "Chris likes tea.", "is_correction": False}],
    )
    llm = AsyncMock(side_effect=_stream_factory("Chris prefers dark mode and tea."))

    with patch(
        "backend.modules.memory._repository.MemoryRepository",
        return_value=repo,
    ), patch(
        "backend.database.get_db", return_value=AsyncMock(),
    ), patch(
        "backend.modules.llm.stream_completion", side_effect=_stream_factory(
            "Chris prefers dark mode and tea.",
        ),
    ) as mock_stream, patch(
        "backend.modules.llm.get_model_supports_reasoning", AsyncMock(return_value=False),
    ), patch(
        "backend.modules.llm.get_effective_context_window", AsyncMock(return_value=8192),
    ), patch(
        "backend.jobs.handlers._memory_consolidation.get_admin_system_message",
        AsyncMock(return_value=None),
    ), patch(
        "backend.jobs.handlers._memory_consolidation.check_and_reserve_budget",
        AsyncMock(return_value=10),
    ), patch(
        "backend.jobs.handlers._memory_consolidation.record_handler_tokens",
        AsyncMock(),
    ), patch(
        "backend.token_counter.count_tokens", return_value=42,
    ):
        await handle_memory_consolidation(
            job=_make_job(),
            config=_make_config(),
            redis=_make_redis(),
            event_bus=AsyncMock(),
        )

    assert mock_stream.called
    repo.save_memory_body.assert_awaited_once()


@pytest.mark.asyncio
async def test_huge_body_is_truncated_handler_proceeds():
    from backend.jobs.handlers._memory_consolidation import handle_memory_consolidation

    huge = "X" * 100_000  # ~33k estimated tokens, far over window
    repo = _FakeRepo(
        existing_body=huge,
        entries=[{"content": "Small entry.", "is_correction": False}],
    )

    captured_prompts: list[str] = []

    async def _mock_stream(user_id, provider_id, request, source):
        # Capture the user-message content to verify truncation.
        for msg in request.messages:
            for part in msg.content:
                captured_prompts.append(part.text)
        yield ContentDelta(delta="New body")
        yield StreamDone()

    with patch(
        "backend.modules.memory._repository.MemoryRepository",
        return_value=repo,
    ), patch(
        "backend.database.get_db", return_value=AsyncMock(),
    ), patch(
        "backend.modules.llm.stream_completion", side_effect=_mock_stream,
    ), patch(
        "backend.modules.llm.get_model_supports_reasoning", AsyncMock(return_value=False),
    ), patch(
        "backend.modules.llm.get_effective_context_window", AsyncMock(return_value=8192),
    ), patch(
        "backend.jobs.handlers._memory_consolidation.get_admin_system_message",
        AsyncMock(return_value=None),
    ), patch(
        "backend.jobs.handlers._memory_consolidation.check_and_reserve_budget",
        AsyncMock(return_value=10),
    ), patch(
        "backend.jobs.handlers._memory_consolidation.record_handler_tokens",
        AsyncMock(),
    ), patch(
        "backend.token_counter.count_tokens", return_value=42,
    ):
        await handle_memory_consolidation(
            job=_make_job(),
            config=_make_config(),
            redis=_make_redis(),
            event_bus=AsyncMock(),
        )

    assert captured_prompts, "LLM was not called"
    full_prompt = captured_prompts[0]
    assert "earlier memory truncated" in full_prompt
    # Truncated body keeps int(8192 * 0.4 * 3) = 9830 chars, not all 100k.
    assert len(full_prompt) < 20_000
    repo.save_memory_body.assert_awaited_once()


@pytest.mark.asyncio
async def test_huge_body_and_entries_raises_unrecoverable():
    from backend.jobs.handlers._memory_consolidation import handle_memory_consolidation

    huge_body = "X" * 100_000
    huge_entries = [
        {"content": "Y" * 50_000, "is_correction": False}
        for _ in range(5)
    ]
    repo = _FakeRepo(existing_body=huge_body, entries=huge_entries)

    mock_stream = AsyncMock()

    with patch(
        "backend.modules.memory._repository.MemoryRepository",
        return_value=repo,
    ), patch(
        "backend.database.get_db", return_value=AsyncMock(),
    ), patch(
        "backend.modules.llm.stream_completion", mock_stream,
    ), patch(
        "backend.modules.llm.get_model_supports_reasoning", AsyncMock(return_value=False),
    ), patch(
        "backend.modules.llm.get_effective_context_window", AsyncMock(return_value=8192),
    ), patch(
        "backend.jobs.handlers._memory_consolidation.get_admin_system_message",
        AsyncMock(return_value=None),
    ):
        with pytest.raises(UnrecoverableJobError, match="too large"):
            await handle_memory_consolidation(
                job=_make_job(),
                config=_make_config(),
                redis=_make_redis(),
                event_bus=AsyncMock(),
            )

    mock_stream.assert_not_called()
    repo.save_memory_body.assert_not_called()
