from typing import Literal

from pydantic import BaseModel


class WebSearchResultDto(BaseModel):
    title: str
    url: str
    snippet: str


class WebFetchResultDto(BaseModel):
    url: str
    title: str | None = None
    content: str


class WebSearchProviderDto(BaseModel):
    provider_id: str
    display_name: str
    is_configured: bool
    last_test_status: Literal["untested", "valid", "failed"] | None = None
    last_test_error: str | None = None


class WebSearchCredentialDto(BaseModel):
    provider_id: str
    is_configured: bool
    last_test_status: Literal["untested", "valid", "failed"] | None = None
    last_test_error: str | None = None
    last_test_at: str | None = None


class SetWebSearchKeyDto(BaseModel):
    api_key: str
