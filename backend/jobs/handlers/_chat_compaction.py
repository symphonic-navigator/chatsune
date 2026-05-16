"""Job handler — chat compaction.

Condenses the source range of a chat session into a markdown briefing
and appends a CompactionCheckpoint to the session document. The
inference path reads only the latest checkpoint and slices the message
history from its tail_start_message_id.
"""

import structlog
from datetime import UTC, datetime
from uuid import uuid4

from backend.jobs._errors import UnrecoverableJobError
from backend.jobs._models import JobConfig, JobEntry
from backend.jobs.handlers._budget_helpers import (
    check_and_reserve_budget,
    record_handler_tokens,
)
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

        # Always trust the session document as the source of truth for the
        # previous checkpoint — the payload's ``prev_checkpoint_id`` was
        # captured when the job was scheduled and may be stale if another
        # compaction landed in between. Compare it to ``checkpoints[-1].id``
        # as a sanity check; mismatch is logged but not fatal.
        prev_tail_start_id = None
        previous_summary = None
        prev_checkpoint_id_actual: str | None = None
        checkpoints = session.get("compaction_checkpoints") or []
        if checkpoints:
            latest_cp = checkpoints[-1]
            prev_tail_start_id = latest_cp["tail_start_message_id"]
            previous_summary = latest_cp["summary_markdown"]
            prev_checkpoint_id_actual = latest_cp["id"]
            if prev_checkpoint_id and prev_checkpoint_id != prev_checkpoint_id_actual:
                _log.warning(
                    "compaction.prev_checkpoint_mismatch",
                    session_id=session_id,
                    correlation_id=correlation_id,
                    payload_prev=prev_checkpoint_id,
                    actual_prev=prev_checkpoint_id_actual,
                )

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

        # Defence-in-depth: an empty source range (or a near-empty one)
        # cannot produce a meaningful briefing — the trigger-handler should
        # have caught this, but a race could still let us through.
        source_tokens_initial = sum(int(m.get("token_count") or 0) for m in source_msgs)
        if source_tokens_initial < 200:
            _log.warning(
                "compaction.empty_source",
                session_id=session_id, correlation_id=correlation_id,
                source_msg_count=len(source_msgs),
                source_tokens=source_tokens_initial,
            )
            await _emit_failed(
                event_bus, session_id, correlation_id, job.user_id,
                error_code="too_small", recoverable=False,
                user_message=(
                    "Nothing new to compact since the last snapshot — "
                    "continue the conversation and try again later."
                ),
            )
            return

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

        # Build the prompt up front so we can both reserve the SG-002
        # daily budget against the real input cost and reuse the same
        # text inside ``_call_llm_with_retry`` without re-running the
        # transcript builder.
        from backend.modules.chat._compaction import (
            build_compaction_system_prompt,
            build_compaction_transcript,
        )
        system_prompt_text = build_compaction_system_prompt()
        transcript_text = build_compaction_transcript(
            source_msgs, previous_summary=previous_summary,
        )
        prompt_text_for_budget = system_prompt_text + transcript_text

        # SG-002: reserve budget before the LLM spend. Raises
        # ``UnrecoverableJobError`` when the user has exhausted their
        # daily allowance — caught below and surfaced as a
        # ``budget_exceeded`` failure.
        await check_and_reserve_budget(redis, job.user_id, prompt_text_for_budget)

        markdown, real_input_tokens, real_output_tokens = await _call_llm_with_retry(
            user_id=job.user_id,
            model_unique_id=job.model_unique_id,
            system_prompt=system_prompt_text,
            transcript=transcript_text,
            correlation_id=correlation_id,
        )

        # Record the real spend so the daily counter reflects what we
        # actually consumed. Non-fatal if it fails — the LLM call has
        # already succeeded.
        await record_handler_tokens(
            redis,
            job.user_id,
            prompt_text=prompt_text_for_budget,
            output_text=markdown,
            input_tokens=real_input_tokens,
            output_tokens=real_output_tokens,
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

        # Recompute session-context numbers after compact and persist
        # them so a reload picks up the new (much lower) fill without
        # waiting for the next inference to update the metrics.
        #
        # The bare ``tokens_after + tail_token_count`` formula
        # systematically undercounts because it omits admin prompt,
        # persona, memory, integration extensions, and the
        # ``<conversation_compact>`` envelope around the new markdown.
        # Calling ``assemble()`` with the same arguments inference will
        # use gives the real system-prompt token cost; failure
        # (missing persona, integration error, etc.) falls back to the
        # legacy estimate so the metric write never crashes the job.
        from backend.modules.chat import assemble
        from backend.modules.chat._context import get_ampel_status
        from backend.token_counter import count_tokens as _count_tokens

        extras_obj: ChatSessionExtras | None = None
        try:
            extras_dict = session.get("extras") or {}
            if extras_dict:
                extras_obj = ChatSessionExtras(**extras_dict)
        except Exception:
            _log.warning(
                "compaction.metrics_extras_parse_failed",
                session_id=session_id, correlation_id=correlation_id,
            )

        system_prompt_tokens: int
        try:
            assembled_system_prompt = await assemble(
                user_id=job.user_id,
                persona_id=session.get("persona_id"),
                model_unique_id=job.model_unique_id,
                project_id=session.get("project_id"),
                supports_reasoning=False,
                extras=extras_obj,
                compact_markdown=markdown,
            )
            system_prompt_tokens = _count_tokens(assembled_system_prompt)
        except Exception:
            _log.exception(
                "compaction.metrics_assemble_failed",
                session_id=session_id, correlation_id=correlation_id,
            )
            # Fallback to the old optimistic estimate so the write
            # still happens; next real inference will correct it.
            system_prompt_tokens = tokens_after

        new_used = system_prompt_tokens + tail_token_count
        new_fill = new_used / model_context if model_context else 0.0
        new_status = get_ampel_status(new_fill)
        await repo.update_session_context_metrics(
            session_id,
            status=new_status,
            fill_percentage=new_fill,
            used_tokens=new_used,
            max_tokens=model_context,
        )

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
    except UnrecoverableJobError as exc:
        _log.warning(
            "compaction.budget_exceeded",
            session_id=session_id, correlation_id=correlation_id,
            reason=str(exc),
        )
        await _emit_failed(
            event_bus, session_id, correlation_id, job.user_id,
            error_code="budget_exceeded",
            user_message=(
                "You have exhausted your daily AI usage budget. "
                "Compaction will be available again tomorrow."
            ),
            recoverable=False,
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
    *, user_id, model_unique_id, system_prompt, transcript, correlation_id,
):
    """Call the LLM and validate the markdown. Retry once on validation failure.

    Mirrors the canonical streaming pattern from
    backend/jobs/handlers/_memory_consolidation.py: matches the typed
    stream events (ContentDelta / StreamDone / StreamError) rather than
    duck-typing on a ``delta`` attribute. ``stream_completion`` takes
    positional ``user_id, model_unique_id, request`` plus ``source=``;
    there is no ``correlation_id=`` kwarg, so we only log it locally.

    Returns ``(markdown, input_tokens, output_tokens)`` where the token
    counts come from the adapter's ``StreamDone`` event and may be
    ``None`` for adapters that do not surface them. The caller uses
    these for SG-002 budget accounting.
    """
    from backend.modules.chat._compaction import (
        COMPACTION_RETRY_REMINDER,
        CompactionValidationError,
        validate_compact_markdown,
    )
    from backend.modules.llm import (
        ContentDelta,
        StreamDone,
        StreamError,
        stream_completion,
    )

    last_input_tokens: int | None = None
    last_output_tokens: int | None = None

    for attempt in (1, 2):
        sp = system_prompt + (
            COMPACTION_RETRY_REMINDER if attempt == 2 else ""
        )
        messages = [
            CompletionMessage(role="system", content=[ContentPart(type="text", text=sp)]),
            CompletionMessage(role="user", content=[ContentPart(type="text", text=transcript)]),
        ]
        # Bump retry temperature: the first attempt's rigid 0.3 may have
        # produced a near-identical malformed output on the retry. A
        # touch more variation gives small instruction-following models
        # a real chance to re-emit the missing headings.
        attempt_temperature = 0.3 if attempt == 1 else 0.5
        request = CompletionRequest(
            model=model_unique_id.split(":", 1)[1],
            messages=messages,
            temperature=attempt_temperature,
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
                case StreamDone() as done:
                    last_input_tokens = done.input_tokens
                    last_output_tokens = done.output_tokens
                    break
                case StreamError() as err:
                    raise RuntimeError(
                        f"Compaction stream error: {err.error_code} — {err.message}"
                    )
        markdown = "".join(collected).strip()
        try:
            validate_compact_markdown(markdown)
            return markdown, last_input_tokens, last_output_tokens
        except CompactionValidationError as exc:
            # Log the raw output preview so we can iterate on validation
            # tolerance without re-running the LLM. Cap at 800 chars to
            # keep log lines manageable for long briefings.
            preview = markdown[:800] if markdown else "<empty>"
            _log.warning(
                "compaction.validation_retry",
                correlation_id=correlation_id,
                attempt=attempt,
                reason=str(exc),
                markdown_preview=preview,
                markdown_total_chars=len(markdown),
            )
            if attempt == 2:
                raise
    raise CompactionValidationError("exhausted retries")
