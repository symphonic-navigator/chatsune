"""Tests for the shared transient-error retry helpers in ``backend._retry``.

Migrated from ``test_openrouter_http.py`` after the retry policy was
extracted from the OpenRouter adapter into a shared helper used by all
HTTP adapters and the integrations voice handler.
"""

from backend._retry import (
    RETRY_MAX_DELAY_SECONDS,
    compute_retry_delay,
    parse_retry_after,
)


def test_parse_retry_after_parses_numeric_header():
    assert parse_retry_after({"Retry-After": "3.5"}) == 3.5


def test_parse_retry_after_returns_none_for_missing_header():
    assert parse_retry_after({}) is None


def test_parse_retry_after_returns_none_for_http_date():
    assert parse_retry_after(
        {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"},
    ) is None


def test_parse_retry_after_clamps_to_max_delay():
    assert parse_retry_after({"Retry-After": "999"}) == RETRY_MAX_DELAY_SECONDS


def test_compute_retry_delay_uses_retry_after_when_present():
    # attempt is irrelevant when Retry-After is honoured
    assert compute_retry_delay(0, retry_after_seconds=2.0) == 2.0
    assert compute_retry_delay(3, retry_after_seconds=2.0) == 2.0


def test_compute_retry_delay_grows_exponentially_when_no_header():
    # base 1.0 * 2**2 = 4.0, with ±25% jitter → range [3.0, 5.0]
    delay = compute_retry_delay(2, retry_after_seconds=None)
    assert 3.0 <= delay <= 5.0
