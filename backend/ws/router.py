import asyncio
import json
import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

_STREAM_ID_RE = re.compile(r"^\d+-\d+$")

from backend.database import get_db, get_redis
from backend.modules.chat import (
    handle_chat_cancel,
    handle_chat_compaction_request,
    handle_chat_edit,
    handle_chat_regenerate,
    handle_chat_retract,
    handle_chat_send,
    handle_incognito_send,
    maybe_trigger_disconnect_extraction,
    reset_disconnect_extraction_guard,
)
from backend.modules.tools import get_client_dispatcher, get_mcp_registry, set_mcp_registry, remove_mcp_registry, eager_discover_mcp
from backend.modules.tools._mcp_discovery import register_local_tools
from backend.modules.tools._namespace import normalise_namespace
from backend.modules.integrations import emit_integration_secrets_for_user
from backend.modules.user import decode_access_token
from backend.ws.event_bus import get_event_bus
from backend.ws.manager import get_manager
from shared.dtos.mcp import McpToolRegistrationPayload, McpToolDeregistrationPayload
from shared.dtos.tools import ClientToolResultDto

_log = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task] = set()


def get_background_tasks() -> set[asyncio.Task]:
    """Return the set of in-flight WebSocket background tasks."""
    return _background_tasks


async def _delayed_disconnect_cleanup(
    *,
    user_id: str,
    connection_id: str,
) -> None:
    """Run cleanup actions a few seconds after a WS disconnect.

    The 10-second grace absorbs flaky-network reconnects. After the
    grace, if the user is still offline:
    - Pending client-side tool futures are resolved with a synthetic
      'client disconnected' error so the inference loop can complete
      cleanly without the user.
    - The MCP registry tied to this WS connection is removed.

    What this function NO LONGER does (compared to the pre-background-
    completions design):
    - It does **not** cancel inflight inferences. They run to natural
      completion and persist their answers, even if the user never
      reconnects. See devdocs/specs/2026-05-07-background-completions-
      design.md.
    - It does **not** trigger disconnect-extraction directly. That is
      now anchored to inference cleanup (Task 4) so the extractor sees
      the final answers, not snapshots taken mid-stream.
    """
    try:
        await asyncio.sleep(10)
        await _run_disconnect_cleanup(
            user_id=user_id,
            connection_id=connection_id,
            has_reconnect=_manager_has_reconnect(user_id),
        )
    except asyncio.CancelledError:
        # Event-loop shutdown during the grace window. Let asyncio see
        # this so the task closes cleanly; cleanup intentionally does
        # not run in this case.
        raise
    except Exception as exc:
        _log.error(
            "Error in delayed disconnect cleanup for user %s: %s",
            user_id, exc,
        )


def _manager_has_reconnect(user_id: str) -> bool:
    """Has the user reconnected during the grace period?"""
    return get_manager().has_connections(user_id)


async def _run_disconnect_cleanup(
    *,
    user_id: str,
    connection_id: str,
    has_reconnect: bool,
) -> None:
    """Perform post-grace disconnect cleanup. Sleep-free so tests can drive it directly."""
    if has_reconnect:
        return
    try:
        get_client_dispatcher().cancel_for_user(user_id)
    except Exception:
        _log.warning(
            "Failed to resolve pending client tools for user %s",
            user_id, exc_info=True,
        )
    remove_mcp_registry(connection_id)

    # Safety net: if the user disconnected and has no inflight inferences
    # right now (so the inference-cleanup anchor will never fire), trigger
    # extraction directly. Wait an additional 30 s after the 10 s grace so
    # any inference that started just before disconnect has a chance to
    # register itself in ``_inflight``.
    safety_task = asyncio.create_task(_extraction_safety_net(user_id))
    _background_tasks.add(safety_task)
    safety_task.add_done_callback(_background_tasks.discard)


