"""Shared retry helper for transient upstream failures (HTTP 429 / 503).

Used by both the LLM module's HTTP adapters
(``backend.modules.llm._adapters.*``) and the integrations module's voice
handler (``backend.modules.integrations._handlers``). Sits at the
``backend`` package root — alongside ``_logging.py`` — so neither module
has to reach into the other's internals to share the retry policy.

Behaviour
---------

* Up to ``MAX_RETRY_ATTEMPTS`` retries after the initial failure (so at
  most ``MAX_RETRY_ATTEMPTS + 1`` total attempts).
* Exponential back-off ``base * 2**attempt`` with ``±RETRY_JITTER_FRACTION``
  jitter, hard-capped at ``RETRY_MAX_DELAY_SECONDS``.
* Honours an upstream ``Retry-After`` header in seconds-form when present
  (capped at ``RETRY_MAX_DELAY_SECONDS``). HTTP-date form is rare on the
  providers we hit and falls back to the exponential delay.
* No third-party dependency — pure ``asyncio.sleep`` + ``random.uniform``.

Anti-spam: callers log ONE INFO line per retry decision, including
attempt number, chosen delay, and ``correlation_id`` when available.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable, Mapping
from typing import TypeVar

# Total worst-case back-off across four retries is roughly
# 1 + 2 + 4 + 8 = 15s, with each step capped at RETRY_MAX_DELAY_SECONDS.
MAX_RETRY_ATTEMPTS = 4
RETRY_BASE_DELAY_SECONDS = 1.0
RETRY_MAX_DELAY_SECONDS = 16.0
RETRY_JITTER_FRACTION = 0.25

# HTTP statuses that warrant transient-error retry.
#   429 — upstream rate-limit (account-wide or per-route)
#   503 — upstream service unavailable (most frequent failure on
#         Nano-GPT in particular, also seen sporadically on the
#         other OpenAI-compatible providers)
_RETRIABLE_STATUSES: frozenset[int] = frozenset({429, 503})


T = TypeVar("T")


def should_retry_status(status_code: int) -> bool:
    """Return True if ``status_code`` should trigger a transient retry."""
    return status_code in _RETRIABLE_STATUSES


def parse_retry_after(headers: Mapping[str, str]) -> float | None:
    """Parse a ``Retry-After`` header (seconds form) into a float.

    Returns ``None`` for missing, malformed, or negative values, and for
    the HTTP-date form (rare on the providers we hit; the caller falls
    back to the exponential delay). The result is hard-capped at
    ``RETRY_MAX_DELAY_SECONDS`` to avoid honouring extreme values.
    """
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if raw is None:
        return None
    try:
        seconds = float(raw.strip())
    except (ValueError, AttributeError):
        return None
    if seconds < 0:
        return None
    return min(seconds, RETRY_MAX_DELAY_SECONDS)


def compute_retry_delay(
    attempt: int,
    retry_after_seconds: float | None = None,
) -> float:
    """Pick the sleep duration before the next retry.

    Honours ``retry_after_seconds`` if provided (capped at
    ``RETRY_MAX_DELAY_SECONDS``); otherwise ``base * 2**attempt`` with
    ±jitter, also capped. ``attempt`` is 0-indexed: 0 for the first
    retry after the initial failure.
    """
    if retry_after_seconds is not None:
        return min(max(0.0, retry_after_seconds), RETRY_MAX_DELAY_SECONDS)
    base = RETRY_BASE_DELAY_SECONDS * (2 ** attempt)
    jitter_range = base * RETRY_JITTER_FRACTION
    delay = base + random.uniform(-jitter_range, jitter_range)
    return max(0.1, min(delay, RETRY_MAX_DELAY_SECONDS))


def log_retry(
    logger: logging.Logger,
    *,
    operation: str,
    attempt: int,
    delay_seconds: float,
    status_code: int | None = None,
    correlation_id: str | None = None,
    extra: Mapping[str, object] | None = None,
) -> None:
    """Emit one structured INFO line per retry decision.

    Format mirrors the existing key=value style used elsewhere in the
    codebase so Grafana / Loki can filter on ``operation`` and
    ``correlation_id``. One log line per retry — never per attempt loop
    iteration — to avoid spam.
    """
    parts: list[str] = [
        f"attempt={attempt + 1}/{MAX_RETRY_ATTEMPTS}",
        f"delay={delay_seconds:.2f}s",
    ]
    if status_code is not None:
        parts.append(f"status={status_code}")
    if correlation_id is not None:
        parts.append(f"correlation_id={correlation_id!r}")
    if extra:
        for key, value in extra.items():
            parts.append(f"{key}={value!r}")
    logger.info("%s.transient_retry %s", operation, " ".join(parts))


async def execute_with_retry(
    operation: Callable[[], Awaitable[T]],
    *,
    is_retriable: Callable[[BaseException], bool],
    extract_retry_after: Callable[[BaseException], float | None] | None = None,
    operation_name: str = "operation",
    logger: logging.Logger | None = None,
    correlation_id: str | None = None,
) -> T:
    """Run ``operation`` with exponential-backoff retry on transient errors.

    The call site decides what counts as transient via ``is_retriable``;
    after ``MAX_RETRY_ATTEMPTS`` exhausted retries the original
    exception bubbles up unchanged (callers do not need to invent new
    exception types).

    Suitable for "single result" calls — e.g. voice TTS / STT / list-
    voices. The streaming LLM adapters use the lower-level helpers
    (:func:`should_retry_status`, :func:`compute_retry_delay`) directly
    because their retry decision sits inside an ``async with
    client.stream(...)`` block where a generic wrapper would obscure
    the control flow.
    """
    last_exc: BaseException | None = None
    for attempt in range(MAX_RETRY_ATTEMPTS + 1):
        try:
            return await operation()
        except BaseException as exc:  # noqa: BLE001 — retriable predicate decides
            if not is_retriable(exc) or attempt >= MAX_RETRY_ATTEMPTS:
                raise
            last_exc = exc
            retry_after: float | None = None
            if extract_retry_after is not None:
                try:
                    retry_after = extract_retry_after(exc)
                except Exception:  # noqa: BLE001 — never let the helper itself crash
                    retry_after = None
            delay = compute_retry_delay(attempt, retry_after)
            if logger is not None:
                log_retry(
                    logger,
                    operation=operation_name,
                    attempt=attempt,
                    delay_seconds=delay,
                    correlation_id=correlation_id,
                    extra={"error": type(exc).__name__},
                )
            await asyncio.sleep(delay)
    # Unreachable: the loop either returns, raises inside the body, or
    # raises here on the final attempt. Kept for type-checker peace.
    assert last_exc is not None
    raise last_exc
