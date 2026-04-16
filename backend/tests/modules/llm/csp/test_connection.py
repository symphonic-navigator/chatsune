import asyncio
import json

import pytest

from backend.modules.llm._csp._connection import SidecarConnection
from backend.modules.llm._csp._errors import CSPConnectionClosed


class FakeWS:
    """In-process stand-in for Starlette's WebSocket."""

    def __init__(self) -> None:
        self.to_client: asyncio.Queue[str] = asyncio.Queue()  # backend → sidecar
        self.from_client: asyncio.Queue[str | None] = asyncio.Queue()  # sidecar → backend
        self.closed = False

    async def send_text(self, text: str) -> None:
        if self.closed:
            raise RuntimeError("closed")
        await self.to_client.put(text)

    async def receive_text(self) -> str:
        v = await self.from_client.get()
        if v is None:
            raise CSPConnectionClosed()
        return v

    async def close(self, code: int = 1000) -> None:
        self.closed = True
        await self.from_client.put(None)

    # Helpers for tests
    async def feed(self, payload: dict) -> None:
        await self.from_client.put(json.dumps(payload))

    async def drain_to_client(self) -> dict:
        return json.loads(await self.to_client.get())


@pytest.mark.asyncio
async def test_list_models_roundtrip():
    ws = FakeWS()
    conn = SidecarConnection(
        ws=ws,
        homelab_id="H1",
        display_name="A",
        max_concurrent=2,
        capabilities={"chat_streaming"},
        sidecar_version="1.0.0",
        engine_info={"type": "ollama", "version": "0.5"},
    )
    loop_task = asyncio.create_task(conn.run())

    async def fake_sidecar():
        req = await ws.drain_to_client()
        assert req["type"] == "req"
        assert req["op"] == "list_models"
        await ws.feed(
            {
                "type": "res",
                "id": req["id"],
                "ok": True,
                "body": {
                    "models": [
                        {
                            "slug": "llama3.2:8b",
                            "display_name": "Llama 3.2 8B",
                            "context_length": 131072,
                            "capabilities": ["text"],
                        }
                    ]
                },
            }
        )

    sidecar_task = asyncio.create_task(fake_sidecar())
    models = await asyncio.wait_for(conn.rpc_list_models(), timeout=2.0)
    await sidecar_task
    assert models[0]["slug"] == "llama3.2:8b"

    await conn.close()
    await loop_task


@pytest.mark.asyncio
async def test_generate_chat_streams_deltas():
    ws = FakeWS()
    conn = SidecarConnection(
        ws=ws, homelab_id="H1", display_name="A", max_concurrent=2,
        capabilities={"chat_streaming"}, sidecar_version="1.0.0",
        engine_info={"type": "ollama"},
    )
    loop_task = asyncio.create_task(conn.run())

    async def fake_sidecar():
        req = await ws.drain_to_client()
        rid = req["id"]
        for ch in ["Hel", "lo", "!"]:
            await ws.feed({"type": "stream", "id": rid, "delta": {"content": ch}})
        await ws.feed(
            {
                "type": "stream_end",
                "id": rid,
                "finish_reason": "stop",
                "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            }
        )

    asyncio.create_task(fake_sidecar())
    received = []
    async for frame in conn.rpc_generate_chat(body={"model_slug": "x", "messages": []}):
        received.append(frame)
    contents = [f.delta.content for f in received[:-1]]
    assert contents == ["Hel", "lo", "!"]
    assert received[-1].type == "stream_end"

    await conn.close()
    await loop_task


@pytest.mark.asyncio
async def test_generate_chat_propagates_err_then_stream_end():
    ws = FakeWS()
    conn = SidecarConnection(
        ws=ws, homelab_id="H1", display_name="A", max_concurrent=2,
        capabilities={"chat_streaming"}, sidecar_version="1.0.0",
        engine_info={"type": "ollama"},
    )
    loop_task = asyncio.create_task(conn.run())

    async def fake_sidecar():
        req = await ws.drain_to_client()
        rid = req["id"]
        await ws.feed(
            {
                "type": "err", "id": rid, "code": "model_oom",
                "message": "VRAM exhausted", "recoverable": True,
            }
        )
        await ws.feed(
            {"type": "stream_end", "id": rid, "finish_reason": "error"}
        )

    asyncio.create_task(fake_sidecar())
    frames = [f async for f in conn.rpc_generate_chat(body={})]
    assert frames[0].type == "err"
    assert frames[0].code == "model_oom"
    assert frames[1].type == "stream_end"

    await conn.close()
    await loop_task


@pytest.mark.asyncio
async def test_cancel_sends_cancel_frame_and_awaits_stream_end():
    ws = FakeWS()
    conn = SidecarConnection(
        ws=ws, homelab_id="H1", display_name="A", max_concurrent=2,
        capabilities={"chat_streaming"}, sidecar_version="1.0.0",
        engine_info={"type": "ollama"},
    )
    loop_task = asyncio.create_task(conn.run())

    cancel_received: dict = {}

    async def fake_sidecar():
        req = await ws.drain_to_client()
        rid = req["id"]
        # emit one chunk, then wait for cancel
        await ws.feed({"type": "stream", "id": rid, "delta": {"content": "A"}})
        maybe_cancel = await ws.drain_to_client()
        cancel_received.update(maybe_cancel)
        await ws.feed(
            {"type": "stream_end", "id": rid, "finish_reason": "cancelled"}
        )

    asyncio.create_task(fake_sidecar())
    gen = conn.rpc_generate_chat(body={})
    first = await gen.__anext__()
    assert first.delta.content == "A"
    await gen.aclose()  # caller cancels the generator

    await asyncio.sleep(0.05)
    assert cancel_received.get("type") == "cancel"

    await conn.close()
    await loop_task


@pytest.mark.asyncio
async def test_rpc_raises_after_close():
    ws = FakeWS()
    conn = SidecarConnection(
        ws=ws, homelab_id="H1", display_name="A", max_concurrent=1,
        capabilities={"chat_streaming"}, sidecar_version="1.0.0",
        engine_info={"type": "ollama"},
    )
    loop_task = asyncio.create_task(conn.run())
    await conn.close()
    await loop_task
    with pytest.raises(CSPConnectionClosed):
        await conn.rpc_list_models()
