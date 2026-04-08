"""Process-local in-flight LLM inference tracker.

Records every active inference that flows through the LLM module's public
``stream_completion`` API. Used by the admin debug overlay to surface what
the backend is currently asking upstream providers to do — this is
diagnostic state, not authoritative.

Thread-safety: this module assumes a single asyncio event loop, which is
how the backend runs. There is no cross-process aggregation: each backend
process keeps its own registry. The Chatsune backend is a Modular
Monolith (single FastAPI process), so a process-local registry covers
the entire backend.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from shared.dtos.debug import ActiveInferenceDto

_log = logging.getLogger("chatsune.debug.inference_tracker")


class _InferenceRecord:
    __slots__ = (
        "inference_id",
        "user_id",
        "provider_id",
        "model_slug",
        "source",
        "started_at",
    )

    def __init__(
        self,
        inference_id: str,
        user_id: str,
        provider_id: str,
        model_slug: str,
        source: str,
        started_at: datetime,
    ) -> None:
        self.inference_id = inference_id
        self.user_id = user_id
        self.provider_id = provider_id
        self.model_slug = model_slug
        self.source = source
        self.started_at = started_at


# Process-local registry. Keyed by inference_id (UUID4 hex).
_active: dict[str, _InferenceRecord] = {}


def register(
    user_id: str,
    provider_id: str,
    model_slug: str,
    source: str,
) -> str:
    """Register a new in-flight inference. Returns its inference_id."""
    inference_id = uuid4().hex
    record = _InferenceRecord(
        inference_id=inference_id,
        user_id=user_id,
        provider_id=provider_id,
        model_slug=model_slug,
        source=source,
        started_at=datetime.now(timezone.utc),
    )
    _active[inference_id] = record
    _log.debug(
        "inference register id=%s user=%s model=%s:%s source=%s active=%d",
        inference_id, user_id, provider_id, model_slug, source, len(_active),
    )
    return inference_id


def unregister(inference_id: str) -> _InferenceRecord | None:
    """Remove an inference from the registry. Returns the removed record."""
    record = _active.pop(inference_id, None)
    if record is not None:
        _log.debug(
            "inference unregister id=%s active=%d", inference_id, len(_active),
        )
    return record


def snapshot(usernames: dict[str, str] | None = None) -> list[ActiveInferenceDto]:
    """Return a snapshot of every currently in-flight inference.

    ``usernames`` is an optional ``{user_id: username}`` lookup used to
    enrich the DTOs for display. Missing entries fall back to ``None``.
    """
    now = datetime.now(timezone.utc)
    usernames = usernames or {}
    out: list[ActiveInferenceDto] = []
    for record in list(_active.values()):
        out.append(
            ActiveInferenceDto(
                inference_id=record.inference_id,
                user_id=record.user_id,
                username=usernames.get(record.user_id),
                provider_id=record.provider_id,
                model_slug=record.model_slug,
                model_unique_id=f"{record.provider_id}:{record.model_slug}",
                source=record.source,
                started_at=record.started_at,
                duration_seconds=(now - record.started_at).total_seconds(),
            )
        )
    out.sort(key=lambda r: r.started_at)
    return out


def user_ids_with_active_inferences() -> set[str]:
    return {r.user_id for r in _active.values()}


def active_count() -> int:
    return len(_active)
