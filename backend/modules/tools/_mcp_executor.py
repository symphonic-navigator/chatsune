"""MCP JSON-RPC client for backend-executed tool calls (admin + user-remote gateways)."""

from __future__ import annotations

import json
import logging

import httpx

_log = logging.getLogger(__name__)

_MCP_HTTP_TIMEOUT_S = 30
_REQUEST_ID_COUNTER = 0

MCP_PROTOCOL_VERSION = "2025-06-18"


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


class McpExecutor:
    """Calls MCP gateway tools via HTTP JSON-RPC.

    Stateless — one instance can be shared across connections.
    """

    async def call_tool(
        self,
        *,
        url: str,
        api_key: str | None,
        tool_name: str,
        arguments: dict,
    ) -> str:
        """Call a tool on a gateway and return JSON string {"stdout": ..., "error": ...}.

        Never raises. All failure modes produce an error in the returned JSON.
        Speaks the MCP Streamable HTTP transport: advertises support for both
        application/json and text/event-stream, and handles whichever the
        server picks.
        """
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

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
                text = "\n".join(p.get("text", "") for p in content_parts if p.get("type") == "text")
                return json.dumps({"stdout": "", "error": text or "Tool returned an error"})

            content_parts = result.get("content", [])
            text = "\n".join(p.get("text", "") for p in content_parts if p.get("type") == "text")
            return json.dumps({"stdout": text, "error": None})

        except httpx.TimeoutException:
            _log.warning("MCP call timed out: %s tool=%s", url, tool_name)
            return json.dumps({"stdout": "", "error": f"MCP gateway timeout after {_MCP_HTTP_TIMEOUT_S}s"})
        except Exception as exc:
            _log.warning("MCP call failed: %s tool=%s error=%s", url, tool_name, exc)
            return json.dumps({"stdout": "", "error": f"MCP gateway unreachable: {exc}"})

    async def discover_tools(
        self,
        *,
        url: str,
        api_key: str | None,
        timeout: float = 10.0,
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
