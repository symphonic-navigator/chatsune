from backend.modules.integrations._registry import get
from shared.dtos.integrations import IntegrationCapability


def test_lovense_is_tool_provider():
    defn = get("lovense")
    assert defn is not None
    assert IntegrationCapability.TOOL_PROVIDER in defn.capabilities


def test_lovense_has_no_persona_config_fields():
    defn = get("lovense")
    assert defn.persona_config_fields == []
