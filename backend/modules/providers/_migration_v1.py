"""One-shot migration for Premium Provider Accounts (v1).

Runs once per database on startup, gated by a marker document in the
``_migrations`` collection. Idempotent — re-runs are no-ops.

Transforms the pre-Premium-Provider data model into the new one:

* ``_step_0`` imports existing api_keys (from legacy xai_http/ollama_http
  connections, from voice-integration configs, and from the old websearch
  credentials store) into ``premium_provider_accounts``.
* ``_step_1`` rewrites ``model_unique_id`` references on personas and user
  model configs from the old ``{connection_slug}:{model}`` form to the new
  ``{provider_id}:{model}`` form.
* ``_step_2`` deletes the now-obsolete xai_http and ollama_http@ollama.com
  connection documents (local Ollama connections are preserved).
* ``_step_3`` strips the ``api_key`` field from xai_voice and mistral_voice
  integration configs — credentials now live on the premium account.
* ``_step_4`` drops the ``websearch_user_credentials`` collection entirely.

Failure is intentionally not caught here — the caller (startup lifespan)
must abort if this does not complete, otherwise the app would run against
an inconsistent mix of old and new state.
"""
import hashlib
import logging
from datetime import UTC, datetime
from urllib.parse import urlparse

from cryptography.fernet import Fernet
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.config import settings
from backend.modules.providers._repository import PremiumProviderAccountRepository

_log = logging.getLogger(__name__)
_MARKER_ID = "premium_provider_accounts_v1"


def _hash_key_for_audit(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:8]


async def run_if_needed(db: AsyncIOMotorDatabase, _redis=None) -> None:
    """Run the one-shot migration unless the marker is already present.

    ``_redis`` is accepted for signature-parity with other migration modules
    but unused — this migration touches Mongo only.
    """
    marker = await db["_migrations"].find_one({"_id": _MARKER_ID})
    if marker is not None:
        return

    _log.warning("premium_provider_accounts_v1: running one-shot migration")

    await _step_0_import_keys(db)
    await _step_1_rewrite_model_unique_ids(db)
    await _step_2_delete_migrated_connections(db)
    await _step_3_strip_integration_api_keys(db)
    await _step_4_drop_websearch_credentials(db)

    await db["_migrations"].insert_one({
        "_id": _MARKER_ID,
        "applied_at": datetime.now(UTC),
    })
    _log.warning("premium_provider_accounts_v1: done")


async def _step_0_import_keys(db: AsyncIOMotorDatabase) -> None:
    """Import existing api_keys into premium_provider_accounts, by user.

    Priority per provider (skip if account already exists for the user):
      xai:          xai_http connection  → xai_voice integration
      mistral:      mistral_voice integration
      ollama_cloud: ollama_http connection (hostname = ollama.com) → websearch cred
    """
    fernet = Fernet(settings.encryption_key.encode())
    repo = PremiumProviderAccountRepository(db)

    candidates: dict[tuple[str, str], list[tuple[str, str]]] = {}

    # --- xAI primary: llm_connections xai_http ---
    async for conn in db["llm_connections"].find({"adapter_type": "xai_http"}):
        enc = (conn.get("config_encrypted") or {}).get("api_key")
        if not enc:
            continue
        plaintext = fernet.decrypt(enc.encode()).decode()
        candidates.setdefault((conn["user_id"], "xai"), []).append(
            ("xai_http_conn", plaintext),
        )

    # --- xAI secondary: xai_voice integration ---
    async for cfg in db["user_integration_configs"].find(
        {"integration_id": "xai_voice"},
    ):
        enc = (cfg.get("config_encrypted") or {}).get("api_key")
        if not enc:
            continue
        plaintext = fernet.decrypt(enc.encode()).decode()
        candidates.setdefault((cfg["user_id"], "xai"), []).append(
            ("xai_voice_cfg", plaintext),
        )

    # --- Mistral primary: mistral_voice integration ---
    async for cfg in db["user_integration_configs"].find(
        {"integration_id": "mistral_voice"},
    ):
        enc = (cfg.get("config_encrypted") or {}).get("api_key")
        if not enc:
            continue
        plaintext = fernet.decrypt(enc.encode()).decode()
        candidates.setdefault((cfg["user_id"], "mistral"), []).append(
            ("mistral_voice_cfg", plaintext),
        )

    # --- Ollama Cloud primary: llm_connections ollama_http where base_url
    #     hostname is ollama.com (local Ollama stays where it is) ---
    async for conn in db["llm_connections"].find({"adapter_type": "ollama_http"}):
        base_url = (conn.get("config") or {}).get("base_url") or ""
        if urlparse(base_url).hostname != "ollama.com":
            continue
        enc = (conn.get("config_encrypted") or {}).get("api_key")
        if not enc:
            continue
        plaintext = fernet.decrypt(enc.encode()).decode()
        candidates.setdefault((conn["user_id"], "ollama_cloud"), []).append(
            ("ollama_http_conn", plaintext),
        )

    # --- Ollama Cloud secondary: websearch credentials ---
    async for cred in db["websearch_user_credentials"].find(
        {"provider_id": "ollama_cloud_search"},
    ):
        enc = cred.get("api_key_encrypted")
        if not enc:
            continue
        plaintext = fernet.decrypt(enc.encode()).decode()
        candidates.setdefault((cred["user_id"], "ollama_cloud"), []).append(
            ("websearch_cred", plaintext),
        )

    for (user_id, provider_id), sources in candidates.items():
        existing = await repo.find(user_id, provider_id)
        if existing is not None:
            continue
        primary_label, primary_key = sources[0]
        if len(sources) > 1:
            # Log conflicts where the non-primary sources carry a different
            # key. Keys are never logged in plaintext — only a short sha256
            # prefix so the operator can tell whether two sources carried the
            # same secret without leaking it.
            other_hashes = [
                f"{label}={_hash_key_for_audit(k)}"
                for label, k in sources[1:]
                if k != primary_key
            ]
            if other_hashes:
                _log.warning(
                    "premium_provider_accounts_v1: conflict user=%s provider=%s "
                    "primary=%s:%s others=%s",
                    user_id, provider_id,
                    primary_label, _hash_key_for_audit(primary_key),
                    ",".join(other_hashes),
                )
        await repo.upsert(user_id, provider_id, {"api_key": primary_key})


