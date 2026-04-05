from pydantic import BaseModel


class WebSearchResultDto(BaseModel):
    title: str
    url: str
    snippet: str


class WebFetchResultDto(BaseModel):
    url: str
    title: str | None = None
    content: str
