import backend.modules.tools._registry as registry_mod
from backend.modules.tools import get_active_definitions, get_all_groups
from backend.modules.tools._registry import get_groups


def _reset_registry_cache() -> None:
    """Force the lazy registry to rebuild — other tests may have warmed
    the cache without the journal group visible, and the module cache
    also persists across tests within the same pytest session."""
    registry_mod._groups = None


def test_journal_group_is_registered():
    _reset_registry_cache()
    groups = get_groups()
    assert "journal" in groups
    group = groups["journal"]
    assert group.side == "server"
    assert group.toggleable is True
    assert group.tool_names == ["write_journal_entry"]
    assert group.executor is not None
    assert len(group.definitions) == 1
    definition = group.definitions[0]
    assert definition.name == "write_journal_entry"
    params = definition.parameters
    assert params["required"] == ["content", "category"]
    assert set(params["properties"]["category"]["enum"]) == {
        "preference", "fact", "relationship", "value",
        "insight", "projects", "creative",
    }


def test_journal_tool_is_in_active_definitions_by_default():
    _reset_registry_cache()
    active = get_active_definitions()
    names = {d.name for d in active}
    assert "write_journal_entry" in names


def test_journal_group_is_in_group_dtos():
    _reset_registry_cache()
    dtos = get_all_groups()
    ids = {g.id for g in dtos}
    assert "journal" in ids
