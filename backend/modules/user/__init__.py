"""User module — auth, user management, audit log.

Public API: import only from this file.
"""

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.modules.user._audit import AuditRepository
from backend.modules.user._invitation_repository import InvitationRepository
from backend.modules.user._key_repository import UserKeysRepository
from backend.modules.user._models import DEFAULT_RECENT_EMOJIS, InvitationTokenDocument, RECENT_EMOJIS_MAX
from backend.modules.user._key_service import (
    DekUnlockError,
    UserKeyNotFoundError,
    UserKeyService,
)
from backend.modules.user._auth import (
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    generate_session_id,
)
from backend.modules.user._cascade import cascade_delete_user
from backend.modules.user._deletion_report_store import DeletionReportStore
from backend.modules.user._handlers import router
from backend.modules.user._invitation_handlers import router as invitation_router
from backend.modules.user._refresh import RefreshTokenStore
from backend.modules.user._repository import UserRepository
from backend.config import settings
from backend.database import get_db
from backend.ws.event_bus import EventBus
from shared.events.auth import RecentEmojisUpdatedEvent
from shared.topics import Topics


async def init_indexes(db) -> None:
    """Create MongoDB indexes for user module collections."""
    await UserRepository(db).create_indexes()
    await AuditRepository(db).create_indexes()
    await UserKeysRepository(db).ensure_indexes()
    await InvitationRepository(db).create_indexes()


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


async def get_user_mcp_gateways(user_id: str) -> list[dict]:
    """Return the user's remote MCP gateway configurations."""
    repo = UserRepository(get_db())
    return await repo.get_mcp_gateways(user_id)


async def get_admin_mcp_gateways() -> list[dict]:
    """Return admin-configured MCP gateways. Used by the chat orchestrator."""
    db = get_db()
    doc = await db["admin_settings"].find_one({"_id": "mcp"})
    if not doc:
        return []
    return doc.get("gateways", [])


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


class UserService:
    """Public service surface for cross-module user operations.

    This class is intentionally thin — most user-module behaviour is still
    exposed via the module-level helpers above. New cross-module entry
    points that need both the user repository and the event bus should be
    added here so callers do not have to wire those dependencies
    themselves.
    """

    def __init__(self, db: AsyncIOMotorDatabase, event_bus: EventBus) -> None:
        self._repository = UserRepository(db)
        self._event_bus = event_bus

    @staticmethod
    def _merge_lru(current: list[str], incoming: list[str], max_size: int) -> list[str]:
        """Front-load ``incoming`` (in order, deduped against later occurrences),
        then append remaining items from ``current``. Cap at ``max_size``."""
        seen: set[str] = set()
        merged: list[str] = []
        for emoji in [*incoming, *current]:
            if emoji in seen:
                continue
            seen.add(emoji)
            merged.append(emoji)
            if len(merged) >= max_size:
                break
        return merged

    async def touch_recent_emojis(
        self, user_id: str, emojis_in_text: list[str]
    ) -> None:
        """Move freshly-used emojis to the front of the user's LRU.

        Idempotent — duplicate entries in ``emojis_in_text`` are tolerated.
        No-op when the input is empty or when the resulting list is
        unchanged from the user's current list."""
        if not emojis_in_text:
            return
        doc = await self._repository.find_by_id(user_id)
        if doc is None:
            return
        current = doc.get("recent_emojis") or list(DEFAULT_RECENT_EMOJIS)
        new_list = self._merge_lru(current, emojis_in_text, max_size=RECENT_EMOJIS_MAX)
        if new_list == current:
            return
        await self._repository.update_recent_emojis(user_id, new_list)
        await self._event_bus.publish(
            Topics.USER_RECENT_EMOJIS_UPDATED,
            RecentEmojisUpdatedEvent(user_id=user_id, emojis=new_list),
            target_user_ids=[user_id],
        )


__all__ = [
    "router",
    "invitation_router",
    "init_indexes",
    "perform_token_refresh",
    "decode_access_token",
    "get_user_about_me",
    "get_username",
    "get_usernames",
    "get_user_mcp_gateways",
    "get_admin_mcp_gateways",
    "cascade_delete_user",
    "DeletionReportStore",
    "InvitationRepository",
    "InvitationTokenDocument",
    "UserKeyService",
    "UserService",
    "DekUnlockError",
    "UserKeyNotFoundError",
]
