from backend.modules.integrations._registry import _registry  # noqa: F401 - force registration
from backend.modules.integrations import (
    get_integration,
    VOICE_EXPRESSION_INLINE_TAGS as INLINE_TAGS,
    VOICE_EXPRESSION_WRAPPING_TAGS as WRAPPING_TAGS,
    build_voice_expression_prompt_extension as build_system_prompt_extension,
)
from shared.dtos.integrations import IntegrationCapability


def test_xai_voice_advertises_expressive_markup_capability() -> None:
    defn = get_integration("xai_voice")
    assert defn is not None
    assert IntegrationCapability.TTS_EXPRESSIVE_MARKUP in defn.capabilities


def test_mistral_voice_does_not_advertise_expressive_markup() -> None:
    defn = get_integration("mistral_voice")
    assert defn is not None
    assert IntegrationCapability.TTS_EXPRESSIVE_MARKUP not in defn.capabilities


def test_inline_tags_cover_xai_vocabulary() -> None:
    expected = {
        "pause", "long-pause", "hum-tune",
        "laugh", "chuckle", "giggle", "cry",
        "tsk", "tongue-click", "lip-smack",
        "breath", "inhale", "exhale", "sigh",
    }
    assert set(INLINE_TAGS) == expected


def test_wrapping_tags_cover_xai_vocabulary() -> None:
    expected = {
        "soft", "whisper", "loud", "build-intensity", "decrease-intensity",
        "higher-pitch", "lower-pitch", "slow", "fast",
        "sing-song", "singing", "laugh-speak", "emphasis",
    }
    assert set(WRAPPING_TAGS) == expected


def test_prompt_extension_mentions_every_tag() -> None:
    prompt = build_system_prompt_extension()
    for tag in INLINE_TAGS:
        assert f"[{tag}]" in prompt, f"inline tag {tag!r} missing from prompt"
    for tag in WRAPPING_TAGS:
        assert f"<{tag}>" in prompt, f"wrapping tag {tag!r} missing from prompt"


def test_prompt_extension_has_integrations_frame() -> None:
    prompt = build_system_prompt_extension()
    assert prompt.startswith('<integrations name="xai_voice">')
    assert prompt.endswith("</integrations>")


def test_prompt_extension_has_dosage_recipe() -> None:
    prompt = build_system_prompt_extension()
    low = prompt.lower()
    assert "sparing" in low or "0" in prompt
    assert "message" in low


def test_prompt_extension_has_narrator_mode_section() -> None:
    prompt = build_system_prompt_extension()
    low = prompt.lower()
    assert "narrat" in low
    assert "dialogue" in low or "quote" in low


def test_xai_voice_registration_uses_prompt_builder() -> None:
    defn = get_integration("xai_voice")
    assert defn is not None
    expected = build_system_prompt_extension()
    assert defn.system_prompt_template == expected


def test_prompt_extension_mentions_qualifier_syntax() -> None:
    prompt = build_system_prompt_extension()
    low = prompt.lower()
    assert "soft laugh" in low or "qualifier" in low
