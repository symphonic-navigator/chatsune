"""Per-conversation import job handler.

Reads one conversation document from ``chatgpt_import_conversations``,
parses its ``raw_data`` field, builds a CreateImportedSessionRequest,
calls the chat module's public ``create_imported_session`` API, then
records the link back into the conversation document and resets the
parent import's TTL.

Memory-batch trigger: each successful per-conversation job bumps
``conversations_imported`` on the matching
``chatgpt_import_memory_batches`` row; each terminal failure (parse
error, no convertible messages, missing conversation) bumps
``permanent_failures``. When ``imported + failures == target_count``
the handler atomically claims the row's ``pending → running``
transition and submits the
:class:`backend.jobs._models.JobType.CHATGPT_IMPORT_MEMORY_BATCH` job
exactly once.

A note on the ``create_imported_session`` failure path: that branch
re-raises, allowing the job system to retry. We deliberately do **not**
bump ``permanent_failures`` from there — the failure may yet succeed on
retry and we'd otherwise count one failure per retry attempt. The
limitation: if all retries are exhausted, the job goes to its terminal
"failed" state without flipping our counter, leaving the batch stuck.
This is the same edge case called out in the spec under "user
mitigation = re-import the failed conversation" (§7.2).
"""
from __future__ import annotations

from datetime import UTC, datetime

import structlog

from backend.database import get_db
from backend.jobs._models import JobConfig, JobEntry, JobType
from backend.modules.chatgpt_import._memory_batch_repository import (
    ChatGptImportMemoryBatchRepository,
)
from backend.modules.chatgpt_import._parser import parse_conversation
from backend.modules.chatgpt_import._repository import ChatGptImportRepository
from backend.modules.chatgpt_import._session_builder import (
    build_imported_session_request,
)
from shared.events.chatgpt_import import (
    ChatGptImportConversationImportFailedEvent,
    ChatGptImportConversationImportedEvent,
)
from shared.topics import Topics

_log = structlog.get_logger(__name__)


