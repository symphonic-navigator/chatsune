from shared.events.providers import (
    PremiumProviderAccountUpsertedEvent,
    PremiumProviderAccountDeletedEvent,
    PremiumProviderAccountTestedEvent,
)
from shared.topics import Topics


def test_topics_present():
    assert Topics.PREMIUM_PROVIDER_ACCOUNT_UPSERTED == "providers.account.upserted"
    assert Topics.PREMIUM_PROVIDER_ACCOUNT_DELETED == "providers.account.deleted"
    assert Topics.PREMIUM_PROVIDER_ACCOUNT_TESTED == "providers.account.tested"


def test_upserted_event_serialises():
    evt = PremiumProviderAccountUpsertedEvent(provider_id="xai")
    assert evt.provider_id == "xai"


def test_tested_event_carries_status():
    evt = PremiumProviderAccountTestedEvent(
        provider_id="xai", status="ok", error=None,
    )
    assert evt.status == "ok"
    assert evt.error is None
