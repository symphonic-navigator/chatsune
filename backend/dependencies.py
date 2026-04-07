from __future__ import annotations

import logging

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_log = logging.getLogger(__name__)
_bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> dict:
    """Decode JWT and return payload. Raises 401 if invalid or expired."""
    from backend.modules.user._auth import decode_access_token  # deferred to break circular import

    try:
        payload = decode_access_token(credentials.credentials)
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    except Exception:
        _log.exception("Unexpected error decoding access token")
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


async def get_optional_user(request: Request) -> dict | None:
    """Decode JWT from a Bearer header if present, else return None.

    Used by endpoints that support an alternative auth path (e.g. signed URLs)
    and only need a user identity when a Bearer token is supplied.
    """
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return None
    from backend.modules.user._auth import decode_access_token  # deferred to break circular import

    try:
        return decode_access_token(auth.removeprefix("Bearer "))
    except Exception:
        return None


async def require_master_admin(
    user: dict = Depends(require_active_session),
) -> dict:
    """Require master_admin role."""
    if user["role"] != "master_admin":
        raise HTTPException(
            status_code=403, detail="Master admin access required"
        )
    return user
