import asyncio

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


class _FakeBus:
    def __init__(self):
        self.events = []

    async def publish(self, topic, event, **kwargs):
        payload = event.model_dump() if hasattr(event, "model_dump") else dict(event)
        self.events.append((topic, payload, kwargs))


@pytest.mark.asyncio
async def test_admin_pull_returns_pull_id(monkeypatch):
    monkeypatch.setenv("OLLAMA_LOCAL_BASE_URL", "http://fake:11434")
    from backend.modules.llm._admin_handlers import build_admin_router
    from backend import dependencies

    def handler(req):
        # Immediate "success" so the pull task finishes cleanly.
        return httpx.Response(200, content=b'{"status":"success"}\n')
    transport = httpx.MockTransport(handler)

    fake_bus = _FakeBus()
    app = FastAPI()
    app.dependency_overrides[dependencies.require_admin] = lambda: {"id": "u1"}
    app.include_router(
        build_admin_router(
            http_transport=transport,
            event_bus_factory=lambda: fake_bus,
        ),
        prefix="/api/llm/admin",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.post(
            "/api/llm/admin/ollama-local/pull",
            json={"slug": "llama3.2"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "pull_id" in body and body["pull_id"]

    # Let the background task run
    await asyncio.sleep(0.05)

    topics = [ev[0] for ev in fake_bus.events]
    from shared.topics import Topics
    assert Topics.LLM_MODEL_PULL_STARTED in topics
    assert Topics.LLM_MODEL_PULL_COMPLETED in topics


@pytest.mark.asyncio
async def test_admin_pull_rejects_empty_slug(monkeypatch):
    monkeypatch.setenv("OLLAMA_LOCAL_BASE_URL", "http://fake:11434")
    from backend.modules.llm._admin_handlers import build_admin_router
    from backend import dependencies

    app = FastAPI()
    app.dependency_overrides[dependencies.require_admin] = lambda: {"id": "u1"}
    app.include_router(build_admin_router(), prefix="/api/llm/admin")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.post(
            "/api/llm/admin/ollama-local/pull",
            json={"slug": "   "},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_admin_delete_forwards_to_ollama(monkeypatch):
    monkeypatch.setenv("OLLAMA_LOCAL_BASE_URL", "http://fake:11434")
    from backend.modules.llm._admin_handlers import build_admin_router
    from backend import dependencies

    calls = []
    def handler(req):
        calls.append((req.method, req.url.path))
        return httpx.Response(200)
    transport = httpx.MockTransport(handler)

    fake_bus = _FakeBus()
    app = FastAPI()
    app.dependency_overrides[dependencies.require_admin] = lambda: {"id": "u1"}
    app.include_router(
        build_admin_router(
            http_transport=transport,
            event_bus_factory=lambda: fake_bus,
        ),
        prefix="/api/llm/admin",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.delete("/api/llm/admin/ollama-local/models/llama3.2")
    assert resp.status_code == 204
    assert ("DELETE", "/api/delete") in calls
    from shared.topics import Topics
    topics = [ev[0] for ev in fake_bus.events]
    assert Topics.LLM_MODEL_DELETED in topics


@pytest.mark.asyncio
async def test_admin_cancel_unknown_pull_returns_404(monkeypatch):
    monkeypatch.setenv("OLLAMA_LOCAL_BASE_URL", "http://fake:11434")
    from backend.modules.llm._admin_handlers import build_admin_router
    from backend import dependencies

    app = FastAPI()
    app.dependency_overrides[dependencies.require_admin] = lambda: {"id": "u1"}
    app.include_router(build_admin_router(), prefix="/api/llm/admin")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.post(
            "/api/llm/admin/ollama-local/pull/nonexistent/cancel",
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_admin_list_pulls_returns_empty_when_none(monkeypatch):
    monkeypatch.setenv("OLLAMA_LOCAL_BASE_URL", "http://fake:11434")
    from backend.modules.llm._admin_handlers import build_admin_router
    from backend import dependencies

    app = FastAPI()
    app.dependency_overrides[dependencies.require_admin] = lambda: {"id": "u1"}
    app.include_router(build_admin_router(), prefix="/api/llm/admin")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        resp = await client.get("/api/llm/admin/ollama-local/pulls")
    assert resp.status_code == 200
    assert resp.json() == {"pulls": []}
