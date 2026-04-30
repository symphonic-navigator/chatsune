"""Unit tests for ``default_enabled`` semantics in ``effective_enabled_map``.

The map honours four cases for unlinked integrations:

1. No config doc + ``default_enabled=True``  -> True
2. No config doc + ``default_enabled=False`` -> False
3. Explicit ``enabled=False`` overrides ``default_enabled=True``
4. Explicit ``enabled=True`` with ``default_enabled=False`` -> True

These rules let us ship "default-on" extensions (e.g. screen-effects) as a
code property without backfilling existing user documents.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from backend.modules.integrations import effective_enabled_map
from backend.modules.integrations._models import IntegrationDefinition


def _make_defn(iid: str, *, default_enabled: bool) -> IntegrationDefinition:
    return IntegrationDefinition(
        id=iid,
        display_name=iid,
        description="",
        icon="",
        execution_mode="frontend",
        config_fields=[],
        default_enabled=default_enabled,
    )


async def test_no_config_doc_default_enabled_true_returns_true() -> None:
    defn = _make_defn("screen_fx", default_enabled=True)
    with patch(
        "backend.modules.integrations._registry.get_all",
        return_value={"screen_fx": defn},
    ), patch(
        "backend.modules.integrations.IntegrationRepository.get_user_configs",
        new=AsyncMock(return_value=[]),
    ), patch(
        "backend.modules.providers.PremiumProviderService.has_account",
        new=AsyncMock(return_value=False),
    ), patch("backend.database.get_db", return_value=MagicMock()):
        result = await effective_enabled_map("user-1")

    assert result == {"screen_fx": True}


async def test_no_config_doc_default_enabled_false_returns_false() -> None:
    defn = _make_defn("lovense", default_enabled=False)
    with patch(
        "backend.modules.integrations._registry.get_all",
        return_value={"lovense": defn},
    ), patch(
        "backend.modules.integrations.IntegrationRepository.get_user_configs",
        new=AsyncMock(return_value=[]),
    ), patch(
        "backend.modules.providers.PremiumProviderService.has_account",
        new=AsyncMock(return_value=False),
    ), patch("backend.database.get_db", return_value=MagicMock()):
        result = await effective_enabled_map("user-1")

    assert result == {"lovense": False}


async def test_explicit_disabled_overrides_default_enabled_true() -> None:
    defn = _make_defn("screen_fx", default_enabled=True)
    cfg = {"integration_id": "screen_fx", "enabled": False}
    with patch(
        "backend.modules.integrations._registry.get_all",
        return_value={"screen_fx": defn},
    ), patch(
        "backend.modules.integrations.IntegrationRepository.get_user_configs",
        new=AsyncMock(return_value=[cfg]),
    ), patch(
        "backend.modules.providers.PremiumProviderService.has_account",
        new=AsyncMock(return_value=False),
    ), patch("backend.database.get_db", return_value=MagicMock()):
        result = await effective_enabled_map("user-1")

    assert result == {"screen_fx": False}


async def test_explicit_enabled_with_default_disabled_returns_true() -> None:
    defn = _make_defn("lovense", default_enabled=False)
    cfg = {"integration_id": "lovense", "enabled": True}
    with patch(
        "backend.modules.integrations._registry.get_all",
        return_value={"lovense": defn},
    ), patch(
        "backend.modules.integrations.IntegrationRepository.get_user_configs",
        new=AsyncMock(return_value=[cfg]),
    ), patch(
        "backend.modules.providers.PremiumProviderService.has_account",
        new=AsyncMock(return_value=False),
    ), patch("backend.database.get_db", return_value=MagicMock()):
        result = await effective_enabled_map("user-1")

    assert result == {"lovense": True}
