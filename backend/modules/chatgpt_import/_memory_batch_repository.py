r"""MongoDB access for the ``chatgpt_import_memory_batches`` collection.

State is scoped to ``(import_id, persona_id)`` so a single import that
imported into multiple personas yields independent batch lifecycles.
The document ``_id`` is the composite key ``f"{import_id}:{persona_id}"``
so atomic ``find_one_and_update`` operations on the state field act on
exactly one row.

State machine::

    pending  -> running -> done
                       \-> paused -> running -> ... -> done
                                  \-> discarded

The trigger handler (per-conversation job) flips ``pending -> running``
atomically when ``conversations_imported + permanent_failures ==
target_count``. The batch handler flips ``running -> paused / done``.
The REST resume / discard endpoints flip ``paused -> running / discarded``.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument


def _batch_id(import_id: str, persona_id: str) -> str:
    return f"{import_id}:{persona_id}"


class ChatGptImportMemoryBatchRepository:
    """Repository for the ``chatgpt_import_memory_batches`` collection.

    All public methods are atomic against MongoDB's single-document
    guarantee: ``find_one_and_update`` either applies all updates and
    returns the new doc, or matches nothing and returns ``None``.
    """

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._batches = db["chatgpt_import_memory_batches"]

    async def ensure_indexes(self) -> None:
        """Idempotent index creation. Safe to call on every startup."""
        # Used by ``list_pending_for_user`` to surface running/paused
        # batches on reconnect.
        await self._batches.create_index([("user_id", 1), ("state", 1)])

    # --- creation / lookup ---------------------------------------------

    async def ensure_batch(
        self,
        *,
        import_id: str,
        persona_id: str,
        user_id: str,
        model_unique_id: str,
        target_count: int,
    ) -> dict:
        """Upsert a batch row in ``pending`` state, idempotent on re-call.

        ``find_one_and_update`` with ``$setOnInsert`` means concurrent
        first-time callers see the same created document; subsequent
        calls return the existing row unchanged. The model snapshot
        captures the persona's model at submit time so a later persona
        re-config does not break a paused batch.
        """
        now = datetime.now(UTC)
        doc = await self._batches.find_one_and_update(
            {"_id": _batch_id(import_id, persona_id)},
            {
                "$setOnInsert": {
                    "_id": _batch_id(import_id, persona_id),
                    "import_id": import_id,
                    "persona_id": persona_id,
                    "user_id": user_id,
                    "model_unique_id": model_unique_id,
                    "state": "pending",
                    "target_count": target_count,
                    "conversations_imported": 0,
                    "permanent_failures": 0,
                    "session_ids": [],
                    "paused_at": None,
                    "total_entries_created": 0,
                    "created_at": now,
                    "updated_at": now,
                }
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        # Mongo guarantees the doc exists after upsert; the cast is just
        # to keep type-checkers happy.
        assert doc is not None
        return doc

    async def get(self, import_id: str, persona_id: str) -> dict | None:
        return await self._batches.find_one(
            {"_id": _batch_id(import_id, persona_id)}
        )

    async def list_pending_for_user(self, user_id: str) -> list[dict]:
        """Return the user's batches in ``running`` or ``paused`` state.

        Used by the GET-active endpoint so the frontend can rebuild
        paused-state UI on reconnect without WS replay.
        """
        cursor = self._batches.find(
            {"user_id": user_id, "state": {"$in": ["running", "paused"]}}
        )
        return await cursor.to_list(length=200)

    # --- counter increments --------------------------------------------

    async def increment_imported(
        self, import_id: str, persona_id: str,
    ) -> dict | None:
        """Add 1 to ``conversations_imported`` and return the updated doc."""
        return await self._batches.find_one_and_update(
            {"_id": _batch_id(import_id, persona_id)},
            {
                "$inc": {"conversations_imported": 1},
                "$set": {"updated_at": datetime.now(UTC)},
            },
            return_document=ReturnDocument.AFTER,
        )

    async def increment_failures(
        self, import_id: str, persona_id: str,
    ) -> dict | None:
        """Add 1 to ``permanent_failures`` and return the updated doc."""
        return await self._batches.find_one_and_update(
            {"_id": _batch_id(import_id, persona_id)},
            {
                "$inc": {"permanent_failures": 1},
                "$set": {"updated_at": datetime.now(UTC)},
            },
            return_document=ReturnDocument.AFTER,
        )

    async def add_entries_created(
        self, import_id: str, persona_id: str, count: int,
    ) -> None:
        """Add to ``total_entries_created``. Caller guarantees idempotency."""
        if count == 0:
            return
        await self._batches.update_one(
            {"_id": _batch_id(import_id, persona_id)},
            {
                "$inc": {"total_entries_created": count},
                "$set": {"updated_at": datetime.now(UTC)},
            },
        )

    # --- state transitions ---------------------------------------------

    async def claim_running(
        self,
        *,
        import_id: str,
        persona_id: str,
        session_ids: list[str],
    ) -> dict | None:
        """Atomically flip ``pending → running``. Returns the doc, or ``None``.

        Used by the trigger logic so only one concurrent finisher actually
        submits the batch job. Subsequent racing callers see the row in
        ``running`` state and the filter fails to match.
        """
        now = datetime.now(UTC)
        return await self._batches.find_one_and_update(
            {
                "_id": _batch_id(import_id, persona_id),
                "state": "pending",
            },
            {
                "$set": {
                    "state": "running",
                    "session_ids": session_ids,
                    "started_at": now,
                    "updated_at": now,
                },
            },
            return_document=ReturnDocument.AFTER,
        )

    async def claim_resume(
        self,
        *,
        import_id: str,
        persona_id: str,
    ) -> dict | None:
        """Atomically flip ``paused → running`` on resume. Returns doc or None.

        The Resume endpoint re-submits the batch job only after this
        claim succeeds, guaranteeing a single in-flight batch even if
        the user mashes the button.
        """
        now = datetime.now(UTC)
        return await self._batches.find_one_and_update(
            {
                "_id": _batch_id(import_id, persona_id),
                "state": "paused",
            },
            {
                "$set": {
                    "state": "running",
                    "paused_at": None,
                    "updated_at": now,
                },
            },
            return_document=ReturnDocument.AFTER,
        )

    async def mark_paused(
        self,
        *,
        import_id: str,
        persona_id: str,
        session_index: int,
        session_id: str,
        reason: str,
        user_message: str,
        detail: str | None = None,
    ) -> dict | None:
        """Flip ``running → paused`` with the paused-at sub-document set."""
        now = datetime.now(UTC)
        return await self._batches.find_one_and_update(
            {"_id": _batch_id(import_id, persona_id)},
            {
                "$set": {
                    "state": "paused",
                    "paused_at": {
                        "session_index": session_index,
                        "session_id": session_id,
                        "reason": reason,
                        "user_message": user_message,
                        "detail": detail,
                        "at": now,
                    },
                    "updated_at": now,
                },
            },
            return_document=ReturnDocument.AFTER,
        )

    async def mark_done(self, import_id: str, persona_id: str) -> dict | None:
        """Flip to ``done`` and clear ``paused_at``."""
        now = datetime.now(UTC)
        return await self._batches.find_one_and_update(
            {"_id": _batch_id(import_id, persona_id)},
            {
                "$set": {
                    "state": "done",
                    "paused_at": None,
                    "updated_at": now,
                },
            },
            return_document=ReturnDocument.AFTER,
        )

    async def mark_discarded(
        self,
        *,
        import_id: str,
        persona_id: str,
        only_if_paused: bool = False,
    ) -> dict | None:
        """Flip to ``discarded`` and clear ``paused_at``.

        ``only_if_paused=True`` is used by the REST handler so a race
        with a fresh resume (paused→running) fails the discard cleanly.
        """
        now = datetime.now(UTC)
        match: dict[str, Any] = {"_id": _batch_id(import_id, persona_id)}
        if only_if_paused:
            match["state"] = "paused"
        return await self._batches.find_one_and_update(
            match,
            {
                "$set": {
                    "state": "discarded",
                    "paused_at": None,
                    "updated_at": now,
                },
            },
            return_document=ReturnDocument.AFTER,
        )
