from shared.dtos.persona import VoiceConfigDto


def test_narrator_mode_defaults_to_off():
    cfg = VoiceConfigDto()
    assert cfg.narrator_mode == "off"


def test_narrator_mode_accepts_valid_values():
    for v in ("off", "play", "narrate"):
        assert VoiceConfigDto(narrator_mode=v).narrator_mode == v


def test_legacy_roleplay_mode_true_translates_to_play():
    cfg = VoiceConfigDto.model_validate({"roleplay_mode": True})
    assert cfg.narrator_mode == "play"


def test_legacy_roleplay_mode_false_translates_to_off():
    cfg = VoiceConfigDto.model_validate({"roleplay_mode": False})
    assert cfg.narrator_mode == "off"


def test_narrator_mode_takes_precedence_over_legacy_flag():
    cfg = VoiceConfigDto.model_validate({"roleplay_mode": True, "narrator_mode": "narrate"})
    assert cfg.narrator_mode == "narrate"


def test_legacy_flag_is_not_re_emitted():
    cfg = VoiceConfigDto.model_validate({"roleplay_mode": True})
    dumped = cfg.model_dump()
    assert "roleplay_mode" not in dumped
    assert dumped["narrator_mode"] == "play"
