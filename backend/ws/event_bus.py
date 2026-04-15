import asyncio
import logging
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel
from redis.asyncio import Redis

_log = logging.getLogger(__name__)

from backend.ws.manager import ConnectionManager
from shared.events.base import BaseEvent
from shared.topics import Topics

_TWENTY_FOUR_HOURS_MS = 86_400_000

# Fan-out rules: (roles_to_broadcast, also_send_to_target_user_ids)
#
# KNOWN LIMITATION (BD-031): Admin events broadcast to ALL connected admins
# without resource-level scoping. Every admin sees every USER_CREATED,
# USER_UPDATED, etc. event regardless of whether they manage that user.
# Sensitive fields in USER_UPDATED payloads are visible to all admins.
# Revisit if per-admin scoping or field-level filtering is needed.
_FANOUT: dict[str, tuple[list[str], bool]] = {
    Topics.USER_CREATED: (["admin", "master_admin"], False),
    Topics.USER_UPDATED: (["admin", "master_admin"], True),
    Topics.USER_DEACTIVATED: (["admin", "master_admin"], True),
    # USER_DELETED — admins only; the target user is already logged out.
    Topics.USER_DELETED: (["admin", "master_admin"], False),
    Topics.USER_PASSWORD_RESET: (["admin", "master_admin"], True),
    Topics.USER_PROFILE_UPDATED: ([], True),
    Topics.PERSONA_CREATED: ([], True),
    Topics.PERSONA_UPDATED: ([], True),
    Topics.PERSONA_DELETED: ([], True),
    Topics.PERSONA_REORDERED: ([], True),
    # LLM Connections — target user only
    Topics.LLM_CONNECTION_CREATED: ([], True),
    Topics.LLM_CONNECTION_UPDATED: ([], True),
    Topics.LLM_CONNECTION_REMOVED: ([], True),
    Topics.LLM_CONNECTION_TESTED: ([], True),
    Topics.LLM_CONNECTION_STATUS_CHANGED: ([], True),
    Topics.LLM_CONNECTION_MODELS_REFRESHED: ([], True),
    Topics.LLM_USER_MODEL_CONFIG_UPDATED: ([], True),
    # LLM Model pull — target user only
    Topics.LLM_MODEL_PULL_STARTED: ([], True),
    Topics.LLM_MODEL_PULL_PROGRESS: ([], True),
    Topics.LLM_MODEL_PULL_COMPLETED: ([], True),
    Topics.LLM_MODEL_PULL_FAILED: ([], True),
    Topics.LLM_MODEL_PULL_CANCELLED: ([], True),
    Topics.LLM_MODEL_DELETED: ([], True),
    # Web Search — target user only
    Topics.WEBSEARCH_CREDENTIAL_SET: ([], True),
    Topics.WEBSEARCH_CREDENTIAL_REMOVED: ([], True),
    Topics.WEBSEARCH_CREDENTIAL_TESTED: ([], True),
    Topics.SETTING_UPDATED: (["admin", "master_admin"], False),
    Topics.SETTING_DELETED: (["admin", "master_admin"], False),
    Topics.SETTING_SYSTEM_PROMPT_UPDATED: (["admin", "master_admin"], False),
    Topics.CHAT_STREAM_STARTED: ([], True),
    Topics.CHAT_CONTENT_DELTA: ([], True),
    Topics.CHAT_THINKING_DELTA: ([], True),
    Topics.CHAT_STREAM_ENDED: ([], True),
    Topics.CHAT_STREAM_ERROR: ([], True),
    Topics.CHAT_STREAM_SLOW: ([], True),
    Topics.CHAT_MESSAGES_TRUNCATED: ([], True),
    Topics.CHAT_MESSAGE_UPDATED: ([], True),
    Topics.CHAT_MESSAGE_DELETED: ([], True),
    Topics.CHAT_SESSION_TITLE_UPDATED: ([], True),
    Topics.CHAT_SESSION_CREATED: ([], True),
    Topics.CHAT_SESSION_DELETED: ([], True),
    Topics.CHAT_SESSION_RESTORED: ([], True),
    Topics.CHAT_SESSION_PINNED_UPDATED: ([], True),
    # Bookmarks — target user only
    Topics.BOOKMARK_CREATED: ([], True),
    Topics.BOOKMARK_UPDATED: ([], True),
    Topics.BOOKMARK_DELETED: ([], True),
    # Tool call progress — target user only
    Topics.CHAT_TOOL_CALL_STARTED: ([], True),
    Topics.CHAT_TOOL_CALL_COMPLETED: ([], True),
    Topics.CHAT_CLIENT_TOOL_DISPATCH: ([], True),
    Topics.CHAT_WEB_SEARCH_CONTEXT: ([], True),
    Topics.CHAT_VISION_DESCRIPTION: ([], True),
    # Storage — target user only
    Topics.STORAGE_FILE_UPLOADED: ([], True),
    Topics.STORAGE_FILE_DELETED: ([], True),
    Topics.STORAGE_FILE_RENAMED: ([], True),
    Topics.STORAGE_QUOTA_WARNING: ([], True),
    # Tool group toggles
    Topics.CHAT_SESSION_TOOLS_UPDATED: ([], True),
    # Background jobs — target user only
    Topics.JOB_STARTED: ([], True),
    Topics.JOB_COMPLETED: ([], True),
    Topics.JOB_FAILED: ([], True),
    Topics.JOB_RETRY: ([], True),
    Topics.JOB_EXPIRED: ([], True),
    # Memory — target user only
    Topics.MEMORY_EXTRACTION_STARTED: ([], True),
    Topics.MEMORY_EXTRACTION_COMPLETED: ([], True),
    Topics.MEMORY_EXTRACTION_FAILED: ([], True),
    Topics.MEMORY_ENTRY_CREATED: ([], True),
    Topics.MEMORY_ENTRY_COMMITTED: ([], True),
    Topics.MEMORY_ENTRY_UPDATED: ([], True),
    Topics.MEMORY_ENTRY_DELETED: ([], True),
    Topics.MEMORY_ENTRY_AUTO_COMMITTED: ([], True),
    Topics.MEMORY_ENTRY_AUTHORED_BY_PERSONA: ([], True),
    Topics.MEMORY_ENTRIES_DISCARDED: ([], True),
    Topics.MEMORY_DREAM_STARTED: ([], True),
    Topics.MEMORY_DREAM_COMPLETED: ([], True),
    Topics.MEMORY_DREAM_FAILED: ([], True),
    Topics.MEMORY_BODY_ROLLBACK: ([], True),
    # Embedding — internal, no WebSocket delivery needed but suppresses warning
    Topics.EMBEDDING_MODEL_LOADING: ([], False),
    Topics.EMBEDDING_MODEL_READY: ([], False),
    Topics.EMBEDDING_BATCH_COMPLETED: ([], False),
    Topics.EMBEDDING_ERROR: ([], False),
    # Knowledge — target user only
    Topics.KNOWLEDGE_LIBRARY_CREATED: ([], True),
    Topics.KNOWLEDGE_LIBRARY_UPDATED: ([], True),
    Topics.KNOWLEDGE_LIBRARY_DELETED: ([], True),
    Topics.KNOWLEDGE_DOCUMENT_CREATED: ([], True),
    Topics.KNOWLEDGE_DOCUMENT_UPDATED: ([], True),
    Topics.KNOWLEDGE_DOCUMENT_DELETED: ([], True),
    Topics.KNOWLEDGE_DOCUMENT_EMBEDDING: ([], True),
    Topics.KNOWLEDGE_DOCUMENT_EMBEDDED: ([], True),
    Topics.KNOWLEDGE_DOCUMENT_EMBED_FAILED: ([], True),
    Topics.KNOWLEDGE_SEARCH_COMPLETED: ([], True),
    # Artefacts — target user only
    Topics.ARTEFACT_CREATED: ([], True),
    Topics.ARTEFACT_UPDATED: ([], True),
    Topics.ARTEFACT_DELETED: ([], True),
    Topics.ARTEFACT_UNDO: ([], True),
    Topics.ARTEFACT_REDO: ([], True),
    # Chat message creation — target user only (echoes optimistic ID for
    # frontend swap; see docs/superpowers/specs/2026-04-08-ollama-local-…)
    Topics.CHAT_MESSAGE_CREATED: ([], True),
    # MCP gateways — target user only
    Topics.MCP_TOOLS_REGISTERED: ([], True),
    Topics.MCP_GATEWAY_ERROR: ([], True),
    # Debug — admins only, no target user
    Topics.DEBUG_INFERENCE_STARTED: (["admin", "master_admin"], False),
    Topics.DEBUG_INFERENCE_FINISHED: (["admin", "master_admin"], False),
    Topics.DEBUG_SNAPSHOT: (["admin", "master_admin"], False),
}

