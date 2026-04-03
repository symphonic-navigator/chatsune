"""Settings module -- platform-wide admin-managed configuration.

Public API: import only from this file.
"""

from backend.modules.settings._handlers import router
from backend.modules.settings._repository import SettingsRepository
from backend.database import get_db


async def init_indexes(db) -> None:
    """Create MongoDB indexes for the settings module collections."""
    await SettingsRepository(db).create_indexes()


async def get_setting(key: str) -> str | None:
    """Return the value for a setting key, or None if not set."""
    repo = SettingsRepository(get_db())
    doc = await repo.find(key)
    if doc is None:
        return None
    return doc["value"]


__all__ = ["router", "init_indexes", "SettingsRepository", "get_setting"]
