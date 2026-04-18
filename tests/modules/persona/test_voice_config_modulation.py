import pytest
from pydantic import ValidationError

from shared.dtos.persona import VoiceConfigDto


def test_defaults_are_neutral():
    cfg = VoiceConfigDto()
    assert cfg.dialogue_speed == 1.0
    assert cfg.dialogue_pitch == 0
    assert cfg.narrator_speed == 1.0
    assert cfg.narrator_pitch == 0


def test_speed_clamped_to_range():
    with pytest.raises(ValidationError):
        VoiceConfigDto(dialogue_speed=0.5)
    with pytest.raises(ValidationError):
        VoiceConfigDto(dialogue_speed=2.0)
    # Boundary values accepted
    VoiceConfigDto(dialogue_speed=0.75, narrator_speed=1.5)


def test_pitch_clamped_to_range():
    with pytest.raises(ValidationError):
        VoiceConfigDto(dialogue_pitch=-12)
    with pytest.raises(ValidationError):
        VoiceConfigDto(dialogue_pitch=7)
    VoiceConfigDto(dialogue_pitch=-6, narrator_pitch=6)


def test_existing_document_without_modulation_loads():
    cfg = VoiceConfigDto.model_validate(
        {"dialogue_voice": "alice", "narrator_mode": "play"}
    )
    assert cfg.dialogue_speed == 1.0
    assert cfg.narrator_pitch == 0
