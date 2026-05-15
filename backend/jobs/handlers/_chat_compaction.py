"""Job handler — chat compaction.

Condenses the source range of a chat session into a markdown briefing
and appends a CompactionCheckpoint to the session document. The
inference path reads only the latest checkpoint and slices the message
history from its tail_start_message_id.
"""

import structlog
from datetime import UTC, datetime
from uuid import uuid4

from backend.jobs._models import JobConfig, JobEntry
from backend.modules.chat._compaction import (
    COMPACTION_MAX_OUTPUT_TOKENS,
    COMPACTION_RETRY_REMINDER,
    CompactionValidationError,
    build_compaction_system_prompt,
    build_compaction_transcript,
    determine_tail_start_index,
    sanitise_source,
    select_source_range,
    validate_compact_markdown,
)
from shared.events.chat import (
    ChatCompactionCompletedEvent,
    ChatCompactionFailedEvent,
    ChatCompactionProgressEvent,
)
from shared.dtos.chat import CompactionCheckpointDto, ChatSessionExtras
from shared.dtos.inference import CompletionMessage, CompletionRequest, ContentPart
from shared.dtos.llm import ReasoningCapability, ToolCapability
from shared.topics import Topics

_log = structlog.get_logger(__name__)


async def handle_chat_compaction(
    job: JobEntry,
    config: JobConfig,
    redis,
    event_bus,
) -> None:
    """Run the compaction job. See devdocs/specs/2026-05-15-compact-and-continue-design.md §6.2."""
    from backend.database import get_db
    from backend.modules.chat._repository import ChatRepository
    from backend.modules.llm import get_effective_context_window

    token_key = f"job:executed:{job.execution_token}"
    already = await redis.set(token_key, "1", nx=True, ex=48 * 3600)
    if already is None:
        _log.info("job.duplicate_skip token=%s job_id=%s",
                  job.execution_token, job.id)
        return

    session_id = job.payload["session_id"]
    correlation_id = job.payload.get("correlation_id") or job.correlation_id
    prev_checkpoint_id = job.payload.get("prev_checkpoint_id")

    lock_key = f"compaction:lock:{session_id}"

    db = get_db()
    repo = ChatRepository(db)

    try:
        # Stub — wired in 3.6/3.7
        _log.info("compaction.skeleton_run", session_id=session_id)
    finally:
        await redis.delete(lock_key)
