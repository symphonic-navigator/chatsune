"""Premium-provider API-key probing helpers.

The explicit ``/api/providers/accounts/{provider_id}/test`` endpoint and the
post-login migration assist use the same probe path so persisted
``last_test_*`` fields and WebSocket events stay consistent.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import httpx

from backend.database import get_db
from backend.modules.providers._registry import get as get_definition
from backend.modules.providers._repository import (
    PremiumProviderAccountRepository,
)
from backend.ws.event_bus import get_event_bus
from shared.events.providers import PremiumProviderAccountTestedEvent
from shared.topics import Topics

_log = logging.getLogger(__name__)

AUTO_TEST_PROVIDER_IDS = frozenset({"xai", "mistral", "ollama_cloud"})
_TESTED_STATUSES = frozenset({"ok", "error"})


class PremiumProviderProbeError(Exception):
    """Base class for expected probe precondition failures."""


class PremiumProviderProbeUnknownProvider(PremiumProviderProbeError):
    """Provider id is not registered."""


class PremiumProviderProbeAccountMissing(PremiumProviderProbeError):
    """User has no account for the requested provider."""


class PremiumProviderProbeSecretMissing(PremiumProviderProbeError):
    """The account exists but has no stored API key."""


@dataclass(frozen=True)
class PremiumProviderProbeResult:
    status: Literal["ok", "error"]
    error: str | None


async def probe_provider_account(
    user_id: str,
    provider_id: str,
    *,
    repo: PremiumProviderAccountRepository | None = None,
    publish_event: bool = True,
) -> PremiumProviderProbeResult:
    """Probe one configured Premium Provider Account and persist the result."""
    defn = get_definition(provider_id)
    if defn is None:
        raise PremiumProviderProbeUnknownProvider(provider_id)

    account_repo = repo or PremiumProviderAccountRepository(get_db())
    doc = await account_repo.find(user_id, provider_id)
    if doc is None:
        raise PremiumProviderProbeAccountMissing(provider_id)

    api_key = account_repo.get_decrypted_secret(doc, "api_key")
    if api_key is None:
        raise PremiumProviderProbeSecretMissing(provider_id)

    probe_status: Literal["ok", "error"] = "error"
    probe_error: str | None = None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.request(
                defn.probe_method,
                defn.probe_url,
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if resp.status_code == 200:
            probe_status = "ok"
        elif resp.status_code in (401, 403):
            probe_error = f"API key rejected by {defn.display_name}"
        else:
            probe_error = f"{defn.display_name} returned {resp.status_code}"
    except Exception as exc:  # noqa: BLE001 - surfaced as persisted status
        probe_error = str(exc) or exc.__class__.__name__

    await account_repo.update_test_status(
        user_id, provider_id,
        status=probe_status, error=probe_error,
    )

    if publish_event:
        await get_event_bus().publish(
            Topics.PREMIUM_PROVIDER_ACCOUNT_TESTED,
            PremiumProviderAccountTestedEvent(
                provider_id=provider_id,
                status=probe_status,
                error=probe_error,
            ),
            target_user_ids=[user_id],
        )

    _log.info(
        "premium probe provider=%s user=%s status=%s",
        provider_id, user_id, probe_status,
    )
    return PremiumProviderProbeResult(status=probe_status, error=probe_error)


async def auto_test_untested_provider_accounts(user_id: str) -> None:
    """Best-effort post-login probe for migrated Premium Provider Accounts.

    Only xAI, Mistral, and Ollama Cloud are in scope. Accounts with a stored
    ``last_test_status`` are left alone so ordinary logins do not keep probing
    external APIs.
    """
    repo = PremiumProviderAccountRepository(get_db())
    try:
        docs = await repo.list_for_user(user_id)
    except Exception:  # noqa: BLE001 - login must never fail because of this
        _log.exception("premium auto-test failed to list accounts user=%s", user_id)
        return

    for doc in docs:
        provider_id = doc.get("provider_id")
        if provider_id not in AUTO_TEST_PROVIDER_IDS:
            continue
        if doc.get("last_test_status") in _TESTED_STATUSES:
            continue
        try:
            await probe_provider_account(user_id, provider_id, repo=repo)
        except PremiumProviderProbeSecretMissing:
            _log.info(
                "premium auto-test skipped provider=%s user=%s: no api key",
                provider_id, user_id,
            )
        except PremiumProviderProbeError as exc:
            _log.warning(
                "premium auto-test skipped provider=%s user=%s: %s",
                provider_id, user_id, exc.__class__.__name__,
            )
        except Exception:  # noqa: BLE001 - best-effort background task
            _log.exception(
                "premium auto-test failed provider=%s user=%s",
                provider_id, user_id,
            )
