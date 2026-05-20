"""Tests for _normalise_mcp_url — base URL vs full URL handling.

Accepts both historical Chatsune base-URL inputs (auto-append ``/mcp``)
and the full-URL form used by every other MCP client (taken verbatim).
"""

import pytest

from backend.modules.tools._mcp_executor import _normalise_mcp_url


@pytest.mark.parametrize(
    "given,expected",
    [
        # Base URL — no path, append /mcp (historical Chatsune behaviour).
        ("https://example.com", "https://example.com/mcp"),
        # Base URL with trailing slash — same as above after rstrip.
        ("https://example.com/", "https://example.com/mcp"),
        # Full URL with the conventional /mcp path — taken verbatim.
        ("https://example.com/mcp", "https://example.com/mcp"),
        # Full URL with a non-default path — also taken verbatim.
        ("https://example.com/api/mcp", "https://example.com/api/mcp"),
        # Full URL pointing at a streamable-http endpoint — verbatim.
        ("https://example.com/streamable-http", "https://example.com/streamable-http"),
        # Trailing slash on a non-root path — rstrip first, then verbatim.
        ("https://example.com/mcp/", "https://example.com/mcp"),
    ],
)
def test_normalise_mcp_url(given: str, expected: str) -> None:
    assert _normalise_mcp_url(given) == expected
