"""Abstract base for upstream inference adapters (connections refactor)."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from fastapi import APIRouter

from backend.modules.llm._adapters._events import ProviderStreamEvent
from backend.modules.llm._adapters._types import (
    AdapterTemplate,
    ConfigFieldHint,
    ResolvedConnection,
)
from shared.dtos.inference import CompletionRequest
from shared.dtos.llm import ModelMetaDto


class BaseAdapter(ABC):
    """Stateless abstract base for LLM upstream adapters.

    One subclass per backend type (e.g. `OllamaHttpAdapter`). Instances are
    cheap — the system instantiates one per request and hands it a
    `ResolvedConnection` containing the merged, decrypted config for the
    user's chosen Connection.

    Required class attributes:

    - `adapter_type`  — stable identifier used in the adapter registry and in
                        `Connection.adapter_type` documents (e.g. `"ollama_http"`).
    - `display_name`  — human label shown in the "add Connection" wizard.
    - `view_id`       — key the frontend uses to resolve the adapter's React
                        view from its `AdapterViewRegistry`.
    - `secret_fields` — names of `config` keys that must be encrypted at rest.

    Required methods:

    - `fetch_models(connection)` — return the list of models this Connection
                                   can serve. Called on cache miss; result is
                                   cached per-Connection in Redis for 30 min.
    - `stream_completion(connection, request)` — yield provider stream events
                                                 for the given request. Must
                                                 yield a terminal event
                                                 (`StreamDone`, `StreamError`,
                                                 `StreamAborted`, or
                                                 `StreamRefused`) exactly once.

    Optional methods:

    - `templates()`      — wizard presets.
    - `config_schema()`  — lightweight form-rendering hints.
    - `router()`         — adapter-specific FastAPI sub-router.
    """

    # Subclasses MUST override
    adapter_type: str = ""
    display_name: str = ""
    view_id: str = ""
    secret_fields: frozenset[str] = frozenset()

    @classmethod
    def templates(cls) -> list[AdapterTemplate]:
        return []

    @classmethod
    def config_schema(cls) -> list[ConfigFieldHint]:
        return []

    @classmethod
    def router(cls) -> APIRouter | None:
        """Return an adapter-specific FastAPI sub-router, or None.

        The router is mounted at `/api/llm/connections/{connection_id}/adapter/`
        and runs AFTER the generic connection resolver dependency. Sub-handlers
        should accept `c: ResolvedConnection = Depends(resolve_connection_for_user)`
        and never re-authenticate or re-authorise — that is the resolver's job.

        Recommended endpoints:

        - `POST /test`      — validate that the configured upstream is reachable
                              and credentials (if any) are accepted. Returns
                              `{"valid": bool, "error": str | None}`.
        - `GET  /diagnostics` — optional, adapter-specific health info (e.g.
                              currently loaded models, available tags). Free-form
                              JSON response.

        Adapters may add further endpoints (e.g. `POST /pair` for pairing-based
        transports) but should avoid endpoints that duplicate generic CRUD.
        """
        return None

    @abstractmethod
    async def fetch_models(
        self, connection: ResolvedConnection,
    ) -> list[ModelMetaDto]:
        ...

    @abstractmethod
    def stream_completion(
        self, connection: ResolvedConnection, request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        ...
