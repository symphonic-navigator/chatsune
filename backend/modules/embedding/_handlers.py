"""Embedding module HTTP endpoints."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/embedding")


@router.get("/status")
async def embedding_status():
    from backend.modules.embedding import get_status
    return get_status()
