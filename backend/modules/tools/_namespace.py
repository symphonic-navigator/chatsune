"""MCP gateway namespace normalisation and validation."""

from __future__ import annotations

import re

_BUILTIN_TOOL_NAMES = frozenset({
    "web_search", "web_fetch", "knowledge_search",
    "create_artefact", "update_artefact", "read_artefact", "list_artefacts",
    "calculate_js", "write_journal_entry",
})


def normalise_namespace(name: str) -> str:
    """Normalise a gateway name into a valid namespace prefix.

    Lowercase, replace non-alphanumeric with underscore, collapse runs,
    strip leading/trailing underscores.
    """
    result = name.lower().strip()
    result = re.sub(r"[^a-z0-9]", "_", result)
    result = re.sub(r"_+", "_", result)
    result = result.strip("_")
    return result


def validate_namespace(
    name: str,
    existing_namespaces: set[str],
) -> str | None:
    """Return an error message if the namespace is invalid, or None if OK."""
    normalised = normalise_namespace(name) if name else ""
    if not normalised:
        return "Gateway name must not be empty."
    # Check the raw name so that "my__server" is caught even though
    # normalise_namespace would collapse the double underscore.
    if "__" in name:
        return "Gateway name must not contain double underscores."
    if normalised in existing_namespaces:
        return f"Namespace '{normalised}' is already in use."
    if normalised in _BUILTIN_TOOL_NAMES:
        return f"'{normalised}' conflicts with a built-in tool name."
    return None
