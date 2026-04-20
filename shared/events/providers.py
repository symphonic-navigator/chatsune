"""Events for the Premium Provider Accounts module."""

from typing import Literal

from pydantic import BaseModel


class PremiumProviderAccountUpsertedEvent(BaseModel):
    type: str = "providers.account.upserted"
    provider_id: str


class PremiumProviderAccountDeletedEvent(BaseModel):
    type: str = "providers.account.deleted"
    provider_id: str


class PremiumProviderAccountTestedEvent(BaseModel):
    type: str = "providers.account.tested"
    provider_id: str
    status: Literal["ok", "error"]
    error: str | None = None
