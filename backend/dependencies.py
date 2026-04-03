from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> dict:
    """Decode JWT and return payload. Raises 401 if invalid or expired."""
    from backend.modules.user._auth import decode_access_token  # deferred to break circular import

    try:
        payload = decode_access_token(credentials.credentials)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return payload


async def require_active_session(
    user: dict = Depends(get_current_user),
) -> dict:
    """Reject requests from users who must change their password (mcp claim)."""
    if user.get("mcp"):
        raise HTTPException(
            status_code=403,
            detail="Password change required before accessing this resource",
        )
    return user


async def require_admin(
    user: dict = Depends(require_active_session),
) -> dict:
    """Require admin or master_admin role."""
    if user["role"] not in ("admin", "master_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def require_master_admin(
    user: dict = Depends(require_active_session),
) -> dict:
    """Require master_admin role."""
    if user["role"] != "master_admin":
        raise HTTPException(
            status_code=403, detail="Master admin access required"
        )
    return user
