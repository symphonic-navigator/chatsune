from abc import ABC, abstractmethod

from shared.dtos.websearch import WebFetchResultDto, WebSearchResultDto


class BaseSearchAdapter(ABC):
    """Abstract base for all upstream web-search provider adapters."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    @abstractmethod
    async def search(
        self,
        api_key: str,
        query: str,
        max_results: int = 5,
    ) -> list[WebSearchResultDto]:
        """Run a web search and return result summaries."""
        ...

    @abstractmethod
    async def fetch(
        self,
        api_key: str,
        url: str,
    ) -> WebFetchResultDto:
        """Fetch the full content of a web page."""
        ...
