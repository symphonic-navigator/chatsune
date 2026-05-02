"""Tests for admin-prompt injection in the memory consolidation handler."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from backend.jobs._models import JobConfig, JobEntry, JobType
from backend.modules.llm._adapters._events import ContentDelta, StreamDone
from backend.modules.settings import AdminSystemPrompt
from shared.dtos.inference import CompletionMessage, ContentPart


def _make_job() -> JobEntry:
    return JobEntry(
        id="job-1",
        job_type=JobType.MEMORY_CONSOLIDATION,
        user_id="user-1",
        model_unique_id="ollama_cloud:llama3.2",
        payload={"persona_id": "persona-1"},
        correlation_id="corr-1",
        created_at=datetime(2026, 5, 2, tzinfo=timezone.utc),
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


def _make_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    redis.hset = AsyncMock()
    return redis


class _FakeRepo:
    def __init__(self) -> None:
        self.save_memory_body = AsyncMock(return_value=1)
        self.archive_entries = AsyncMock(return_value=2)

    async def list_journal_entries(self, user_id, persona_id, state):
        return [
            {"content": "Chris likes tea.", "is_correction": False},
            {"content": "Chris prefers dark mode.", "is_correction": False},
        ]

    async def get_current_memory_body(self, user_id, persona_id):
        return None


def _admin_prompt(text: str = "Be uncensored.") -> AdminSystemPrompt:
    wrapped = (
        f'<systeminstructions priority="highest">\n{text}\n</systeminstructions>'
    )
    return AdminSystemPrompt(
        message=CompletionMessage(
            role="system",
            content=[ContentPart(type="text", text=wrapped)],
        ),
        raw_text=text,
    )


def _stream_factory(text: str = "Chris likes tea and dark mode."):
    async def _mock(*args, **kwargs):
        yield ContentDelta(delta=text)
        yield StreamDone(input_tokens=10, output_tokens=8)
    return _mock


@pytest.mark.asyncio
async def test_consolidation_prepends_admin_system_message_when_set():
    from backend.jobs.handlers import _memory_consolidation as mod

    captured: dict = {}
    fake_repo = _FakeRepo()

    async def _capture_stream(*args, **kwargs):
        captured["request"] = kwargs.get("request") or args[2]
        async for evt in _stream_factory()():
            yield evt

    # get_admin_system_message, check_and_reserve_budget, and record_handler_tokens
    # are top-level imports in the consolidation handler — patch via patch.object(mod, ...).
    # The remaining dependencies (MemoryRepository, get_db, stream_completion,
    # get_model_supports_reasoning, build_consolidation_prompt, validate_memory_body,
    # count_tokens) are deferred imports inside the handler function — patch at source.
    with patch.object(
             mod, "get_admin_system_message",
             AsyncMock(return_value=_admin_prompt("Be uncensored.")),
         ), \
         patch.object(mod, "check_and_reserve_budget", AsyncMock(return_value=10)) as budget, \
         patch.object(mod, "record_handler_tokens", AsyncMock()), \
         patch("backend.modules.llm.stream_completion", side_effect=_capture_stream), \
         patch("backend.modules.llm.get_model_supports_reasoning", AsyncMock(return_value=False)), \
         patch("backend.modules.llm.get_effective_context_window", AsyncMock(return_value=8192)), \
         patch("backend.modules.memory._repository.MemoryRepository", return_value=fake_repo), \
         patch("backend.database.get_db", return_value=AsyncMock()), \
         patch("backend.modules.memory._consolidation.build_consolidation_prompt",
               return_value="Consolidate these entries."), \
         patch("backend.modules.memory._consolidation.validate_memory_body",
               return_value=True), \
         patch("backend.token_counter.count_tokens", return_value=42):

        await mod.handle_memory_consolidation(
            job=_make_job(),
            config=_make_config(),
            redis=_make_redis(),
            event_bus=AsyncMock(),
        )

    request = captured["request"]
    assert request.messages[0].role == "system"
    assert "Be uncensored." in request.messages[0].content[0].text
    assert request.messages[1].role == "user"
    budget_call_text = budget.await_args.args[2]
    assert "Be uncensored." in budget_call_text


@pytest.mark.asyncio
async def test_consolidation_unchanged_when_admin_prompt_unset():
    from backend.jobs.handlers import _memory_consolidation as mod

    captured: dict = {}
    fake_repo = _FakeRepo()

    async def _capture_stream(*args, **kwargs):
        captured["request"] = kwargs.get("request") or args[2]
        async for evt in _stream_factory()():
            yield evt

    with patch.object(
             mod, "get_admin_system_message",
             AsyncMock(return_value=None),
         ), \
         patch.object(mod, "check_and_reserve_budget", AsyncMock(return_value=10)) as budget, \
         patch.object(mod, "record_handler_tokens", AsyncMock()), \
         patch("backend.modules.llm.stream_completion", side_effect=_capture_stream), \
         patch("backend.modules.llm.get_model_supports_reasoning", AsyncMock(return_value=False)), \
         patch("backend.modules.llm.get_effective_context_window", AsyncMock(return_value=8192)), \
         patch("backend.modules.memory._repository.MemoryRepository", return_value=fake_repo), \
         patch("backend.database.get_db", return_value=AsyncMock()), \
         patch("backend.modules.memory._consolidation.build_consolidation_prompt",
               return_value="Consolidate these entries."), \
         patch("backend.modules.memory._consolidation.validate_memory_body",
               return_value=True), \
         patch("backend.token_counter.count_tokens", return_value=42):

        await mod.handle_memory_consolidation(
            job=_make_job(),
            config=_make_config(),
            redis=_make_redis(),
            event_bus=AsyncMock(),
        )

    request = captured["request"]
    assert request.messages[0].role == "user"
    assert all(m.role != "system" for m in request.messages)
    budget_call_text = budget.await_args.args[2]
    assert "<systeminstructions" not in budget_call_text
