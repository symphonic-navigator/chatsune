"""Domain events for per-user key lifecycle."""

from typing import Literal

from pydantic import BaseModel


class UserKeyProvisionedEvent(BaseModel):
    user_id: str
    reason: Literal["signup", "migration"]
    # Recovery key is never in this event. Signup: the client already has it
    # (it generated it). Migration: the server returns it once in the
    # /login-legacy HTTP response body.


class UserKeyRecoveryRequiredEvent(BaseModel):
    user_id: str
    triggered_by_admin_id: str | None = None


class UserKeyRecoveredEvent(BaseModel):
    user_id: str


class UserKeyRecoveryDeclinedEvent(BaseModel):
    user_id: str
