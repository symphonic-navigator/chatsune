from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel
from redis.asyncio import Redis

from backend.ws.manager import ConnectionManager
from shared.events.base import BaseEvent
from shared.topics import Topics

_TWENTY_FOUR_HOURS_MS = 86_400_000

# (roles_to_broadcast, also_send_to_target_user_ids)
_FANOUT: dict[str, tuple[list[str], bool]] = {
    Topics.USER_CREATED: (["admin", "master_admin"], False),
    Topics.USER_UPDATED: (["admin", "master_admin"], True),
    Topics.USER_DEACTIVATED: (["admin", "master_admin"], True),
    Topics.USER_PASSWORD_RESET: (["admin", "master_admin"], True),
}

_bus: "EventBus | None" = None


class EventBus:
    def __init__(self, redis: Redis, manager: ConnectionManager) -> None:
        self._redis = redis
        self._manager = manager

    async def publish(
        self,
        topic: str,
        event: BaseModel,
        scope: str = "global",
        target_user_ids: list[str] | None = None,
        correlation_id: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        envelope = BaseEvent(
            type=topic,
            scope=scope,
            correlation_id=correlation_id or str(uuid4()),
            timestamp=now,
            payload=event.model_dump(mode="json"),
        )

        stream_key = f"events:{scope}"
        stream_id = await self._redis.xadd(
            stream_key, {"envelope": envelope.model_dump_json()}
        )
        envelope.sequence = stream_id

        now_ms = int(now.timestamp() * 1000)
        await self._redis.xtrim(
            stream_key, minid=str(now_ms - _TWENTY_FOUR_HOURS_MS)
        )

        await self._fan_out(
            topic, envelope.model_dump(mode="json"), target_user_ids or []
        )

    async def _fan_out(
        self, topic: str, event_dict: dict, target_user_ids: list[str]
    ) -> None:
        if topic == Topics.AUDIT_LOGGED:
            await self._fan_out_audit(event_dict)
            return

        if topic not in _FANOUT:
            return

        roles, send_to_targets = _FANOUT[topic]
        await self._manager.broadcast_to_roles(roles, event_dict)
        if send_to_targets and target_user_ids:
            await self._manager.send_to_users(target_user_ids, event_dict)

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
