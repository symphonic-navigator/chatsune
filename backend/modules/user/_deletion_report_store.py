"""Short-lived (15-minute TTL) store for user deletion reports.

After a user self-deletes they are logged out immediately — but they
still need to see the transparent receipt of what was purged. We store
the report in Redis under a random slug and redirect the now-logged-out
client to a public confirmation page that fetches the report by slug.

Design notes (see INSIGHTS.md):

- Slug is 24 bytes of url-safe randomness from ``secrets.token_urlsafe``.
  Non-guessable. No PII in the key.
- TTL is 15 minutes — enough for the user to read, copy, and close.
- Value is the JSON-serialised ``DeletionReportDto``. After the TTL
  elapses Redis drops the key automatically, so there is no cleanup job.
- PII contained: the report has the deleted user's ``target_name``
  (username) but no access token, password, or identifier that maps to
  anything still-live in the system. After deletion the user_id is
  worthless.
"""

from __future__ import annotations

import logging
import secrets

from redis.asyncio import Redis

from shared.dtos.deletion import DeletionReportDto

_log = logging.getLogger(__name__)

_KEY_PREFIX = "deletion_report:"
_TTL_SECONDS = 15 * 60  # 15 minutes


class DeletionReportStore:
    """Redis-backed, TTL-bounded store for deletion reports.

    Keys are of the form ``deletion_report:{slug}`` where ``slug`` is a
    url-safe token of ``secrets.token_urlsafe(24)``. The slug itself is
    the capability — anyone holding it can read the report — but the
    entire key is gone after 15 minutes.
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def store(self, report: DeletionReportDto) -> str:
        """Store ``report`` under a freshly generated slug. Returns the slug.

        The TTL is fixed at 15 minutes; the key will vanish automatically
        afterwards with no cleanup job needed.
        """
        slug = secrets.token_urlsafe(24)
        key = f"{_KEY_PREFIX}{slug}"
        await self._redis.setex(key, _TTL_SECONDS, report.model_dump_json())
        _log.info(
            "deletion_report.stored slug_len=%d target_type=%s ttl=%d",
            len(slug), report.target_type, _TTL_SECONDS,
        )
        return slug

    async def fetch(self, slug: str) -> DeletionReportDto | None:
        """Return the stored report, or None if the slug is unknown / expired."""
        key = f"{_KEY_PREFIX}{slug}"
        data = await self._redis.get(key)
        if data is None:
            return None
        try:
            return DeletionReportDto.model_validate_json(data)
        except Exception:
            _log.warning(
                "deletion_report.fetch_parse_failed slug_len=%d",
                len(slug), exc_info=True,
            )
            return None
