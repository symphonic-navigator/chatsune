"""Image generation module — public API."""

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.modules.images._http import router
from backend.modules.images._repository import (
    GeneratedImagesRepository,
    UserImageConfigRepository,
)
from backend.modules.images._service import ImageGenerationOutcome, ImageService


_SERVICE_SINGLETON: ImageService | None = None


def set_image_service(svc: ImageService) -> None:
    global _SERVICE_SINGLETON
    _SERVICE_SINGLETON = svc


def get_image_service() -> ImageService:
    if _SERVICE_SINGLETON is None:
        raise RuntimeError("ImageService not initialised")
    return _SERVICE_SINGLETON


async def init_indexes(db: AsyncIOMotorDatabase) -> None:
    await GeneratedImagesRepository(db).create_indexes()
    await UserImageConfigRepository(db).create_indexes()


async def count_for_sessions(session_ids: list[str], user_id: str) -> int:
    """Mindspace: count generated images referenced by the given chat sessions.

    Used by the project usage-counts endpoint. Generated images are
    not directly linked to sessions; the chat module's
    ``list_image_ids_for_sessions`` walks message ``image_refs`` and
    ``events`` timelines to recover the set, then we count owned
    images in that set. Empty input → 0 with no DB round-trip.
    """
    if not session_ids:
        return 0
    from backend.database import get_db
    from backend.modules import chat as chat_service

    image_ids = await chat_service.list_image_ids_for_sessions(
        session_ids, user_id,
    )
    if not image_ids:
        return 0
    repo = GeneratedImagesRepository(get_db())
    return await repo.count_by_ids(user_id=user_id, image_ids=image_ids)


async def list_for_sessions(
    session_ids: list[str], user_id: str, *, limit: int = 200,
) -> list:
    """Mindspace: list generated images referenced by the given chat sessions.

    Used by the project-filtered ``GET /api/images?project_id=…``
    endpoint. Returns ``GeneratedImageDocument`` instances sorted
    newest-first; the caller maps them to whatever DTO the surface
    expects.
    """
    if not session_ids:
        return []
    from backend.database import get_db
    from backend.modules import chat as chat_service

    image_ids = await chat_service.list_image_ids_for_sessions(
        session_ids, user_id,
    )
    if not image_ids:
        return []
    repo = GeneratedImagesRepository(get_db())
    return await repo.list_for_ids(
        user_id=user_id, image_ids=image_ids, limit=limit,
    )


__all__ = [
    "ImageService",
    "ImageGenerationOutcome",
    "router",
    "init_indexes",
    "set_image_service",
    "get_image_service",
    "count_for_sessions",
    "list_for_sessions",
]