# Intentionally empty after the connections refactor — repopulate when
# a future feature needs truly cross-user broadcasts.
_BROADCAST_ALL: set[str] = set()

# Chat events that skip Redis Streams persistence (high-frequency, ephemeral).
# They are delivered directly to the target user's WebSocket but not stored.
_SKIP_PERSISTENCE: set[str] = {
    Topics.CHAT_CONTENT_DELTA,
    Topics.CHAT_THINKING_DELTA,
    Topics.CHAT_TOOL_CALL_STARTED,
    Topics.CHAT_TOOL_CALL_COMPLETED,
    Topics.CHAT_CLIENT_TOOL_DISPATCH,
    Topics.CHAT_WEB_SEARCH_CONTEXT,
    # Debug events: high-frequency diagnostics, useless after the fact.
    # Admins re-fetch a fresh snapshot on (re)connect via the HTTP route.
    Topics.DEBUG_INFERENCE_STARTED,
    Topics.DEBUG_INFERENCE_FINISHED,
    Topics.DEBUG_SNAPSHOT,
}

_bus: "EventBus | None" = None


class EventBus:
    def __init__(self, redis: Redis, manager: ConnectionManager) -> None:
        self._redis = redis
        self._manager = manager
        self._internal_subscribers: dict[str, list] = {}

    def subscribe(self, topic: str, callback) -> None:
        """Register an internal async callback for a topic.

        The callback receives the raw event payload dict and is called
        after fan-out delivery. Used for server-side module coordination.
        """
        self._internal_subscribers.setdefault(topic, []).append(callback)

    async def publish(
        self,
        topic: str,
        event: BaseModel,
        scope: str = "global",
        target_user_ids: list[str] | None = None,
        correlation_id: str | None = None,
        target_connection_id: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        envelope = BaseEvent(
            type=topic,
            scope=scope,
            correlation_id=correlation_id or str(uuid4()),
            timestamp=now,
            payload=event.model_dump(mode="json"),
        )

        if topic not in _SKIP_PERSISTENCE:
            stream_key = f"events:{scope}"
            # Persist fan-out targeting alongside the envelope so that
            # reconnect/replay can determine which users are legitimately
            # allowed to receive each historical event — without leaking
            # across users. See backend/ws/router.py replay path.
            if topic in _BROADCAST_ALL:
                replay_roles: list[str] = ["*"]
                replay_targets: list[str] = []
            else:
                roles_rule, send_to_targets = _FANOUT.get(topic, ([], False))
                replay_roles = list(roles_rule)
                replay_targets = (
                    list(target_user_ids or []) if send_to_targets else []
                )
            stream_id = await self._redis.xadd(
                stream_key,
                {
                    "envelope": envelope.model_dump_json(),
                    "roles": ",".join(replay_roles),
                    "targets": ",".join(replay_targets),
                },
            )
            # Redis stream IDs have the form "<ms>-<seq>"; BaseEvent.sequence is str.
            envelope.sequence = stream_id
            # NOTE: periodic xtrim runs in start_periodic_trim() — no inline trim here.

        await self._fan_out(
            topic,
            envelope.model_dump(mode="json"),
            target_user_ids or [],
            target_connection_id=target_connection_id,
        )

        # Notify internal subscribers (server-side module coordination)
        for callback in self._internal_subscribers.get(topic, []):
            try:
                await callback(envelope.payload)
            except Exception:
                _log.exception("Internal subscriber failed for topic %r", topic)

    async def start_periodic_trim(self) -> asyncio.Task:
        """Start a background task that trims all event streams every 10 minutes."""

        async def _trim_loop() -> None:
            while True:
                await asyncio.sleep(600)  # 10 minutes
                try:
                    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                    min_id = str(now_ms - _TWENTY_FOUR_HOURS_MS)
                    async for key in self._redis.scan_iter(match="events:*"):
                        try:
                            await self._redis.xtrim(key, minid=min_id)
                        except Exception:
                            _log.warning("xtrim failed for stream %r", key, exc_info=True)
                except Exception:
                    _log.warning("Periodic stream trim cycle failed", exc_info=True)

        return asyncio.create_task(_trim_loop())

    async def _fan_out(
        self,
        topic: str,
        event_dict: dict,
        target_user_ids: list[str],
        *,
        target_connection_id: str | None = None,
    ) -> None:
        if topic == Topics.AUDIT_LOGGED:
            await self._fan_out_audit(event_dict)
            return

        if topic in _BROADCAST_ALL:
            await self._manager.broadcast_to_all(event_dict)
            return

        if topic not in _FANOUT:
            _log.warning(
                "EventBus: no fan-out rule for topic %r — event persisted but not delivered", topic
            )
            return

        roles, send_to_targets = _FANOUT[topic]
        # BD-031: broadcasts to ALL connected users with matching roles —
        # no resource-level filtering (see comment on _FANOUT).
        await self._manager.broadcast_to_roles(roles, event_dict)

        if target_connection_id is not None and target_user_ids:
            # Targeted delivery — exactly one (user_id, connection_id) pair.
            # Used by client-side tool dispatch to avoid duplicate execution
            # across multi-tab sessions. The first element of target_user_ids
            # is the owning user; we never deliver to other users even if
            # multiple are listed (targeted delivery is single-recipient).
            await self._manager.send_to_connection(
                target_user_ids[0], target_connection_id, event_dict,
            )
        elif send_to_targets and target_user_ids:
            await self._manager.send_to_users(target_user_ids, event_dict)

        # BD-020: sync cached role when an admin changes a user's role
        if topic == Topics.USER_UPDATED:
            new_role = event_dict.get("payload", {}).get("changes", {}).get("role")
            if new_role:
                for uid in target_user_ids:
                    self._manager.update_role(uid, new_role)

    async def _fan_out_audit(self, event_dict: dict) -> None:
        actor_id = event_dict.get("payload", {}).get("actor_id", "")
        await self._manager.broadcast_to_roles(["master_admin"], event_dict)
        for admin_id in self._manager.user_ids_by_role("admin"):
            if admin_id == actor_id:
                await self._manager.send_to_user(admin_id, event_dict)


def set_event_bus(bus: "EventBus") -> None:
    global _bus
    _bus = bus


def get_event_bus() -> "EventBus":
    if _bus is None:
        raise RuntimeError("EventBus not initialised")
    return _bus
