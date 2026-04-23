import pytest

from backend.modules.user._recovery_key import (
    generate_recovery_key,
    normalise_recovery_key,
    decode_recovery_key,
    encode_recovery_key,
    InvalidRecoveryKeyError,
    RECOVERY_KEY_RAW_BYTES,
    RECOVERY_KEY_DISPLAY_LENGTH,
)


def test_generate_is_formatted_as_groups_of_four():
    key = generate_recovery_key()
    assert len(key) == RECOVERY_KEY_DISPLAY_LENGTH
    groups = key.split("-")
    assert len(groups) == 8
    assert all(len(g) == 4 for g in groups)


def test_round_trip_encode_decode():
    key = generate_recovery_key()
    raw = decode_recovery_key(key)
    assert len(raw) == RECOVERY_KEY_RAW_BYTES
    assert encode_recovery_key(raw) == key


def test_normalise_accepts_spaces_hyphens_mixed_case():
    key = generate_recovery_key()
    noisy = "  " + key.lower().replace("-", " ") + "  "
    assert normalise_recovery_key(noisy) == key.replace("-", "")


def test_crockford_ambiguity_mapping_on_input():
    # Crockford treats O -> 0, I/L -> 1. Input must be accepted and decoded identically.
    base = generate_recovery_key().replace("-", "")
    # Substitute a 0 in the string with 'O' (if any), or 1 with 'I', to probe mapping.
    probed = base.replace("0", "O", 1).replace("1", "I", 1)
    assert decode_recovery_key(probed) == decode_recovery_key(base)


def test_invalid_characters_reject():
    # U is explicitly excluded from the Crockford-Base32 alphabet.
    with pytest.raises(InvalidRecoveryKeyError):
        decode_recovery_key("U" * 32)


def test_wrong_length_rejects():
    with pytest.raises(InvalidRecoveryKeyError):
        decode_recovery_key("ABCD" * 7)
