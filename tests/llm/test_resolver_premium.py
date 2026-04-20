"""Premium Provider dispatch in the LLM resolver.

When ``model_unique_id`` begins with a reserved Premium Provider slug
(``xai``, ``mistral``, ``ollama_cloud``), :func:`resolve_for_model` must
route credential lookup through ``PremiumProviderService`` and synthesise
a :class:`ResolvedConnection` carrying the registry-fixed ``base_url``
and the user's decrypted ``api_key``. For any other slug, the function
falls back to the per-user Connection repository unchanged.
"""

import pytest

from backend.modules.llm import (
    LlmConnectionNotFoundError,
    _resolver as resolver_mod,
)
from backend.modules.llm._connections import ConnectionRepository
from backend.modules.llm._resolver import resolve_for_model
from backend.modules.providers._repository import (
    PremiumProviderAccountRepository,
)


@pytest.fixture
async def premium_db(mock_db, monkeypatch):
    """mock_db + premium_provider_accounts isolation + get_db patch."""
    await mock_db["premium_provider_accounts"].drop()
    monkeypatch.setattr(resolver_mod, "get_db", lambda: mock_db)
    yield mock_db
    await mock_db["premium_provider_accounts"].drop()


@pytest.fixture
async def user_with_xai_account(premium_db):
    repo = PremiumProviderAccountRepository(premium_db)
    await repo.create_indexes()
    await repo.upsert("user-xai", "xai", {"api_key": "xai-abc"})
    return "user-xai"


@pytest.fixture
async def user_with_ollama_cloud(premium_db):
    repo = PremiumProviderAccountRepository(premium_db)
    await repo.create_indexes()
    await repo.upsert("user-oc", "ollama_cloud", {"api_key": "oc-abc"})
    return "user-oc"


@pytest.fixture
async def user_with_local_ollama(premium_db):
    repo = ConnectionRepository(premium_db)
    await repo.create_indexes()
    doc = await repo.create(
        user_id="user-local",
        adapter_type="ollama_http",
        display_name="my-homeserver",
        slug="my-homeserver",
        config={"url": "http://192.168.0.10:11434"},
    )
    return ("user-local", doc["slug"])


async def test_resolves_premium_xai(user_with_xai_account):
    resolved = await resolve_for_model(user_with_xai_account, "xai:grok-3")
    assert resolved.adapter_type == "xai_http"
    assert resolved.slug == "xai"
    assert resolved.config["url"] == "https://api.x.ai/v1"
    assert resolved.config["api_key"] == "xai-abc"


async def test_resolves_premium_ollama_cloud(user_with_ollama_cloud):
    resolved = await resolve_for_model(
        user_with_ollama_cloud, "ollama_cloud:llama3.2",
    )
    assert resolved.adapter_type == "ollama_http"
    assert resolved.slug == "ollama_cloud"
    assert resolved.config["url"] == "https://ollama.com"
    assert resolved.config["api_key"] == "oc-abc"


async def test_missing_premium_account_raises(premium_db):
    with pytest.raises(LlmConnectionNotFoundError):
        await resolve_for_model("fresh-user", "xai:grok-3")


async def test_local_connection_still_resolved(user_with_local_ollama):
    user_id, conn_slug = user_with_local_ollama
    resolved = await resolve_for_model(user_id, f"{conn_slug}:llama3.2")
    assert resolved is not None
    assert resolved.slug == conn_slug
    assert resolved.config["url"] == "http://192.168.0.10:11434"


# ---------------------------------------------------------------------------
# End-to-end: the public LLM inference entry points must route premium
# model_unique_ids through resolve_for_model, otherwise the Premium dispatch
# added in Task 9 is never exercised for real inference.
# ---------------------------------------------------------------------------


class _FakeAdapter:
    """Minimal adapter stub capturing the ResolvedConnection handed to it."""

    last_connection = None
    last_request = None

    async def stream_completion(self, connection, request):
        type(self).last_connection = connection
        type(self).last_request = request
        from backend.modules.llm import StreamDone

        yield StreamDone(reason="stop")

    async def fetch_models(self, connection):
        type(self).last_connection = connection
        from shared.dtos.llm import ModelMetaDto

        return [
            ModelMetaDto(
                model_id="grok-3",
                display_name="Grok 3",
                context_window=131072,
                supports_vision=False,
                supports_reasoning=False,
                supports_tools=True,
            ),
        ]


