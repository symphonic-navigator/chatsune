import pytest
from shared.topics import Topics
from backend.ws.event_bus import _topic_definition_for


def test_integration_secrets_topics_are_non_persistent():
    assert Topics.INTEGRATION_SECRETS_HYDRATED.persist is False
    assert Topics.INTEGRATION_SECRETS_CLEARED.persist is False


def test_lookup_finds_persist_flag():
    defn = _topic_definition_for("integration.secrets.hydrated")
    assert defn is not None
    assert defn.persist is False


def test_lookup_returns_none_for_unknown():
    assert _topic_definition_for("does.not.exist") is None
