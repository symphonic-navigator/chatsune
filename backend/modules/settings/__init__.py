"""Settings module -- platform-wide admin-managed configuration.

Public API: import only from this file.
"""

from dataclasses import dataclass

from backend.modules.settings._handlers import router
from backend.modules.settings._repository import SettingsRepository
from backend.database import get_db
from shared.dtos.inference import CompletionMessage, ContentPart


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


@dataclass(frozen=True)
class AdminSystemPrompt:
    """A ready-to-prepend admin system message plus its raw text.

    ``raw_text`` is the stripped admin prompt without the
    ``<systeminstructions>`` wrapper, for token-budget arithmetic.
    """

    message: CompletionMessage
    raw_text: str


async def get_admin_system_message() -> AdminSystemPrompt | None:
    """Return the admin master prompt as a system-role CompletionMessage.

    Wrapped in ``<systeminstructions priority="highest">`` to match the
    chat prompt assembler. The admin prompt is a trusted source and is
    NOT sanitised. Returns ``None`` if the setting is unset, empty, or
    whitespace-only.
    """
    raw = await get_setting("system_prompt")
    if not raw or not raw.strip():
        return None
    stripped = raw.strip()
    wrapped = (
        f'<systeminstructions priority="highest">\n{stripped}\n</systeminstructions>'
    )
    return AdminSystemPrompt(
        message=CompletionMessage(
            role="system",
            content=[ContentPart(type="text", text=wrapped)],
        ),
        raw_text=stripped,
    )


__all__ = [
    "router",
    "init_indexes",
    "SettingsRepository",
    "get_setting",
    "AdminSystemPrompt",
    "get_admin_system_message",
]
