"""One-shot migration for Premium Provider Accounts (v1).

Gated by a marker document in ``_migrations``. Idempotent — re-runs are no-ops.
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
    pass     # filled in Task 17


async def _step_2_delete_migrated_connections(db: AsyncIOMotorDatabase) -> None:
    pass     # filled in Task 17


async def _step_3_strip_integration_api_keys(db: AsyncIOMotorDatabase) -> None:
    pass     # filled in Task 17


async def _step_4_drop_websearch_credentials(db: AsyncIOMotorDatabase) -> None:
    await db.drop_collection("websearch_user_credentials")
