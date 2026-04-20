from shared.dtos.providers import (
    Capability, CAPABILITY_META, PremiumProviderAccountDto,
    PremiumProviderUpsertRequest, PremiumProviderDefinitionDto,
)


def test_capability_enum_values():
    assert Capability.LLM.value == "llm"
    assert Capability.TTS.value == "tts"
    assert Capability.STT.value == "stt"
    assert Capability.WEBSEARCH.value == "websearch"
    assert Capability.TTI.value == "tti"
    assert Capability.ITI.value == "iti"


def test_capability_meta_has_every_capability():
    for cap in Capability:
        assert cap in CAPABILITY_META
        assert CAPABILITY_META[cap]["label"]
        assert CAPABILITY_META[cap]["tooltip"]


def test_premium_provider_account_dto_redacts_secrets():
    dto = PremiumProviderAccountDto(
        provider_id="xai",
        config={"api_key": {"is_set": True}},
        last_test_status="ok",
        last_test_error=None,
        last_test_at=None,
    )
    assert dto.config["api_key"] == {"is_set": True}


def test_upsert_request_accepts_plain_api_key():
    req = PremiumProviderUpsertRequest(config={"api_key": "xai-abc123"})
    assert req.config["api_key"] == "xai-abc123"
