"""Tests for BackendMarkerMiddleware: every /api/* response carries
X-Chatsune-Backend so the frontend can distinguish authentic backend
responses from proxy fall-throughs."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend._middleware import BackendMarkerMiddleware


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(BackendMarkerMiddleware)

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/error")
    async def error():
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="bad")

    @app.get("/non-api")
    async def non_api():
        return {"ok": True}

    return app


def test_marker_header_present_on_api_success():
    client = TestClient(_app())
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.headers.get("X-Chatsune-Backend") == "1"


def test_marker_header_present_on_api_error():
    client = TestClient(_app())
    response = client.get("/api/error")
    assert response.status_code == 400
    assert response.headers.get("X-Chatsune-Backend") == "1"


def test_marker_header_absent_on_non_api_path():
    client = TestClient(_app())
    response = client.get("/non-api")
    assert response.status_code == 200
    assert "X-Chatsune-Backend" not in response.headers