async def _step_1_rewrite_model_unique_ids(db: AsyncIOMotorDatabase) -> None:
    """Rewrite {old_slug}:{model} → {xai|ollama_cloud}:{model}.

    Touches the ``personas`` and ``llm_user_model_configs`` collections.
    Only runs for connections that the migration is about to delete —
    surviving connections keep their slug-based IDs untouched.
    """
    rewrite_jobs: list[tuple[str, str, str]] = []     # (user_id, old_slug, new_prefix)

    async for conn in db["llm_connections"].find({"adapter_type": "xai_http"}):
        rewrite_jobs.append((conn["user_id"], conn["slug"], "xai"))

    async for conn in db["llm_connections"].find({"adapter_type": "ollama_http"}):
        base_url = (conn.get("config") or {}).get("base_url") or ""
        if urlparse(base_url).hostname != "ollama.com":
            continue
        rewrite_jobs.append((conn["user_id"], conn["slug"], "ollama_cloud"))

    for user_id, old_slug, new_prefix in rewrite_jobs:
        for collection_name in ("personas", "llm_user_model_configs"):
            col = db[collection_name]
            async for doc in col.find({
                "user_id": user_id,
                "model_unique_id": {"$regex": f"^{old_slug}:"},
            }):
                _, _, model_slug = doc["model_unique_id"].partition(":")
                await col.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"model_unique_id": f"{new_prefix}:{model_slug}"}},
                )


async def _step_2_delete_migrated_connections(db: AsyncIOMotorDatabase) -> None:
    """Delete xai_http + ollama_http@ollama.com connections.

    Self-hosted Ollama (any base_url whose hostname is not ollama.com) is
    kept — that one is still a legitimate per-user connection.
    """
    await db["llm_connections"].delete_many({"adapter_type": "xai_http"})
    async for conn in db["llm_connections"].find({"adapter_type": "ollama_http"}):
        base_url = (conn.get("config") or {}).get("base_url") or ""
        if urlparse(base_url).hostname == "ollama.com":
            await db["llm_connections"].delete_one({"_id": conn["_id"]})


async def _step_3_strip_integration_api_keys(db: AsyncIOMotorDatabase) -> None:
    """Remove api_key from xai_voice and mistral_voice integration configs.

    The credential now lives on the premium provider account; the voice
    integration resolves it from there at call time.
    """
    await db["user_integration_configs"].update_many(
        {"integration_id": {"$in": ["xai_voice", "mistral_voice"]}},
        {"$unset": {"config_encrypted.api_key": ""}},
    )


async def _step_4_drop_websearch_credentials(db: AsyncIOMotorDatabase) -> None:
    """Drop the legacy websearch_user_credentials collection.

    ``drop_collection`` is idempotent — dropping a non-existent collection
    is a no-op, so re-runs of this step are safe.
    """
    await db.drop_collection("websearch_user_credentials")
