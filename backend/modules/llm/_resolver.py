"""Resolve a connection_id + current user into a ResolvedConnection."""

from fastapi import Depends, HTTPException, Path

from backend.database import get_db
from backend.dependencies import require_active_session
from backend.modules.llm._adapters._types import ResolvedConnection
from backend.modules.llm._connections import ConnectionRepository


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
    repo = ConnectionRepository(get_db())
    doc = await repo.find(user["sub"], connection_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    return _to_resolved(doc)


async def resolve_owned_connection(
    user_id: str, connection_id: str,
) -> ResolvedConnection | None:
    """Non-HTTP variant used from internal call sites (stream_completion)."""
    repo = ConnectionRepository(get_db())
    doc = await repo.find(user_id, connection_id)
    if doc is None:
        return None
    return _to_resolved(doc)
