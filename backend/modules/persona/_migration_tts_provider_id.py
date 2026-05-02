"""One-shot migration: backfill persona.voice_config.tts_provider_id.

Runs once per database on startup, gated by a marker document in the
``_migrations`` collection. Idempotent — re-runs are no-ops.

Background: between alpha and the early beta, the persona-voice editor on
the frontend would only persist ``voice_config.tts_provider_id`` when the
user actively changed the TTS-provider selector. Personas that were
created and only had a voice picked therefore landed in the database with
``integration_configs[<voice_int>].voice_id`` set but no
``voice_config.tts_provider_id``. The cockpit Live-button gate fell back
to "first enabled TTS integration" and looked fine; the top-bar voice-chat
pill did not, and rendered as strikethrough. This migration repairs those
documents so the gates agree.

The frontend persistence path was fixed at the same time (see
``PersonaVoiceConfig.persistVoiceConfig``); this script handles the
existing document corpus.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.modules.integrations._registry import get_all
from shared.dtos.integrations import IntegrationCapability

_log = logging.getLogger(__name__)
_MARKER_ID = "persona_tts_provider_id_backfill_v1"


def _tts_integration_ids() -> tuple[str, ...]:
    """Snapshot of the registry-known TTS-provider integration ids.

    Order matters for the migration's tie-break behaviour: when a persona
    has voice ids configured on multiple TTS integrations we pick the first
    one in registry order so the result is deterministic. Iteration order
    of the registry is the registration order in
    ``_register_builtins``, which is stable across runs.
    """
    return tuple(
        defn.id
        for defn in get_all().values()
        if IntegrationCapability.TTS_PROVIDER in (defn.capabilities or [])
    )


def pick_default_provider_id(
    persona: dict[str, Any], tts_integration_ids: Iterable[str],
) -> str | None:
    """Return the integration id whose ``voice_id`` we should adopt as
    the persona's ``tts_provider_id``, or None if no candidate exists.

    Pure function — easy to unit-test without a database. The order of
    ``tts_integration_ids`` is the tie-break.
    """
    integration_configs = persona.get("integration_configs") or {}
    for integration_id in tts_integration_ids:
        cfg = integration_configs.get(integration_id) or {}
        if cfg.get("voice_id"):
            return integration_id
    return None


async def run_if_needed(db: AsyncIOMotorDatabase, _redis=None) -> None:
    """Run the one-shot backfill unless the marker is already present.

    ``_redis`` is accepted for signature-parity with other migration
    modules but unused — this migration touches Mongo only.
    """
    marker = await db["_migrations"].find_one({"_id": _MARKER_ID})
    if marker is not None:
        return

    _log.warning("persona_tts_provider_id_backfill_v1: running")

    tts_ids = _tts_integration_ids()
    personas = db["personas"]
    updated = 0
    skipped = 0

    # Match documents where tts_provider_id is missing or null. The same
    # filter on a re-run finds nothing because the previous run set the
    # field — that is the idempotency guarantee.
    cursor = personas.find({
        "$or": [
            {"voice_config": {"$exists": False}},
            {"voice_config.tts_provider_id": {"$in": [None, ""]}},
            {"voice_config.tts_provider_id": {"$exists": False}},
        ],
    })
    async for doc in cursor:
        chosen = pick_default_provider_id(doc, tts_ids)
        if chosen is None:
            skipped += 1
            continue
        await personas.update_one(
            {"_id": doc["_id"]},
            {"$set": {"voice_config.tts_provider_id": chosen}},
        )
        updated += 1

    await db["_migrations"].insert_one({
        "_id": _MARKER_ID,
        "applied_at": datetime.now(UTC),
        "updated": updated,
        "skipped": skipped,
    })
    _log.warning(
        "persona_tts_provider_id_backfill_v1: done updated=%d skipped=%d",
        updated, skipped,
    )
