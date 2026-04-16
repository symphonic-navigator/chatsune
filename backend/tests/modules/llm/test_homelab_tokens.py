from backend.modules.llm._homelab_tokens import (
    API_KEY_PREFIX,
    HOMELAB_ID_LENGTH,
    HOST_KEY_PREFIX,
    generate_api_key,
    generate_homelab_id,
    generate_host_key,
    hash_token,
    hint_for,
)


def test_generate_host_key_has_prefix_and_length():
    key = generate_host_key()
    assert key.startswith(HOST_KEY_PREFIX)
    assert len(key) == len(HOST_KEY_PREFIX) + 43  # token_urlsafe(32)


def test_generate_api_key_has_prefix_and_length():
    key = generate_api_key()
    assert key.startswith(API_KEY_PREFIX)
    assert len(key) == len(API_KEY_PREFIX) + 43


def test_generate_homelab_id_length_and_charset():
    hid = generate_homelab_id()
    assert len(hid) == HOMELAB_ID_LENGTH == 11
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    assert set(hid) <= allowed


def test_generated_tokens_are_unique():
    seen = {generate_host_key() for _ in range(100)}
    assert len(seen) == 100


def test_hash_token_is_deterministic_hex_sha256():
    assert hash_token("cshost_abc") == hash_token("cshost_abc")
    assert len(hash_token("x")) == 64
    assert all(c in "0123456789abcdef" for c in hash_token("x"))


def test_hash_token_differs_for_different_inputs():
    assert hash_token("cshost_a") != hash_token("cshost_b")


def test_hint_for_returns_last_four_chars():
    assert hint_for("cshost_1234567890xyzwABCD") == "ABCD"


def test_hint_for_short_token_pads():
    assert hint_for("ab") == "ab"
