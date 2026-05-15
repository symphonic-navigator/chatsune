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
# NB: imports from backend.modules.chat.* are deferred into functions because
# backend.modules.chat.__init__ → _handlers → backend.jobs forms a circular
# import at module-load time (this file is itself imported by
# backend.jobs._registry). All other job handlers follow the same pattern.
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
    from backend.modules.chat._compaction import (
        CompactionValidationError,
        determine_tail_start_index,
        sanitise_source,
        select_source_range,
    )
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
        session = await repo.get_session(session_id, job.user_id)
        if session is None:
            _log.warning("compaction.session_missing", session_id=session_id)
            return

        all_messages = await repo.list_messages(session_id)
        model_context = (
            await get_effective_context_window(job.user_id, job.model_unique_id)
            or 8192
        )

        prev_tail_start_id = None
        previous_summary = None
        checkpoints = session.get("compaction_checkpoints") or []
        if prev_checkpoint_id:
            for cp in checkpoints:
                if cp["id"] == prev_checkpoint_id:
                    prev_tail_start_id = cp["tail_start_message_id"]
                    previous_summary = cp["summary_markdown"]
                    break

        tail_start_idx = determine_tail_start_index(
            all_messages, model_context=model_context,
        )
        source_msgs_raw, tail_msgs = select_source_range(
            all_messages,
            tail_start_index=tail_start_idx,
            prev_tail_start_id=prev_tail_start_id,
        )
        source_msgs = sanitise_source(source_msgs_raw)
        tail_start_message_id = (
            tail_msgs[0]["_id"] if tail_msgs else all_messages[-1]["_id"]
        )

        # Truncation: drop oldest source messages until <= 70% of model context.
        truncation_target = int(model_context * 0.70)
        truncated_count = 0
        while (
            sum(int(m.get("token_count") or 0) for m in source_msgs)
            > truncation_target
        ):
            source_msgs.pop(0)
            truncated_count += 1
        if truncated_count > 0:
            _log.warning(
                "compaction.source.truncated",
                count=truncated_count,
                session_id=session_id,
                correlation_id=correlation_id,
            )

        tokens_before = sum(int(m.get("token_count") or 0) for m in source_msgs)
        tail_token_count = sum(int(m.get("token_count") or 0) for m in tail_msgs)
        last_message_id_before = (
            source_msgs[-1]["_id"] if source_msgs else tail_start_message_id
        )

        await _emit_progress(event_bus, session_id, correlation_id, "calling_model", job.user_id)

        markdown = await _call_llm_with_retry(
            user_id=job.user_id,
            model_unique_id=job.model_unique_id,
            source_msgs=source_msgs,
            previous_summary=previous_summary,
            correlation_id=correlation_id,
        )

        await _emit_progress(event_bus, session_id, correlation_id, "persisting", job.user_id)

        from backend.token_counter import count_tokens
        from backend.modules.chat._models import CompactionCheckpoint

        tokens_after = count_tokens(markdown)
        checkpoint = CompactionCheckpoint(
            id=str(uuid4()),
            created_at=datetime.now(UTC),
            model_unique_id=job.model_unique_id,
            summary_markdown=markdown,
            last_message_id_before=last_message_id_before,
            tail_start_message_id=tail_start_message_id,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            tail_token_count=tail_token_count,
            prev_checkpoint_id=prev_checkpoint_id,
        )
        await repo.append_compaction_checkpoint(session_id, checkpoint)

        # Recompute session-context numbers after compact.
        new_used = tokens_after + tail_token_count
        new_fill = new_used / model_context if model_context else 0.0

        completed = ChatCompactionCompletedEvent(
            session_id=session_id,
            correlation_id=correlation_id,
            checkpoint=CompactionCheckpointDto(**checkpoint.model_dump()),
            tokens_saved=max(0, tokens_before - tokens_after),
            new_context_used_tokens=new_used,
            new_context_fill_percentage=new_fill,
            truncated_message_count=truncated_count,
            timestamp=datetime.now(UTC),
        )
        await event_bus.publish(
            Topics.CHAT_COMPACTION_COMPLETED,
            completed,
            scope=f"session:{session_id}",
            target_user_ids=[job.user_id],
            correlation_id=correlation_id,
        )
    except CompactionValidationError:
        _log.exception("compaction.validation_failed", session_id=session_id)
        await _emit_failed(
            event_bus, session_id, correlation_id, job.user_id,
            error_code="validation_failed",
            user_message="The model could not produce a valid briefing. Please try again.",
            recoverable=True,
        )
    except ValueError:
        _log.exception(
            "compaction.stale_prev_checkpoint",
            session_id=session_id, correlation_id=correlation_id,
        )
        await _emit_failed(
            event_bus, session_id, correlation_id, job.user_id,
            error_code="stale_prev_checkpoint",
            user_message=(
                "The previous compact snapshot references a message that "
                "no longer exists. Start a new conversation to compact again."
            ),
            recoverable=False,
        )
    except Exception:
        _log.exception("compaction.llm_failed", session_id=session_id)
        await _emit_failed(
            event_bus, session_id, correlation_id, job.user_id,
            error_code="llm_failed",
            user_message="The model could not be reached. Please try again.",
            recoverable=True,
        )
    finally:
        await redis.delete(lock_key)


