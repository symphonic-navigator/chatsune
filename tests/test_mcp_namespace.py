"""Tests for MCP namespace normalisation."""

from backend.modules.tools._namespace import normalise_namespace, validate_namespace


class TestNormaliseNamespace:
    def test_lowercase(self):
        assert normalise_namespace("MyServer") == "myserver"

    def test_special_chars_to_underscore(self):
        assert normalise_namespace("my-server.v2") == "my_server_v2"

    def test_collapse_multiple_underscores(self):
        assert normalise_namespace("my--server") == "my_server"

    def test_strip_leading_trailing_underscores(self):
        assert normalise_namespace("_server_") == "server"

    def test_already_clean(self):
        assert normalise_namespace("homelab") == "homelab"

    def test_spaces(self):
        assert normalise_namespace("my server") == "my_server"


class TestValidateNamespace:
    def test_valid(self):
        assert validate_namespace("homelab", existing_namespaces=set()) is None

    def test_empty_name(self):
        err = validate_namespace("", existing_namespaces=set())
        assert err is not None

    def test_duplicate(self):
        err = validate_namespace("homelab", existing_namespaces={"homelab"})
        assert err is not None

    def test_collides_with_builtin(self):
        err = validate_namespace("web_search", existing_namespaces=set())
        assert err is not None

    def test_contains_double_underscore(self):
        err = validate_namespace("my__server", existing_namespaces=set())
        assert err is not None
