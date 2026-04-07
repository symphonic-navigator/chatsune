from backend.modules.chat._soft_cot import (
    SOFT_COT_INSTRUCTIONS,
    SOFT_COT_MARKER,
    is_soft_cot_active,
)


def test_inactive_when_soft_cot_disabled():
    assert is_soft_cot_active(False, supports_reasoning=False, reasoning_enabled=False) is False
    assert is_soft_cot_active(False, supports_reasoning=True, reasoning_enabled=False) is False
    assert is_soft_cot_active(False, supports_reasoning=True, reasoning_enabled=True) is False


def test_active_when_non_reasoning_model():
    assert is_soft_cot_active(True, supports_reasoning=False, reasoning_enabled=False) is True
    # reasoning_enabled is moot when the model can't reason
    assert is_soft_cot_active(True, supports_reasoning=False, reasoning_enabled=True) is True


def test_inactive_when_hard_cot_takes_over():
    assert is_soft_cot_active(True, supports_reasoning=True, reasoning_enabled=True) is False


def test_active_when_reasoning_capable_but_hard_cot_off():
    assert is_soft_cot_active(True, supports_reasoning=True, reasoning_enabled=False) is True


def test_marker_is_present_in_block():
    assert SOFT_COT_MARKER in SOFT_COT_INSTRUCTIONS
