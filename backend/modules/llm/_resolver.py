"""Resolve a connection (by _id or slug) + current user into a ResolvedConnection.

Two public entry points:

* :func:`resolve_connection_for_user` — FastAPI dependency, used by adapter
  sub-routers (``/api/llm/connections/{connection_id}/...``) that accept the
  Connection's ``_id`` or ``slug`` in the path.

* :func:`resolve_for_model` — non-HTTP helper that takes a ``model_unique_id``
  of the form ``<slug>:<model_slug>`` and returns a :class:`ResolvedConnection`
  ready to hand to an adapter. When the left segment is a reserved Premium
  Provider id (``xai``, ``mistral``, ``ollama_cloud``), the resolver fetches
  the user's encrypted credential from :class:`PremiumProviderService` and
  synthesises a ResolvedConnection carrying the registry-fixed ``base_url``
  + decrypted ``api_key``. Otherwise it falls back to the per-user Connection
  repository lookup (the existing behaviour).
"""

from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Path

from backend.database import get_db
from backend.dependencies import require_active_session
from backend.modules.llm._adapters._types import ResolvedConnection
from backend.modules.llm._connections import ConnectionRepository

# Mapping from reserved Premium-Provider id → adapter_type string. Only
# providers with an LLM capability appear here. ``mistral`` is reserved by
# the slug system but has no LLM adapter yet, so it intentionally has no
# entry and will fall through to the "no LLM capability" branch.
_PREMIUM_ADAPTER_TYPE: dict[str, str] = {
    "xai": "xai_http",
    "ollama_cloud": "ollama_http",
}


