"""HTTP middleware shared by the FastAPI app."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Marker header tagged on every backend-originated response under /api.
# The frontend uses this to distinguish authentic backend responses from
# proxy fall-throughs (e.g. Traefik routing /api/* to the frontend
# catch-all when the backend container is stopped).
BACKEND_MARKER_HEADER = "X-Chatsune-Backend"
BACKEND_MARKER_VALUE = "1"


class BackendMarkerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        if request.url.path.startswith("/api"):
            response.headers[BACKEND_MARKER_HEADER] = BACKEND_MARKER_VALUE
        return response
