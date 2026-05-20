"""MCP JSON-RPC client for backend-executed tool calls (admin + user-remote gateways)."""

from __future__ import annotations

import asyncio
import json
import logging
from urllib.parse import urlparse

import httpx

_log = logging.getLogger(__name__)

_MCP_HTTP_TIMEOUT_S = 30
_REQUEST_ID_COUNTER = 0

MCP_PROTOCOL_VERSION = "2025-06-18"


def _normalise_mcp_url(url: str) -> str:
    """Return the URL Chatsune should POST MCP JSON-RPC to.

    Users may enter either:
    - a base URL (``https://mcp.example.com``) — historical Chatsune convention,
      we append the conventional ``/mcp`` path.
    - a full URL (``https://mcp.example.com/mcp`` or any other path) — the form
      every other MCP client (Claude Desktop, etc.) uses, taken verbatim.

    Decision is made on the URL's path: empty or ``"/"`` means base URL,
    anything else is treated as the full endpoint.
    """
    cleaned = url.rstrip("/")
    parsed = urlparse(cleaned)
    if parsed.path in ("", "/"):
        return cleaned + "/mcp"
    return cleaned


def _client_version() -> str:
    """Resolve the version string sent in MCP `clientInfo`.

    Tries Docker package name first (``chatsune-backend``), falls back
    to host dev package (``chatsune``), then ``"unknown"``. Resolved
    once at import time — version metadata does not change at runtime.
    """
    from importlib.metadata import PackageNotFoundError, version

    for name in ("chatsune-backend", "chatsune"):
        try:
            return version(name)
        except PackageNotFoundError:
            continue
    return "unknown"


_CLIENT_VERSION = _client_version()


def _next_request_id() -> int:
    global _REQUEST_ID_COUNTER
    _REQUEST_ID_COUNTER += 1
    return _REQUEST_ID_COUNTER


def _content_type(resp: httpx.Response) -> str:
    raw = resp.headers.get("content-type", "")
    return raw.split(";", 1)[0].strip().lower()


async def _read_sse_response(resp: httpx.Response, expected_id: int) -> dict:
    """Read an SSE stream until a JSON-RPC payload with `expected_id` arrives.

    Notifications (no `id`) are silently skipped, as are unrelated `id`s.
    Raises `RuntimeError` if the stream closes without a match.
    """
    async for line in resp.aiter_lines():
        if not line.startswith("data:"):
            continue
        data = line[5:].lstrip()
        if not data:
            continue
        try:
            obj = json.loads(data)
        except json.JSONDecodeError:
            _log.warning("MCP SSE: malformed data line: %r", data[:120])
            continue
        if obj.get("id") == expected_id:
            return obj
    raise RuntimeError("SSE stream closed without a matching JSON-RPC response")


