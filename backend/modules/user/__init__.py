"""User module — auth, user management, audit log.

Public API: import only from this file.
"""

from backend.modules.user._audit import AuditRepository
from backend.modules.user._auth import (
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    generate_session_id,
)
from backend.modules.user._handlers import router
from backend.modules.user._refresh import RefreshTokenStore
from backend.modules.user._repository import UserRepository
from backend.config import settings
from backend.database import get_db


async def init_indexes(db) -> None:
    """Create MongoDB indexes for user module collections."""
    await UserRepository(db).create_indexes()
    await AuditRepository(db).create_indexes()


async def perform_token_refresh(refresh_token: str, redis) -> dict | None:
    """Rotate a refresh token and return new token data, or None if invalid."""
    store = RefreshTokenStore(redis)
    data = await store.consume(refresh_token)
    if data is None:
        return None

    repo = UserRepository(get_db())
    user = await repo.find_by_id(data["user_id"])
    if not user or not user["is_active"]:
        return None

    session_id = data["session_id"]
    access_token = create_access_token(
        user_id=user["_id"],
        role=user["role"],
        session_id=session_id,
        must_change_password=user["must_change_password"],
    )
    new_refresh_token = generate_refresh_token()
    await store.store(new_refresh_token, user_id=user["_id"], session_id=session_id)

    return {
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "expires_in": settings.jwt_access_token_expire_minutes * 60,
    }


async def get_user_about_me(user_id: str) -> str | None:
    """Return the user's about_me text, or None if not set."""
    repo = UserRepository(get_db())
    return await repo.get_about_me(user_id)


async def get_username(user_id: str) -> str | None:
    """Return the username for a user_id, or None if not found.

    Intended for cross-module display lookups (e.g. admin debug overlay
    enriching user IDs with human-readable names).
    """
    repo = UserRepository(get_db())
    doc = await repo.find_by_id(user_id)
    return doc.get("username") if doc else None


async def get_usernames(user_ids: list[str]) -> dict[str, str]:
    """Return a ``{user_id: username}`` map for the requested user IDs.

    Missing users are simply omitted. Used by the admin debug overlay to
    enrich snapshots with display names in a single round-trip.
    """
    if not user_ids:
        return {}
    repo = UserRepository(get_db())
    out: dict[str, str] = {}
    # Small N (typically < 10 connected users / queued jobs); per-id
    # lookups are fine here and avoid leaking the collection abstraction.
    for uid in set(user_ids):
        doc = await repo.find_by_id(uid)
        if doc and doc.get("username"):
            out[uid] = doc["username"]
    return out


__all__ = [
    "router",
    "init_indexes",
    "perform_token_refresh",
    "decode_access_token",
    "get_user_about_me",
    "get_username",
    "get_usernames",
]
