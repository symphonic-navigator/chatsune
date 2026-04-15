import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


class FakeOllamaTransport(httpx.MockTransport):
    def __init__(self, ps_json, tags_json):
        def handler(req):
            if req.url.path == "/api/ps":
                return httpx.Response(200, json=ps_json)
            if req.url.path == "/api/tags":
                return httpx.Response(200, json=tags_json)
            return httpx.Response(404)
        super().__init__(handler)


@pytest.fixture
def app_with_admin(monkeypatch):
    monkeypatch.setenv("OLLAMA_LOCAL_BASE_URL", "http://fake:11434")
    from backend.modules.llm._admin_handlers import build_admin_router
    from backend import dependencies

    app = FastAPI()
    app.dependency_overrides[dependencies.require_admin] = lambda: {
        "id": "u1", "role": "admin",
    }
    transport = FakeOllamaTransport(
        ps_json={"models": [{"name": "a"}]},
        tags_json={"models": [{"name": "b"}]},
    )
    app.include_router(
        build_admin_router(http_transport=transport),
        prefix="/api/llm/admin",
    )
    return app


@pytest.mark.asyncio
async def test_ps_returns_ollama_ps_payload(app_with_admin):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_admin), base_url="http://test",
    ) as client:
        resp = await client.get("/api/llm/admin/ollama-local/ps")
    assert resp.status_code == 200
    assert resp.json() == {"models": [{"name": "a"}]}


@pytest.mark.asyncio
async def test_tags_returns_ollama_tags_payload(app_with_admin):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_admin), base_url="http://test",
    ) as client:
        resp = await client.get("/api/llm/admin/ollama-local/tags")
    assert resp.status_code == 200
    assert resp.json() == {"models": [{"name": "b"}]}


@pytest.mark.asyncio
async def test_ps_returns_503_when_env_missing(monkeypatch):
    # Env var intentionally unset
    monkeypatch.delenv("OLLAMA_LOCAL_BASE_URL", raising=False)
    from backend.modules.llm._admin_handlers import build_admin_router
    from backend import dependencies

    app = FastAPI()
    app.dependency_overrides[dependencies.require_admin] = lambda: {
        "id": "u1", "role": "admin",
    }
    app.include_router(build_admin_router(), prefix="/api/llm/admin")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.get("/api/llm/admin/ollama-local/ps")
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_ps_returns_503_when_ollama_unreachable(monkeypatch):
    monkeypatch.setenv("OLLAMA_LOCAL_BASE_URL", "http://fake:11434")
    from backend.modules.llm._admin_handlers import build_admin_router
    from backend import dependencies

    def handler(req):
        raise httpx.ConnectError("refused")

    transport = httpx.MockTransport(handler)
    app = FastAPI()
    app.dependency_overrides[dependencies.require_admin] = lambda: {
        "id": "u1", "role": "admin",
    }
    app.include_router(
        build_admin_router(http_transport=transport),
        prefix="/api/llm/admin",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.get("/api/llm/admin/ollama-local/ps")
    assert resp.status_code == 503
