import httpx

from backend.modules.websearch._adapters._base import BaseSearchAdapter
from shared.dtos.websearch import WebFetchResultDto, WebSearchResultDto

_MAX_FETCH_CONTENT_LENGTH = 8000
_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)


class OllamaCloudSearchAdapter(BaseSearchAdapter):
    """Web search and fetch via Ollama Cloud's API."""

    async def search(
        self,
        api_key: str,
        query: str,
        max_results: int = 5,
    ) -> list[WebSearchResultDto]:
        max_results = max(1, min(max_results, 10))

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{self.base_url}/api/web_search",
                json={"query": query, "max_results": max_results},
                headers={"Authorization": f"Bearer {api_key}"},
            )
            resp.raise_for_status()

        data = resp.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        if not isinstance(results, list):
            results = []

        return [
            WebSearchResultDto(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("snippet", r.get("description", "")),
            )
            for r in results
        ]

    async def fetch(
        self,
        api_key: str,
        url: str,
    ) -> WebFetchResultDto:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{self.base_url}/api/web_fetch",
                json={"url": url},
                headers={"Authorization": f"Bearer {api_key}"},
            )
            resp.raise_for_status()

        data = resp.json()
        content = data.get("content", "")
        title = data.get("title")

        if len(content) > _MAX_FETCH_CONTENT_LENGTH:
            content = content[:_MAX_FETCH_CONTENT_LENGTH] + "\n\n[Content truncated]"

        return WebFetchResultDto(url=url, title=title, content=content)