async def _extraction_safety_net(user_id: str) -> None:
    try:
        await asyncio.sleep(30)
        await maybe_trigger_disconnect_extraction(user_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        _log.warning(
            "extraction safety net failed for user %s",
            user_id, exc_info=True,
        )


ws_router = APIRouter()


@ws_router.websocket("/ws")
async def websocket_endpoint(
    ws: WebSocket,
    token: str = Query(...),
    since: str | None = Query(default=None),
) -> None:
    try:
        payload = decode_access_token(token)
    except Exception:
        await ws.close(code=4001)
        return

    if payload.get("mcp"):
        await ws.close(code=4003)
        return

    user_id = payload.get("sub")
    role = payload.get("role")
    exp = payload.get("exp")
    if not user_id or not role or exp is None:
        _log.warning("WebSocket token missing required claims (sub/role/exp)")
        await ws.close(code=4001)
        return

    manager = get_manager()
    await ws.accept()
    connection_id = await manager.connect(user_id, role, ws)
    # Fresh connection: clear any one-shot disconnect-extraction guard so the
    # next offline window is eligible to trigger extraction again. Done after
    # manager.connect so has_connections() already returns True — this avoids
    # a narrow window where the safety-net task could observe no connections
    # while the guard is already cleared, double-triggering extraction.
    reset_disconnect_extraction_guard(user_id)
    try:
        await ws.send_json({"type": "ws.hello", "connection_id": connection_id})
    except Exception:
        _log.warning("Failed to send ws.hello to user %s", user_id)

    # Hydrate integration secrets so the frontend has decrypted keys immediately
    try:
        await emit_integration_secrets_for_user(
            user_id=user_id,
            db=get_db(),
            event_bus=get_event_bus(),
        )
    except Exception:
        _log.exception("Integration secrets hydration failed for user %s", user_id)

    # Eagerly discover MCP tools so they are ready before the first message
    async def _eager_mcp() -> None:
        try:
            await eager_discover_mcp(connection_id, user_id)
        except Exception:
            _log.exception("Eager MCP discovery failed for user %s", user_id)

    mcp_task = asyncio.create_task(_eager_mcp())
    _background_tasks.add(mcp_task)
    mcp_task.add_done_callback(_background_tasks.discard)

    expiry_task: asyncio.Task | None = None

    try:
        if since is not None:
            # Replay across all scopes (global, session:<id>, persona:<id>,
            # user:<id>, ...). Each persisted stream entry carries the
            # fan-out targeting (roles + target user ids) it was published
            # with, so we can securely filter replay per-user without
            # leaking events across users. Entries are merged in
            # stream-id order, which is time-ordered, so sequence
            # monotonicity on the frontend is preserved.
            if not _STREAM_ID_RE.match(since):
                _log.warning("Ignoring invalid 'since' stream id from client: %r", since)
            else:
                redis = get_redis()
                collected: list[tuple[str, dict]] = []
                try:
                    async for key in redis.scan_iter(match="events:*"):
                        try:
                            entries = await redis.xrange(
                                key, min=f"({since}", max="+",
                            )
                        except Exception:
                            _log.exception(
                                "Failed to xrange replay stream %r for user %s",
                                key, user_id,
                            )
                            continue
                        for stream_id, data in entries:
                            roles_field = data.get("roles", "")
                            targets_field = data.get("targets", "")
                            roles_list = [r for r in roles_field.split(",") if r]
                            targets_list = [t for t in targets_field.split(",") if t]
                            # Allow-rules, in priority order:
                            #   1. Broadcast-all (roles contains "*")
                            #   2. User is in explicit target user ids
                            #   3. User's role matches an authorised role
                            #   4. Legacy entry with no targeting metadata
                            #      AND scope == "global" (backwards compat
                            #      during the deployment window while old
                            #      entries from before this change are
                            #      still within the 24h retention).
                            authorised = False
                            if "*" in roles_list:
                                authorised = True
                            elif user_id in targets_list:
                                authorised = True
                            elif role in roles_list:
                                authorised = True
                            elif not roles_list and not targets_list and key == "events:global":
                                authorised = True
                            if not authorised:
                                continue
                            collected.append((stream_id, data))
                except Exception:
                    _log.exception(
                        "Failed to scan replay streams for user %s", user_id
                    )

                # Merge by stream id — Redis stream ids are "<ms>-<seq>"
                # and time-ordered across streams, so lexicographic sort
                # on the (ms, seq) tuple yields the correct delivery order.
                def _sort_key(item: tuple[str, dict]) -> tuple[int, int]:
                    sid = item[0]
                    ms_str, _, seq_str = sid.partition("-")
                    try:
                        return (int(ms_str), int(seq_str) if seq_str else 0)
                    except ValueError:
                        return (0, 0)

                collected.sort(key=_sort_key)
                for stream_id, data in collected:
                    try:
                        envelope = json.loads(data["envelope"])
                        envelope["sequence"] = stream_id
                        await ws.send_json(envelope)
                    except Exception:
                        _log.exception("Failed to replay stream entry %s", stream_id)

        async def _send_expiry_warning() -> None:
            now = datetime.now(timezone.utc).timestamp()
            delay = exp - 120 - now
            if delay > 0:
                await asyncio.sleep(delay)
                try:
                    await ws.send_json({"type": "token.expiring_soon"})
                except Exception:
                    pass

        expiry_task = asyncio.create_task(_send_expiry_warning())

        while True:
            data = await ws.receive_json()
            msg_type = data.get("type")

            if msg_type == "ping":
                await ws.send_json({"type": "pong"})
            elif msg_type == "chat.send":
                task = asyncio.create_task(handle_chat_send(user_id, data, connection_id=connection_id))
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)
            elif msg_type == "chat.cancel":
                handle_chat_cancel(user_id, data)
            elif msg_type == "chat.retract":
                await handle_chat_retract(user_id, data)
            elif msg_type == "chat.edit":
                task = asyncio.create_task(handle_chat_edit(user_id, data, connection_id=connection_id))
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)
            elif msg_type == "chat.regenerate":
                task = asyncio.create_task(handle_chat_regenerate(user_id, data, connection_id=connection_id))
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)
            elif msg_type == "chat.compaction.request":
                task = asyncio.create_task(handle_chat_compaction_request(user_id, data, connection_id=connection_id))
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)
            elif msg_type == "chat.incognito.send":
                task = asyncio.create_task(handle_incognito_send(user_id, data, connection_id=connection_id))
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)
            elif msg_type == "chat.client_tool.result":
                try:
                    dto = ClientToolResultDto.model_validate(data)
                except ValidationError as e:
                    _log.warning(
                        "malformed chat.client_tool.result from user=%s connection=%s: %s",
                        user_id, connection_id, e,
                    )
                else:
                    get_client_dispatcher().resolve(
                        tool_call_id=dto.tool_call_id,
                        received_from_user_id=user_id,
                        result_json=dto.result.model_dump_json(),
                    )
            elif msg_type == "mcp.tools.register":
                try:
                    payload = McpToolRegistrationPayload.model_validate(data.get("payload", data))
                except ValidationError as e:
                    _log.warning(
                        "malformed mcp.tools.register from user=%s connection=%s: %s",
                        user_id, connection_id, e,
                    )
                else:
                    registry = get_mcp_registry(connection_id)
                    if registry is None:
                        from backend.modules.tools._mcp_registry import SessionMcpRegistry
                        registry = SessionMcpRegistry()
                        set_mcp_registry(connection_id, registry)
                    namespace = normalise_namespace(payload.name)
                    try:
                        register_local_tools(
                            registry=registry,
                            gateway_id=payload.gateway_id,
                            namespace=namespace,
                            url="",  # local gateways: URL not needed server-side
                            tools=payload.tools,
                        )
                        _log.info(
                            "Registered %d local MCP tools from gateway '%s' for user=%s",
                            len(payload.tools), namespace, user_id,
                        )
                    except ValueError as exc:
                        _log.warning("MCP registration failed: %s", exc)
            elif msg_type == "mcp.tools.deregister":
                try:
                    payload = McpToolDeregistrationPayload.model_validate(data.get("payload", data))
                except ValidationError as e:
                    _log.warning(
                        "malformed mcp.tools.deregister from user=%s connection=%s: %s",
                        user_id, connection_id, e,
                    )
                else:
                    registry = get_mcp_registry(connection_id)
                    if registry is not None:
                        removed = registry.unregister_by_id(payload.gateway_id)
                        # No event emission — local mutations are entirely
                        # frontend-driven; the frontend updates its own
                        # sessionGateways synchronously, and an echo would
                        # re-introduce the duplicate-merge bug fixed by
                        # filtering tier=local out of MCP_TOOLS_REGISTERED
                        # (see devdocs/specs/2026-05-10-mcp-gateway-sync-design.md §4.1).
                        _log.info(
                            "Deregistered local MCP gateway id=%s for user=%s (removed=%s)",
                            payload.gateway_id, user_id, removed,
                        )

            # token.refresh is handled via POST /api/auth/refresh (HTTP) — the httpOnly
            # refresh token cookie cannot be updated over WebSocket; the token.expiring_soon
            # event prompts the client to refresh via the REST endpoint

    except WebSocketDisconnect:
        pass
    except Exception as e:
        _log.error("Unexpected error in WebSocket handler for user %s: %s", user_id, e)
    finally:
        if expiry_task is not None:
            expiry_task.cancel()
        # Drop this specific socket from the manager. The delayed-cancel
        # task below checks whether the user still has any live sockets,
        # so this must happen first.
        await manager.disconnect(user_id, ws)

        # Spawn the disconnect cleanup as a fire-and-forget background
        # task — it sleeps for the grace period and then runs cleanup
        # if the user has not reconnected.
        cleanup_task = asyncio.create_task(
            _delayed_disconnect_cleanup(
                user_id=user_id,
                connection_id=connection_id,
            )
        )
        _background_tasks.add(cleanup_task)
        cleanup_task.add_done_callback(_background_tasks.discard)
