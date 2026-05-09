from backend.modules.llm._adapters._base import BaseAdapter


def test_base_adapter_capability_hint_default_returns_none():
    """Default returns None — fall through to universal default capabilities.
    Adapters that hand-curate models override this to return a CapabilityHint."""
    class _Adapter(BaseAdapter):
        async def fetch_models(self, connection): ...
        def stream_completion(self, connection, request): ...

    a = _Adapter.__new__(_Adapter)
    assert a.capability_hint("anything") is None