async def handle_chatgpt_import_conversation(
    job: JobEntry,
    config: JobConfig,
    redis,
    event_bus,
) -> None:
    payload = job.payload
    user_id = payload["user_id"]
    import_id = payload["import_id"]
    chatgpt_conversation_id = payload["chatgpt_conversation_id"]
    persona_id = payload["persona_id"]
    correlation_id = payload.get("correlation_id") or job.correlation_id
    # New payload field — older jobs already on the queue may not carry
    # it. We log and skip the batch trigger entirely rather than
    # crashing on KeyError. See the matching note in
    # ``ChatGptImportService.trigger_conversation_imports``.
    persona_target_count: int | None = payload.get("persona_target_count")

    db = get_db()
    repo = ChatGptImportRepository(db)
    batch_repo = ChatGptImportMemoryBatchRepository(db)
    scope_import = f"chatgpt_import:{import_id}"
    scope_persona = f"persona:{persona_id}"

    async def _publish_failure(error_code: str, error_message: str) -> None:
        event = ChatGptImportConversationImportFailedEvent(
            import_id=import_id,
            chatgpt_conversation_id=chatgpt_conversation_id,
            persona_id=persona_id,
            error_code=error_code,
            error_message=error_message,
            correlation_id=correlation_id,
            timestamp=datetime.now(UTC),
        )
        await event_bus.publish(
            Topics.CHATGPT_IMPORT_CONVERSATION_IMPORT_FAILED,
            event,
            scope=scope_import,
            target_user_ids=[user_id],
            correlation_id=correlation_id,
        )

    async def _record_permanent_failure() -> None:
        """Bump ``permanent_failures`` on the batch row and maybe submit.

        Called only from the three terminal non-raise branches:
        conversation_not_found, parse_failed, and no_convertible_messages.
        The generic except at the end of this handler re-raises, so we
        intentionally do **not** bump from there — the job will retry,
        and a real terminal counts as zero failures from our point of
        view (see module docstring caveat).
        """
        if persona_target_count is None:
            _log.warning(
                "chatgpt_import.memory.batch.trigger.missing_target_count",
                import_id=import_id,
                persona_id=persona_id,
            )
            return
        updated = await batch_repo.increment_failures(import_id, persona_id)
        if updated is None:
            _log.warning(
                "chatgpt_import.memory.batch.trigger.batch_missing",
                import_id=import_id,
                persona_id=persona_id,
            )
            return
        await _maybe_submit_batch(updated)

    async def _maybe_submit_batch(batch_doc: dict) -> None:
        """If the counter quorum is reached, claim+submit the batch job.

        Concurrency: ``claim_running`` only succeeds for the first caller
        that observes ``state="pending"``. A second caller arriving at
        the same moment sees ``state="running"`` and bails. The pre-check
        on ``imported + failures == target_count`` is a cheap early exit;
        the atomic guarantee is the state filter inside
        ``claim_running``.
        """
        target = int(batch_doc.get("target_count", 0))
        imported = int(batch_doc.get("conversations_imported", 0))
        failures = int(batch_doc.get("permanent_failures", 0))
        if imported + failures != target:
            return
        # Resolve session_ids chronologically from the conversations
        # collection. ``list_imported_session_ids_chronological`` sorts
        # by the original ChatGPT ``create_time``.
        session_ids = await repo.list_imported_session_ids_chronological(
            import_id=import_id, persona_id=persona_id,
        )
        claimed = await batch_repo.claim_running(
            import_id=import_id,
            persona_id=persona_id,
            session_ids=session_ids,
        )
        if claimed is None:
            # Lost the race or already past pending — fine, someone else
            # owns the batch lifecycle now.
            return
        from backend.jobs import submit
        await submit(
            JobType.CHATGPT_IMPORT_MEMORY_BATCH,
            user_id=user_id,
            model_unique_id=claimed["model_unique_id"],
            payload={
                "import_id": import_id,
                "persona_id": persona_id,
                "force_budget": False,
            },
            correlation_id=correlation_id,
        )

    conv_doc = await repo.get_conversation(
        user_id=user_id,
        import_id=import_id,
        chatgpt_conversation_id=chatgpt_conversation_id,
    )
    if not conv_doc:
        await _publish_failure(
            "conversation_not_found",
            "Conversation no longer in import",
        )
        await _record_permanent_failure()
        return

    try:
        parsed = parse_conversation(conv_doc.get("raw_data") or {})
    except Exception as exc:  # noqa: BLE001
        _log.exception(
            "chatgpt_import.conversation.parse_failed",
            import_id=import_id,
            chatgpt_conversation_id=chatgpt_conversation_id,
        )
        await _publish_failure(type(exc).__name__, str(exc))
        await _record_permanent_failure()
        return

    if not parsed.messages:
        await _publish_failure(
            "no_convertible_messages",
            "No user/assistant text after filtering",
        )
        await _record_permanent_failure()
        return

    # Deferred import to break the circular dependency between the jobs
    # registry (which is imported during chat module bootstrap) and the
    # chat module's public API (which submits jobs).
    from backend.modules.chat import create_imported_session
    from backend.modules.persona import get_persona

    try:
        req = build_imported_session_request(parsed=parsed, persona_id=persona_id)
        session = await create_imported_session(
            user_id=user_id,
            persona_id=req.persona_id,
            title=req.title,
            messages=req.messages,
            imported_from=req.imported_from,
            imported_model_slug=req.imported_model_slug,
            original_created_at=req.original_created_at,
        )
    except Exception as exc:
        _log.exception(
            "chatgpt_import.conversation.create_failed",
            import_id=import_id,
            chatgpt_conversation_id=chatgpt_conversation_id,
        )
        await _publish_failure(type(exc).__name__, str(exc))
        # NOTE: we re-raise so the job system retries the create. Do
        # not bump ``permanent_failures`` here — see module docstring.
        raise

    session_id = str(session["_id"])
    await repo.record_import(
        import_id=import_id,
        chatgpt_conversation_id=chatgpt_conversation_id,
        persona_id=persona_id,
        session_id=session_id,
    )
    await repo.reset_ttl(import_id)

    # Ensure the batch row exists and bump the imported counter. This
    # also captures the persona's ``model_unique_id`` for the snapshot
    # the batch handler will use later. If the persona has no
    # ``model_unique_id`` we still create the row (so the UI sees the
    # state) but the trigger will eventually submit a batch that the
    # batch handler will fail-fast on. In practice every persona has
    # one because chat would already be broken otherwise.
    if persona_target_count is not None:
        persona = await get_persona(persona_id, user_id)
        model_unique_id = (
            (persona or {}).get("model_unique_id") or ""
        )
        await batch_repo.ensure_batch(
            import_id=import_id,
            persona_id=persona_id,
            user_id=user_id,
            model_unique_id=model_unique_id,
            target_count=int(persona_target_count),
        )
        updated = await batch_repo.increment_imported(import_id, persona_id)
        if updated is not None:
            await _maybe_submit_batch(updated)
    else:
        _log.warning(
            "chatgpt_import.memory.batch.trigger.missing_target_count",
            import_id=import_id,
            persona_id=persona_id,
        )

    imported_event = ChatGptImportConversationImportedEvent(
        import_id=import_id,
        chatgpt_conversation_id=chatgpt_conversation_id,
        persona_id=persona_id,
        session_id=session_id,
        title=parsed.title or "Imported conversation",
        correlation_id=correlation_id,
        timestamp=datetime.now(UTC),
    )
    # Publish on the import scope (ChatGPT-Import tab listens here) and on
    # the persona scope (history tabs / sidebar listen on persona:* to
    # refresh their session list when a new imported session lands).
    await event_bus.publish(
        Topics.CHATGPT_IMPORT_CONVERSATION_IMPORTED,
        imported_event,
        scope=scope_import,
        target_user_ids=[user_id],
        correlation_id=correlation_id,
    )
    await event_bus.publish(
        Topics.CHATGPT_IMPORT_CONVERSATION_IMPORTED,
        imported_event,
        scope=scope_persona,
        target_user_ids=[user_id],
        correlation_id=correlation_id,
    )