async def test_stream_completion_routes_premium_xai(
    user_with_xai_account, monkeypatch,
):
    """Regression test for Task 9 follow-up:

    ``stream_completion(user_id, "xai:grok-3", ...)`` must resolve credentials
    through the Premium Provider service (via ``resolve_for_model``) and hand
    the adapter a ResolvedConnection whose ``config`` carries the registry-
    fixed ``https://api.x.ai/v1`` base URL + the decrypted premium ``api_key``.

    Before the rewire: ``stream_completion`` delegated to
    ``resolve_owned_connection_by_slug`` and raised
    ``LlmConnectionNotFoundError("xai")`` because no Connection doc has
    slug ``"xai"``.
    """
    from backend.modules.llm import stream_completion
    from backend.modules.llm import _registry as registry_mod
    from shared.dtos.inference import CompletionMessage, CompletionRequest, ContentPart

    # Stub the adapter lookup so we never go near an HTTP client.
    _FakeAdapter.last_connection = None
    _FakeAdapter.last_request = None
    monkeypatch.setitem(registry_mod.ADAPTER_REGISTRY, "xai_http", _FakeAdapter)

    request = CompletionRequest(
        model="grok-3",
        messages=[
            CompletionMessage(
                role="user",
                content=[ContentPart(type="text", text="hi")],
            ),
        ],
        reasoning_enabled=False,
        supports_reasoning=False,
    )

    events = []
    async for event in stream_completion(
        user_id=user_with_xai_account,
        model_unique_id="xai:grok-3",
        request=request,
    ):
        events.append(event)

    assert _FakeAdapter.last_connection is not None, (
        "adapter was never called — resolve_for_model did not route "
        "premium model_unique_ids through the Premium Provider resolver"
    )
    c = _FakeAdapter.last_connection
    assert c.adapter_type == "xai_http"
    assert c.slug == "xai"
    assert c.config["url"] == "https://api.x.ai/v1"
    assert c.config["api_key"] == "xai-abc"
    assert _FakeAdapter.last_request is request


async def test_stream_completion_calls_resolve_for_model(
    user_with_xai_account, monkeypatch,
):
    """Guard: the public stream_completion entry point must delegate
    connection resolution to ``resolve_for_model`` so premium dispatch is
    exercised. This test lets us detect a regression if someone reverts
    the call site to ``resolve_owned_connection_by_slug``.
    """
    from backend.modules.llm import stream_completion
    from backend.modules.llm import _registry as registry_mod
    from shared.dtos.inference import CompletionMessage, CompletionRequest, ContentPart

    monkeypatch.setitem(registry_mod.ADAPTER_REGISTRY, "xai_http", _FakeAdapter)

    resolve_calls: list[tuple[str, str]] = []

    original_resolve = resolver_mod.resolve_for_model

    async def spy(user_id, model_unique_id):
        resolve_calls.append((user_id, model_unique_id))
        return await original_resolve(user_id, model_unique_id)

    # Patch the symbol in the llm package where stream_completion imports it.
    import backend.modules.llm as llm_pkg

    monkeypatch.setattr(llm_pkg, "resolve_for_model", spy, raising=False)
    monkeypatch.setattr(resolver_mod, "resolve_for_model", spy)

    request = CompletionRequest(
        model="grok-3",
        messages=[
            CompletionMessage(
                role="user",
                content=[ContentPart(type="text", text="hi")],
            ),
        ],
        reasoning_enabled=False,
        supports_reasoning=False,
    )

    async for _ in stream_completion(
        user_id=user_with_xai_account,
        model_unique_id="xai:grok-3",
        request=request,
    ):
        pass

    assert resolve_calls == [(user_with_xai_account, "xai:grok-3")], (
        f"stream_completion did not call resolve_for_model; calls={resolve_calls}"
    )
