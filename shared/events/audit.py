from pydantic import BaseModel


class AuditLoggedEvent(BaseModel):
    actor_id: str
    action: str
    resource_type: str
    resource_id: str | None = None
    detail: dict | None = None