async def _emit_progress(event_bus, session_id, correlation_id, stage, user_id):
    await event_bus.publish(
        Topics.CHAT_COMPACTION_PROGRESS,
        ChatCompactionProgressEvent(
            session_id=session_id,
            correlation_id=correlation_id,
            stage=stage,
            timestamp=datetime.now(UTC),
        ),
        scope=f"session:{session_id}",
        target_user_ids=[user_id],
        correlation_id=correlation_id,
    )


async def _emit_failed(
    event_bus, session_id, correlation_id, user_id,
    *, error_code, user_message, recoverable,
):
    await event_bus.publish(
        Topics.CHAT_COMPACTION_FAILED,
        ChatCompactionFailedEvent(
            session_id=session_id,
            correlation_id=correlation_id,
            error_code=error_code,
            user_message=user_message,
            recoverable=recoverable,
            timestamp=datetime.now(UTC),
        ),
        scope=f"session:{session_id}",
        target_user_ids=[user_id],
        correlation_id=correlation_id,
    )


async def _call_llm_with_retry(
    *, user_id, model_unique_id, source_msgs, previous_summary, correlation_id,
):
    """Call the LLM and validate the markdown. Retry once on validation failure.

    Mirrors the canonical streaming pattern from
    backend/jobs/handlers/_memory_consolidation.py: matches the typed
    stream events (ContentDelta / StreamDone / StreamError) rather than
    duck-typing on a ``delta`` attribute. ``stream_completion`` takes
    positional ``user_id, model_unique_id, request`` plus ``source=``;
    there is no ``correlation_id=`` kwarg, so we only log it locally.
    """
    from backend.modules.chat._compaction import (
        COMPACTION_RETRY_REMINDER,
        CompactionValidationError,
        build_compaction_system_prompt,
        build_compaction_transcript,
        validate_compact_markdown,
    )
    from backend.modules.llm import (
        ContentDelta,
        StreamDone,
        StreamError,
        stream_completion,
    )

    system_prompt = build_compaction_system_prompt()
    transcript = build_compaction_transcript(
        source_msgs, previous_summary=previous_summary,
    )

    for attempt in (1, 2):
        sp = system_prompt + (
            COMPACTION_RETRY_REMINDER if attempt == 2 else ""
        )
        messages = [
            CompletionMessage(role="system", content=[ContentPart(type="text", text=sp)]),
            CompletionMessage(role="user", content=[ContentPart(type="text", text=transcript)]),
        ]
        request = CompletionRequest(
            model=model_unique_id.split(":", 1)[1],
            messages=messages,
            temperature=0.3,
            reasoning=ReasoningCapability(kind="no_reasoning"),
            tools_capability=ToolCapability(supported=False),
            extras=ChatSessionExtras(
                tools_enabled=False, reasoning_mode="off", reasoning_effort=None,
            ),
        )
        collected: list[str] = []
        async for event in stream_completion(
            user_id,
            model_unique_id,
            request,
            source="job:chat_compaction",
        ):
            match event:
                case ContentDelta(delta=delta):
                    collected.append(delta)
                case StreamDone():
                    break
                case StreamError() as err:
                    raise RuntimeError(
                        f"Compaction stream error: {err.error_code} — {err.message}"
                    )
        markdown = "".join(collected).strip()
        try:
            validate_compact_markdown(markdown)
            return markdown
        except CompactionValidationError:
            if attempt == 2:
                raise
            _log.warning(
                "compaction.validation_retry",
                correlation_id=correlation_id,
            )
    raise CompactionValidationError("exhausted retries")