class _NullAsyncLock:
    """No-op async context manager used when an explicit lock is not needed."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


_NULL_LOCK = _NullAsyncLock()


class McpExecutor:
    """Calls MCP gateway tools via HTTP JSON-RPC.

    Stateless — one instance can be shared across connections.
    """

    async def initialise(
        self,
        *,
        url: str,
        api_key: str | None,
        timeout: float = 10.0,
    ) -> str | None:
        """Run the MCP Streamable HTTP three-step handshake.

        Returns the ``Mcp-Session-Id`` issued by the server, or ``None`` if
        the server is operating in stateless mode (no header issued) or
        if the handshake failed at the protocol level (non-200 status).
        Always sends the ``notifications/initialized`` confirmation when
        the initialize step succeeded with 200.
        """
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        init_id = _next_request_id()
        init_payload = {
            "jsonrpc": "2.0",
            "id": init_id,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "chatsune", "version": _CLIENT_VERSION},
            },
        }

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST", url, json=init_payload, headers=headers
                ) as resp:
                    if resp.status_code != 200:
                        _log.warning(
                            "MCP initialise failed: HTTP %d from %s",
                            resp.status_code, url,
                        )
                        return None
                    session_id = resp.headers.get("mcp-session-id")
                    ctype = _content_type(resp)
                    if ctype == "application/json":
                        await resp.aread()
                    elif ctype == "text/event-stream":
                        try:
                            await _read_sse_response(resp, expected_id=init_id)
                        except RuntimeError:
                            # Server closed the stream without a matching reply.
                            # Header may still be set — that's the only piece
                            # we actually need from the handshake.
                            pass

                # Step 3: notifications/initialized — fire-and-forget.
                notif_headers = dict(headers)
                if session_id:
                    notif_headers["Mcp-Session-Id"] = session_id
                try:
                    await client.post(
                        url,
                        json={
                            "jsonrpc": "2.0",
                            "method": "notifications/initialized",
                        },
                        headers=notif_headers,
                    )
                except Exception as exc:
                    _log.warning(
                        "MCP notifications/initialized post failed for %s: %s",
                        url, exc,
                    )

            return session_id
        except Exception as exc:
            _log.warning("MCP initialise transport failure for %s: %s", url, exc)
            return None

    async def call_tool(
        self,
        *,
        url: str,
        api_key: str | None,
        tool_name: str,
        arguments: dict,
        session_id: str | None = None,
        on_session_refresh: "Callable[[str], Awaitable[None]] | None" = None,
        init_lock: "asyncio.Lock | None" = None,
        _retry: bool = True,
    ) -> str:
        """Call a tool on a gateway and return JSON string {"stdout": ..., "error": ...}.

        Never raises. All failure modes produce an error in the returned JSON.
        Speaks the MCP Streamable HTTP transport: advertises support for both
        application/json and text/event-stream, and handles whichever the
        server picks. When ``session_id`` is provided and the server
        responds 404 (session expired), the executor re-runs ``initialise``
        once (under ``init_lock`` if provided), notifies the caller of the
        new id via ``on_session_refresh``, and retries the call once.
        """
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        if session_id:
            headers["Mcp-Session-Id"] = session_id

        request_id = _next_request_id()
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }

        try:
            async with httpx.AsyncClient(timeout=_MCP_HTTP_TIMEOUT_S) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    if resp.status_code == 404 and session_id and _retry:
                        # Drain to free the connection before re-initialising.
                        await resp.aread()
                        async with (init_lock or _NULL_LOCK):
                            new_session_id = await self.initialise(url=url, api_key=api_key)
                        if new_session_id is None:
                            return json.dumps({
                                "stdout": "",
                                "error": "MCP session expired and re-initialise failed",
                            })
                        # Notify caller AFTER releasing the lock — the callback may do
                        # downstream I/O (DB write, event emit) that should not block
                        # other coroutines waiting on the same lock.
                        if on_session_refresh:
                            await on_session_refresh(new_session_id)
                        return await self.call_tool(
                            url=url, api_key=api_key,
                            tool_name=tool_name, arguments=arguments,
                            session_id=new_session_id,
                            on_session_refresh=on_session_refresh,
                            init_lock=init_lock,
                            _retry=False,
                        )

                    if resp.status_code != 200:
                        await resp.aread()
                        return json.dumps({
                            "stdout": "",
                            "error": f"MCP gateway returned HTTP {resp.status_code}",
                        })

                    ctype = _content_type(resp)

                    if ctype == "application/json":
                        body_bytes = await resp.aread()
                        body = json.loads(body_bytes)

                    elif ctype == "text/event-stream":
                        body = await _read_sse_response(resp, expected_id=request_id)

                    else:
                        _log.warning("MCP unexpected content-type from %s: %r", url, ctype)
                        return json.dumps({
                            "stdout": "",
                            "error": f"MCP gateway returned unexpected content-type: {ctype!r}",
                        })

            if "error" in body:
                err = body["error"]
                msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                _log.warning("MCP JSON-RPC error from %s: %s", url, msg)
                return json.dumps({"stdout": "", "error": f"MCP error: {msg}"})

            result = body.get("result", {})
            if result.get("isError"):
                content_parts = result.get("content", [])
                text = "\n".join(
                    p.get("text", "") for p in content_parts if p.get("type") == "text"
                )
                return json.dumps({"stdout": "", "error": text or "Tool returned an error"})

            content_parts = result.get("content", [])
            text = "\n".join(
                p.get("text", "") for p in content_parts if p.get("type") == "text"
            )
            return json.dumps({"stdout": text, "error": None})

        except httpx.TimeoutException:
            _log.warning("MCP call timed out: %s tool=%s", url, tool_name)
            return json.dumps({
                "stdout": "",
                "error": f"MCP gateway timeout after {_MCP_HTTP_TIMEOUT_S}s",
            })
        except Exception as exc:
            _log.warning("MCP call failed: %s tool=%s error=%s", url, tool_name, exc)
            return json.dumps({"stdout": "", "error": f"MCP gateway unreachable: {exc}"})

    async def discover_tools(
        self,
        *,
        url: str,
        api_key: str | None,
        timeout: float = 10.0,
        session_id: str | None = None,
    ) -> list[dict]:
        """Call tools/list on a gateway. Returns list of tool dicts or empty on failure.

        Does NOT raise — returns empty list on any error.
        Speaks Streamable HTTP just like call_tool.
        """
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        if session_id:
            headers["Mcp-Session-Id"] = session_id

        request_id = _next_request_id()
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/list",
        }

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    ctype = _content_type(resp)

                    if ctype == "application/json":
                        body_bytes = await resp.aread()
                        body = json.loads(body_bytes)

                    elif ctype == "text/event-stream":
                        body = await _read_sse_response(resp, expected_id=request_id)

                    else:
                        _log.warning("MCP discover unexpected content-type from %s: %r", url, ctype)
                        return []

            if "error" in body:
                _log.warning("MCP tools/list error from %s: %s", url, body["error"])
                return []

            return body.get("result", {}).get("tools", [])

        except Exception as exc:
            _log.warning("MCP tools/list failed for %s: %s", url, exc)
            return []

    async def call_tool_oneshot(
        self,
        *,
        url: str,
        api_key: str | None,
        tool_name: str,
        arguments: dict,
    ) -> str:
        """Initialise → call_tool → return. Used by stateless proxy routes.

        Each invocation runs the full handshake; session state is not
        retained between calls. See spec section 3 (proxy lifecycle).
        """
        session_id = await self.initialise(url=url, api_key=api_key)
        return await self.call_tool(
            url=url, api_key=api_key,
            tool_name=tool_name, arguments=arguments,
            session_id=session_id,
        )

    async def discover_tools_oneshot(
        self,
        *,
        url: str,
        api_key: str | None,
        timeout: float = 10.0,
    ) -> list[dict]:
        """Initialise → tools/list → return. Used by stateless proxy routes."""
        session_id = await self.initialise(url=url, api_key=api_key, timeout=timeout)
        return await self.discover_tools(
            url=url, api_key=api_key, timeout=timeout, session_id=session_id,
        )