def _to_resolved(doc: dict) -> ResolvedConnection:
    merged = dict(doc.get("config", {}))
    for field in doc.get("config_encrypted", {}):
        merged[field] = ConnectionRepository.get_decrypted_secret(doc, field)
    return ResolvedConnection(
        id=doc["_id"],
        user_id=doc["user_id"],
        adapter_type=doc["adapter_type"],
        display_name=doc["display_name"],
        slug=doc["slug"],
        config=merged,
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


async def resolve_connection_for_user(
    connection_id: str = Path(...),
    user: dict = Depends(require_active_session),
) -> ResolvedConnection:
    # The path parameter may be either the Connection ``_id`` (UUID used by
    # internal callers such as the Model Browser / favourites flow) or the
    # ``slug`` (used when the Frontend splits a ``model_unique_id`` of the
    # form ``<connection_slug>:<model_slug>`` — see INS-019). Try id first,
    # then fall back to slug; both lookups are strictly scoped to the
    # calling user.
    repo = ConnectionRepository(get_db())
    doc = await repo.find(user["sub"], connection_id)
    if doc is None:
        doc = await repo.find_by_slug(user["sub"], connection_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    return _to_resolved(doc)


async def resolve_owned_connection_by_slug(
    user_id: str, connection_slug: str,
) -> ResolvedConnection | None:
    """Non-HTTP variant used from internal call sites (stream_completion).

    Looks up the Connection by ``(user_id, slug)`` — the left segment of a
    ``<connection_slug>:<model_slug>`` unique_id.
    """
    repo = ConnectionRepository(get_db())
    doc = await repo.find_by_slug(user_id, connection_slug)
    if doc is None:
        return None
    return _to_resolved(doc)


async def _resolve_premium(
    user_id: str, model_unique_id: str,
) -> ResolvedConnection | None:
    """Return a ResolvedConnection for a Premium-Provider model, or ``None``
    when ``model_unique_id`` does not begin with a reserved slug.

    Raises :class:`LlmConnectionNotFoundError` if the prefix IS a reserved
    slug but the user has no matching Premium account, or the account has
    no ``api_key`` set. Unknown-but-non-premium prefixes return ``None`` so
    the caller can fall back to the standard Connection lookup.
    """
    # Local imports to avoid import-time cycles (providers → ws → llm).
    from backend.modules.llm import LlmConnectionNotFoundError
    from backend.modules.providers import PremiumProviderService
    from backend.modules.providers._registry import get as get_premium_definition
    from backend.modules.providers._repository import (
        PremiumProviderAccountRepository,
    )

    prefix, sep, _ = model_unique_id.partition(":")
    if not sep or not prefix:
        return None
    defn = get_premium_definition(prefix)
    if defn is None:
        return None
    adapter_type = _PREMIUM_ADAPTER_TYPE.get(prefix)
    if adapter_type is None:
        # Premium provider exists but has no LLM adapter (e.g. mistral).
        # Nothing we can resolve for LLM inference — let the caller deal.
        return None

    svc = PremiumProviderService(PremiumProviderAccountRepository(get_db()))
    api_key = await svc.get_decrypted_secret(user_id, prefix, "api_key")
    if api_key is None:
        raise LlmConnectionNotFoundError(model_unique_id)

    now = datetime.now(UTC)
    return ResolvedConnection(
        id=f"premium:{prefix}",
        user_id=user_id,
        adapter_type=adapter_type,
        display_name=defn.display_name,
        slug=prefix,
        config={"url": defn.base_url, "api_key": api_key},
        created_at=now,
        updated_at=now,
    )


async def resolve_premium_for_listing(
    user_id: str, provider_id: str,
) -> ResolvedConnection | None:
    """Synthesise a :class:`ResolvedConnection` for model-*listing* calls
    against a Premium Provider.

    Differences versus :func:`_resolve_premium`:
      * Takes a bare ``provider_id`` (no ``<slug>:<model>`` split needed).
      * Returns ``None`` on any "not eligible" outcome (unknown provider,
        no LLM adapter mapping, or no user account with an ``api_key``).
        The inference path needs to raise because a missing key mid-chat
        is a hard error; listing is a UI read and "no account configured"
        is a perfectly normal 404 the handler can translate.
    """
    # Local imports — see :func:`_resolve_premium`.
    from backend.modules.providers import PremiumProviderService
    from backend.modules.providers._registry import get as get_premium_definition
    from backend.modules.providers._repository import (
        PremiumProviderAccountRepository,
    )

    defn = get_premium_definition(provider_id)
    if defn is None:
        return None
    adapter_type = _PREMIUM_ADAPTER_TYPE.get(provider_id)
    if adapter_type is None:
        return None

    svc = PremiumProviderService(PremiumProviderAccountRepository(get_db()))
    api_key = await svc.get_decrypted_secret(user_id, provider_id, "api_key")
    if api_key is None:
        return None

    now = datetime.now(UTC)
    return ResolvedConnection(
        id=f"premium:{provider_id}",
        user_id=user_id,
        adapter_type=adapter_type,
        display_name=defn.display_name,
        slug=provider_id,
        config={"url": defn.base_url, "api_key": api_key},
        created_at=now,
        updated_at=now,
    )


async def resolve_for_model(
    user_id: str, model_unique_id: str,
) -> ResolvedConnection:
    """Resolve ``<slug>:<model_slug>`` into a :class:`ResolvedConnection`.

    Dispatch order:
      1. If ``slug`` is a reserved Premium-Provider id with an LLM adapter,
         synthesise from the registry + the user's Premium account.
      2. Otherwise look up the user's Connection by slug.

    Raises:
        LlmConnectionNotFoundError: neither a premium account nor a
            per-user connection matched the slug.
    """
    from backend.modules.llm import LlmConnectionNotFoundError

    premium = await _resolve_premium(user_id, model_unique_id)
    if premium is not None:
        return premium

    slug, sep, _ = model_unique_id.partition(":")
    if not sep or not slug:
        raise LlmConnectionNotFoundError(model_unique_id)
    resolved = await resolve_owned_connection_by_slug(user_id, slug)
    if resolved is None:
        raise LlmConnectionNotFoundError(slug)
    return resolved
