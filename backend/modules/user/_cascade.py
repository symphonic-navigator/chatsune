"""User cascade-delete helper — right-to-be-forgotten orchestrator.

Removes every piece of data owned by a user and returns a structured
``DeletionReportDto`` summarising what was purged. The report is stored
briefly in Redis (see ``_deletion_report_store.py``) so the logged-out
user can view their receipt on a public confirmation page.

Design notes (see INSIGHTS.md):

1. This orchestrator never touches another module's collections
   directly. Every step goes through the owning module's public API.
2. Per-persona and per-library sub-cascades are already implemented in
   ``persona._cascade`` and ``knowledge._cascade``. We reuse them as-is.
3. Per-persona report rows are **aggregated** into resource-type totals
   (e.g. "chat sessions" = sum across all personas) rather than emitted
   as dozens of sub-reports. The user sees a digestible receipt.
4. Every step is wrapped in ``_safe_call`` — failures become warnings on
   the corresponding row but never abort the cascade. The user must see
   partial progress rather than a hard stop halfway through.

The final step is the user document itself; its deletion determines the
overall ``success`` flag of the report.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from redis.asyncio import Redis

from backend.database import get_db
from backend.modules.user._audit import AuditRepository
from backend.modules.user._refresh import RefreshTokenStore
from backend.modules.user._repository import UserRepository
from shared.dtos.deletion import DeletionReportDto, DeletionStepDto

_log = logging.getLogger(__name__)


async def _safe_call(label: str, coro):
    """Run ``coro`` returning ``(value, warnings)``.

    Any exception is captured as a single warning string and the value
    falls back to ``None`` so callers can still build a report row.
    """
    try:
        return await coro, []
    except Exception as exc:  # noqa: BLE001 — tolerant cascade by design
        _log.warning(
            "cascade_delete_user.step_failed label=%s error=%s", label, exc,
        )
        return None, [f"{label} failed: {exc}"]


async def _scan_and_delete(redis: Redis, match: str) -> int:
    """Best-effort SCAN+DEL for Redis keys matching *match*. Returns total deleted.

    Uses small batches so a large key-space doesn't stall the event loop
    for an unreasonable time. An error returns the count deleted so far
    rather than raising — the caller treats Redis failures as warnings.
    """
    deleted = 0
    batch: list[str] = []
    async for key in redis.scan_iter(match=match, count=200):
        batch.append(key)
        if len(batch) >= 200:
            deleted += await redis.delete(*batch) or 0
            batch = []
    if batch:
        deleted += await redis.delete(*batch) or 0
    return deleted


def _aggregate_persona_reports(
    reports: list[DeletionReportDto],
) -> tuple[list[DeletionStepDto], int]:
    """Collapse per-persona cascade reports into resource-type totals.

    Preserves step label ordering from the first report so the receipt
    looks consistent across invocations. Warnings are concatenated per
    label. Returns ``(merged_steps, personas_deleted)``.
    """
    # Use dict to preserve first-seen insertion order for consistent output.
    totals: dict[str, DeletionStepDto] = {}
    personas_deleted = 0
    for rep in reports:
        if rep.success:
            personas_deleted += 1
        for step in rep.steps:
            existing = totals.get(step.label)
            if existing is None:
                totals[step.label] = DeletionStepDto(
                    label=step.label,
                    deleted_count=step.deleted_count,
                    warnings=list(step.warnings),
                )
            else:
                existing.deleted_count += step.deleted_count
                existing.warnings.extend(step.warnings)
    return list(totals.values()), personas_deleted


def _aggregate_library_reports(
    reports: list[DeletionReportDto],
) -> tuple[list[DeletionStepDto], int]:
    """Collapse per-library cascade reports into resource-type totals."""
    totals: dict[str, DeletionStepDto] = {}
    libraries_deleted = 0
    for rep in reports:
        if rep.success:
            libraries_deleted += 1
        for step in rep.steps:
            existing = totals.get(step.label)
            if existing is None:
                totals[step.label] = DeletionStepDto(
                    label=step.label,
                    deleted_count=step.deleted_count,
                    warnings=list(step.warnings),
                )
            else:
                existing.deleted_count += step.deleted_count
                existing.warnings.extend(step.warnings)
    return list(totals.values()), libraries_deleted


async def cascade_delete_user(
    user_id: str, redis: Redis,
) -> tuple[bool, DeletionReportDto]:
    """Cascade-delete every trace of ``user_id`` across all modules.

    Returns ``(success, report)`` where ``success`` reflects whether the
    ``users`` document itself was removed. Every other step is tolerant —
    partial failures surface as warnings in the report but never abort
    the cascade.
    """
    # Deferred imports — keeps module import order clean and avoids any
    # chance of an import-time cycle (every submodule we touch is also
    # imported elsewhere during app startup).
    from backend.modules.integrations import delete_all_for_user as del_integrations
    from backend.modules.knowledge import (
        cascade_delete_library,
        list_library_ids_for_user,
    )
    from backend.modules.llm import delete_all_for_user as del_llm
    from backend.modules.persona import (
        cascade_delete_persona,
        list_persona_ids_for_user,
    )
    from backend.modules.project import delete_all_for_user as del_projects
    from backend.modules.providers import (
        PremiumProviderAccountRepository,
        PremiumProviderService,
    )

    user_repo = UserRepository(get_db())
    audit_repo = AuditRepository(get_db())

    # Step 0: snapshot the user document for the receipt.
    user_doc = await user_repo.find_by_id(user_id)
    target_name = (
        (user_doc or {}).get("username")
        or (user_doc or {}).get("display_name")
        or "(unknown user)"
    )

    steps: list[DeletionStepDto] = []

    # Step 1: cascade every persona. Aggregate into per-resource totals.
    persona_ids, pids_warnings = await _safe_call(
        "persona enumeration", list_persona_ids_for_user(user_id),
    )
    persona_ids = persona_ids or []
    persona_reports: list[DeletionReportDto] = []
    persona_outer_warnings: list[str] = list(pids_warnings)
    for pid in persona_ids:
        report, warnings = await _safe_call(
            f"persona {pid} cascade", cascade_delete_persona(user_id, pid),
        )
        if report is not None:
            # cascade_delete_persona returns (bool, DeletionReportDto).
            _deleted, dto = report
            persona_reports.append(dto)
        persona_outer_warnings.extend(warnings)

    persona_step_rows, personas_deleted = _aggregate_persona_reports(
        persona_reports,
    )
    # Emit aggregated resource-type rows first, then a summary row.
    steps.extend(persona_step_rows)
    steps.append(DeletionStepDto(
        label="personas",
        deleted_count=personas_deleted,
        warnings=persona_outer_warnings,
    ))

    # Step 2: cascade every knowledge library.
    library_ids, lids_warnings = await _safe_call(
        "library enumeration", list_library_ids_for_user(user_id),
    )
    library_ids = library_ids or []
    library_reports: list[DeletionReportDto] = []
    library_outer_warnings: list[str] = list(lids_warnings)
    for lid in library_ids:
        report, warnings = await _safe_call(
            f"library {lid} cascade", cascade_delete_library(user_id, lid),
        )
        if report is not None:
            _deleted, dto = report
            library_reports.append(dto)
        library_outer_warnings.extend(warnings)

    library_step_rows, libraries_deleted = _aggregate_library_reports(
        library_reports,
    )
    steps.extend(library_step_rows)
    steps.append(DeletionStepDto(
        label="knowledge libraries",
        deleted_count=libraries_deleted,
        warnings=library_outer_warnings,
    ))

    # Step 3: projects.
    project_count, project_warnings = await _safe_call(
        "project deletion", del_projects(user_id),
    )
    steps.append(DeletionStepDto(
        label="projects",
        deleted_count=project_count or 0,
        warnings=project_warnings,
    ))

    # Step 4: LLM data — three counts in one call.
    llm_result, llm_warnings = await _safe_call(
        "LLM data deletion", del_llm(user_id),
    )
    llm_result = llm_result or {}
    steps.append(DeletionStepDto(
        label="LLM connections",
        deleted_count=int(llm_result.get("connections_deleted", 0)),
        warnings=llm_warnings,
    ))
    steps.append(DeletionStepDto(
        label="LLM user model configs",
        deleted_count=int(llm_result.get("user_model_configs_deleted", 0)),
        warnings=[],
    ))
    steps.append(DeletionStepDto(
        label="LLM model cache keys",
        deleted_count=int(llm_result.get("model_cache_keys_cleared", 0)),
        warnings=[],
    ))

    # Step 5: integrations.
    # (web-search credentials are no longer a separate store — they were
    # folded into the premium_provider_accounts collection handled in
    # Step 6b below.)
    integration_count, integration_warnings = await _safe_call(
        "integration config deletion", del_integrations(user_id),
    )
    steps.append(DeletionStepDto(
        label="integration configs",
        deleted_count=integration_count or 0,
        warnings=integration_warnings,
    ))

    # Step 6: premium provider accounts.
    provider_service = PremiumProviderService(
        PremiumProviderAccountRepository(get_db()),
    )
    provider_count, provider_warnings = await _safe_call(
        "premium provider account deletion",
        provider_service.delete_all_for_user(user_id),
    )
    steps.append(DeletionStepDto(
        label="premium provider accounts",
        deleted_count=provider_count or 0,
        warnings=provider_warnings,
    ))

    # Step 7: generated images and image config.
    from backend.modules.images import get_image_service as _get_image_service
    image_count: int = 0
    image_warnings: list[str] = []
    try:
        _image_svc = _get_image_service()
        _deleted_images, _del_warnings = await _safe_call(
            "image data deletion",
            _image_svc.cascade_delete_user(user_id=user_id),
        )
        image_count = _deleted_images or 0
        image_warnings.extend(_del_warnings)
    except RuntimeError:
        # ImageService not initialised — e.g. a standalone migration script
        # that bypasses the normal lifespan. Not a hard failure.
        image_warnings.append("ImageService not initialised — image data not purged")
    steps.append(DeletionStepDto(
        label="generated images",
        deleted_count=image_count,
        warnings=image_warnings,
    ))

    # Step 8: audit-log entries (actor OR resource).
    audit_count, audit_warnings = await _safe_call(
        "audit log deletion", audit_repo.delete_for_user(user_id),
    )
    steps.append(DeletionStepDto(
        label="audit log entries",
        deleted_count=audit_count or 0,
        warnings=audit_warnings,
    ))

    # Step 8b: invitation tokens created by this admin. TTL would eventually
    # clean them up, but we purge immediately on right-to-be-forgotten so
    # valid-looking tokens don't remain usable after the admin is gone.
    from backend.modules.user._invitation_repository import InvitationRepository as _InvRepo
    inv_repo = _InvRepo(get_db())
    inv_count, inv_warnings = await _safe_call(
        "invitation token deletion", inv_repo.delete_all_by_creator(user_id),
    )
    steps.append(DeletionStepDto(
        label="invitation tokens",
        deleted_count=inv_count or 0,
        warnings=inv_warnings,
    ))

    # Step 9: per-user Redis safeguard keys.
    redis_patterns = [
        f"safeguard:queue:{user_id}",
        f"safeguard:budget:{user_id}:*",
        f"safeguard:cb:fail:{user_id}:*",
        f"safeguard:cb:open:{user_id}:*",
        f"safeguard:cb:probe:{user_id}:*",
    ]
    redis_deleted_total = 0
    redis_warnings: list[str] = []
    for pattern in redis_patterns:
        count, warns = await _safe_call(
            f"redis scan {pattern}", _scan_and_delete(redis, pattern),
        )
        redis_deleted_total += count or 0
        redis_warnings.extend(warns)
    steps.append(DeletionStepDto(
        label="redis safeguard keys",
        deleted_count=redis_deleted_total,
        warnings=redis_warnings,
    ))

    # Step 10: revoke every active session (refresh tokens).
    # Pre-count the outstanding token set size so the report shows how
    # many sessions the action actually killed.
    session_count = 0
    session_warnings: list[str] = []
    try:
        members = await redis.smembers(f"user_refresh_tokens:{user_id}")
        session_count = len(members or [])
    except Exception as exc:  # noqa: BLE001 — best-effort pre-count
        session_warnings.append(f"session pre-count failed: {exc}")
    _revoked, revoke_warnings = await _safe_call(
        "refresh token revocation",
        RefreshTokenStore(redis).revoke_all_for_user(user_id),
    )
    session_warnings.extend(revoke_warnings)
    steps.append(DeletionStepDto(
        label="active sessions revoked",
        deleted_count=session_count,
        warnings=session_warnings,
    ))

    # Step 11: the user document itself. This determines overall success.
    user_deleted = False
    user_warnings: list[str] = []
    try:
        user_deleted = await user_repo.delete_user_document(user_id)
    except Exception as exc:  # noqa: BLE001
        user_warnings.append(f"user document deletion failed: {exc}")
        _log.warning(
            "cascade_delete_user.user_doc_failed user_id=%s error=%s",
            user_id, exc,
        )
    steps.append(DeletionStepDto(
        label="user document",
        deleted_count=1 if user_deleted else 0,
        warnings=user_warnings,
    ))

    report = DeletionReportDto(
        target_type="user",
        target_id=user_id,
        target_name=target_name,
        success=user_deleted,
        steps=steps,
        timestamp=datetime.now(UTC),
    )

    _log.info(
        "cascade_delete_user.done user_id=%s personas=%d libraries=%d "
        "warnings=%d user_deleted=%s",
        user_id,
        personas_deleted,
        libraries_deleted,
        report.total_warnings,
        user_deleted,
    )
    return user_deleted, report
