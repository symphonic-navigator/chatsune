"""MCP JSON-RPC client for backend-executed tool calls (admin + user-remote gateways)."""

from __future__ import annotations

import inspect
import json
import logging

import httpx

_log = logging.getLogger(__name__)

_MCP_HTTP_TIMEOUT_S = 30
_REQUEST_ID_COUNTER = 0


def _next_request_id() -> int:
    global _REQUEST_ID_COUNTER
    _REQUEST_ID_COUNTER += 1
    return _REQUEST_ID_COUNTER


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
        """
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "jsonrpc": "2.0",
            "id": _next_request_id(),
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=_MCP_HTTP_TIMEOUT_S) as client:
                resp = await client.post(url, json=payload, headers=headers)

            # httpx Response.json() is sync; in tests the mock may be async — handle both
            _raw = resp.json()
            body = (await _raw) if inspect.isawaitable(_raw) else _raw

            # JSON-RPC error
            if "error" in body:
                err = body["error"]
                msg = err.get("message", str(err))
                _log.warning("MCP JSON-RPC error from %s: %s", url, msg)
                return json.dumps({"stdout": "", "error": f"MCP error: {msg}"})

            # Successful result — extract text content
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
        """
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "jsonrpc": "2.0",
            "id": _next_request_id(),
            "method": "tools/list",
        }

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)

            _raw = resp.json()
            body = (await _raw) if inspect.isawaitable(_raw) else _raw
            if "error" in body:
                _log.warning("MCP tools/list error from %s: %s", url, body["error"])
                return []

            return body.get("result", {}).get("tools", [])

        except Exception as exc:
            _log.warning("MCP tools/list failed for %s: %s", url, exc)
            return []
