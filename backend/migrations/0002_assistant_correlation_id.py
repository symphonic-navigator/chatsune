"""Backfill ``correlation_id`` on legacy assistant docs and imported messages.

See ``devdocs/specs/2026-05-17-pair-by-correlation-design.md`` for the
design rationale. Short version: until the forward-fix landed at
``backend/modules/chat/_orchestrator.py`` (save_fn passes
``correlation_id=correlation_id``), every assistant doc was written
with ``correlation_id=None``. Imported sessions never carried one
either. The new pair-builder (``select_message_pairs``) keys off
``correlation_id`` and silently skips docs without it — which would
drop the entire pre-migration history out of the LLM context.

This migration walks every session in chronological (``session_seq``)
order and:

- For **legacy** sessions: copies the immediately-preceding user
  message's ``correlation_id`` onto every assistant doc whose
  ``correlation_id`` is None.
- For **imported** sessions (``session.imported_from`` set, where
  every doc was written with ``correlation_id=None`` by design):
  assigns synthetic ids of the shape ``imported-{session_id}-{idx}``
  to each completed user+assistant pair, and
  ``imported-{session_id}-orphan-{idx}`` to unpaired stragglers.

Idempotent: only updates docs whose ``correlation_id`` is still
``None``. Re-running on already-migrated data is a no-op.

Ordering follows the same key the rest of the codebase uses post-INS-047:
``session_seq`` ascending, with ``created_at`` and ``_id`` as tiebreaks
for legacy docs that haven't been backfilled by the 0001 migration yet
(0001 runs first in lexical order, so by the time 0002 runs every doc
already carries a non-zero ``session_seq``).
"""
from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger(__name__)


async def run(db: Any) -> None:
    sessions = db["chat_sessions"]
    messages = db["chat_messages"]

    session_count = 0
    legacy_backfilled = 0
    imported_backfilled = 0
    skipped_sessions = 0

    async for session in sessions.find({}):
        session_count += 1
        session_id = session["_id"]
        is_imported = bool(session.get("imported_from"))

        cursor = messages.find(
            {"session_id": session_id},
        ).sort([("session_seq", 1), ("created_at", 1), ("_id", 1)])
        docs = await cursor.to_list(length=None)

        if not docs:
            skipped_sessions += 1
            continue

        if is_imported:
            written = await _backfill_imported(messages, session_id, docs)
            imported_backfilled += written
        else:
            written = await _backfill_legacy(messages, docs)
            legacy_backfilled += written

    _log.info(
        "migrations.0002_assistant_correlation_id complete sessions_total=%d "
        "legacy_writes=%d imported_writes=%d sessions_skipped_empty=%d",
        session_count, legacy_backfilled, imported_backfilled, skipped_sessions,
    )


async def _backfill_legacy(messages: Any, docs: list[dict]) -> int:
    """For each assistant doc with ``correlation_id is None``, copy the
    correlation_id of the immediately-preceding user doc.

    Returns the number of docs updated.
    """
    writes = 0
    last_user_cid: str | None = None
    for d in docs:
        role = d.get("role")
        if role == "user":
            # Track the most recent user's cid for the next assistant.
            # User docs that already have a cid (the common case post
            # 2025) update the running pointer; legacy user docs
            # without a cid leave it at its previous value, which is
            # the right thing to do since the next assistant probably
            # belongs to whichever user actually had a cid.
            cid = d.get("correlation_id")
            if cid:
                last_user_cid = cid
            continue
        if role != "assistant":
            continue
        if d.get("correlation_id") is not None:
            # Idempotency: already backfilled (or written by new code).
            continue
        if last_user_cid is None:
            # No preceding user with a cid — assign a synthetic
            # orphan id. Rare; happens if a session starts with an
            # assistant doc or every preceding user is also cid-less.
            synthetic = f"orphan-{d['_id']}"
            await messages.update_one(
                {"_id": d["_id"]},
                {"$set": {"correlation_id": synthetic}},
            )
            writes += 1
            continue
        await messages.update_one(
            {"_id": d["_id"]},
            {"$set": {"correlation_id": last_user_cid}},
        )
        writes += 1
    return writes


async def _backfill_imported(
    messages: Any, session_id: str, docs: list[dict],
) -> int:
    """Pair imported user + assistant docs by adjacency and assign
    synthetic ``correlation_id`` values.

    Returns the number of docs updated. Idempotent: docs whose
    ``correlation_id`` is already non-None are skipped, and the
    pairing counter advances only across docs that actually get a
    new synthetic id.
    """
    writes = 0
    pair_idx = 0
    pending_user: dict | None = None

    for d in docs:
        if d.get("correlation_id") is not None:
            # Already backfilled — also reset any pending_user, because
            # an already-paired turn breaks the adjacency chain.
            pending_user = None
            continue
        role = d.get("role")
        if role == "user":
            if pending_user is not None:
                # Two users in a row — first one is orphan.
                synthetic = f"imported-{session_id}-orphan-{pair_idx}"
                pair_idx += 1
                await messages.update_one(
                    {"_id": pending_user["_id"]},
                    {"$set": {"correlation_id": synthetic}},
                )
                writes += 1
            pending_user = d
            continue
        if role == "assistant":
            synthetic = f"imported-{session_id}-{pair_idx}"
            pair_idx += 1
            if pending_user is not None:
                await messages.update_one(
                    {"_id": pending_user["_id"]},
                    {"$set": {"correlation_id": synthetic}},
                )
                writes += 1
                pending_user = None
            await messages.update_one(
                {"_id": d["_id"]},
                {"$set": {"correlation_id": synthetic}},
            )
            writes += 1

    # Trailing user without a following assistant — synthetic orphan id.
    if pending_user is not None:
        synthetic = f"imported-{session_id}-orphan-{pair_idx}"
        await messages.update_one(
            {"_id": pending_user["_id"]},
            {"$set": {"correlation_id": synthetic}},
        )
        writes += 1

    return writes
