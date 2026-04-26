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


__all__ = [
    "ImageService",
    "ImageGenerationOutcome",
    "router",
    "init_indexes",
    "set_image_service",
    "get_image_service",
]
