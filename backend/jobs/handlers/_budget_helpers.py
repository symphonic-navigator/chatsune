"""Shared helpers for daily-token-budget enforcement inside job handlers.

Background jobs spend tokens on behalf of the user and therefore must be
bounded by the SG-002 daily budget. The consumer layer only knows about
job execution, not about the tokens a particular handler spent, so each
handler is responsible for:

  1. Reserving an estimated input-token cost before calling the LLM via
     :func:`check_and_reserve_budget`. If the user's daily budget would
     be exceeded the call raises :class:`UnrecoverableJobError`, which
     tells the consumer to skip the retry chain — re-running the same
     job later today would just hit the same cap.

  2. Recording the real spend after a successful call via
     :func:`record_handler_tokens`. Failures inside the recording path
     are deliberately swallowed and logged — the LLM call has already
     succeeded and losing a single budget update must not break the
     handler.

Prefer the adapter's real token counts from :class:`StreamDone` when
available; otherwise fall back to the conservative estimator.
"""
from __future__ import annotations

import structlog

from redis.asyncio import Redis

from backend.jobs._errors import UnrecoverableJobError
from backend.modules.llm._token_estimate import estimate_tokens
from backend.modules.safeguards import SafeguardConfig
from backend.modules.safeguards._budget import (
    BudgetExceededError,
    check_budget,
    record_tokens,
)

_log = structlog.get_logger(__name__)


async def check_and_reserve_budget(
    redis: Redis,
    user_id: str,
    prompt_text: str,
) -> int:
    """Ensure the user has budget headroom for the estimated prompt cost.

    Returns the estimated input-token count so callers can reuse it for
    post-success accounting without re-estimating.
    """
    sg_config = SafeguardConfig.from_env()
    estimated_input = estimate_tokens(prompt_text)
    try:
        await check_budget(
            redis,
            sg_config,
            user_id=user_id,
            tokens_to_reserve=estimated_input,
        )
    except BudgetExceededError as exc:
        # Retrying today will not help — skip the retry chain entirely.
        raise UnrecoverableJobError(str(exc)) from exc
    return estimated_input


async def record_handler_tokens(
    redis: Redis,
    user_id: str,
    prompt_text: str,
    output_text: str,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> None:
    """Record the real token spend for a completed handler LLM call.

    When the adapter surfaced real counts via ``StreamDone.input_tokens``
    / ``output_tokens`` we prefer those; otherwise we fall back to the
    conservative estimator. Failures here are non-fatal: the LLM call
    already succeeded and the handler must not die because of a Redis
    hiccup in the accounting path.
    """
    sg_config = SafeguardConfig.from_env()
    if input_tokens is not None and output_tokens is not None:
        total = int(input_tokens) + int(output_tokens)
    else:
        total = estimate_tokens(prompt_text) + estimate_tokens(output_text)
    try:
        await record_tokens(
            redis,
            sg_config,
            user_id=user_id,
            tokens=total,
        )
    except Exception as exc:  # noqa: BLE001 — deliberately tolerant
        _log.warning(
            "budget.record_tokens_failed user=%s tokens=%d error=%s",
            user_id, total, exc,
        )
