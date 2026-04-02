import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.main import app
from backend.modules.user._auth import create_access_token, generate_session_id


def valid_token(role: str = "user", mcp: bool = False) -> str:
    return create_access_token(
        user_id="test-user-id",
        role=role,
        session_id=generate_session_id(),
        must_change_password=mcp,
    )


@pytest.fixture
def ws_client():
    with TestClient(app) as client:
        yield client


def test_ws_rejects_missing_token(ws_client):
    with pytest.raises(Exception):
        with ws_client.websocket_connect("/ws"):
            pass


def test_ws_rejects_invalid_token(ws_client):
    with pytest.raises(Exception):
        with ws_client.websocket_connect("/ws?token=not-a-jwt"):
            pass


def test_ws_rejects_mcp_token(ws_client):
    token = valid_token(mcp=True)
    with pytest.raises(Exception):
        with ws_client.websocket_connect(f"/ws?token={token}"):
            pass


def test_ws_accepts_valid_token_and_responds_to_ping(ws_client):
    token = valid_token(role="user")
    with ws_client.websocket_connect(f"/ws?token={token}") as ws:
        ws.send_json({"type": "ping"})
        data = ws.receive_json()
        assert data["type"] == "pong"


def test_ws_ignores_unknown_message_types(ws_client):
    token = valid_token(role="user")
    with ws_client.websocket_connect(f"/ws?token={token}") as ws:
        ws.send_json({"type": "unknown_type"})
        ws.send_json({"type": "ping"})
        data = ws.receive_json()
        assert data["type"] == "pong"


def test_ws_replays_missed_events_on_reconnect(ws_client):
    """Seed a Redis stream event, connect with since=0-0, verify replay."""
    import json
    import asyncio
    from redis.asyncio import Redis
    from backend.config import settings

    async def seed_stream():
        r = Redis.from_url(settings.redis_uri, decode_responses=True)
        stream_id = await r.xadd(
            "events:global",
            {"envelope": json.dumps({
                "id": "evt-1",
                "type": "user.created",
                "sequence": "",
                "scope": "global",
                "correlation_id": "corr-1",
                "timestamp": "2026-04-03T00:00:00+00:00",
                "payload": {"user_id": "u1"},
            })}
        )
        await r.aclose()
        return stream_id

    stream_id = asyncio.get_event_loop().run_until_complete(seed_stream())

    token = valid_token(role="admin")
    with ws_client.websocket_connect(f"/ws?token={token}&since=0-0") as ws:
        data = ws.receive_json()
        assert data["type"] == "user.created"
        assert data["sequence"] == stream_id
