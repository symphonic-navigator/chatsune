import secrets
import pytest

from backend.modules.user._crypto import (
    derive_wrap_key,
    aes_gcm_wrap,
    aes_gcm_unwrap,
    pseudo_salt_for_unknown_user,
    AesGcmUnwrapError,
)


def test_derive_wrap_key_is_deterministic_per_input_and_info():
    k1 = derive_wrap_key(b"input" * 4, info=b"dek-wrap")
    k2 = derive_wrap_key(b"input" * 4, info=b"dek-wrap")
    assert k1 == k2
    assert len(k1) == 32


def test_derive_wrap_key_differs_by_info_string():
    material = secrets.token_bytes(32)
    assert derive_wrap_key(material, info=b"a") != derive_wrap_key(material, info=b"b")


def test_wrap_then_unwrap_returns_plaintext():
    key = secrets.token_bytes(32)
    plaintext = secrets.token_bytes(32)
    blob = aes_gcm_wrap(key, plaintext)
    # nonce (12) + ct (32) + tag (16) == 60 bytes for 32-byte plaintext
    assert len(blob) == 12 + 32 + 16
    assert aes_gcm_unwrap(key, blob) == plaintext


def test_unwrap_with_wrong_key_raises():
    key1 = secrets.token_bytes(32)
    key2 = secrets.token_bytes(32)
    blob = aes_gcm_wrap(key1, b"secret")
    with pytest.raises(AesGcmUnwrapError):
        aes_gcm_unwrap(key2, blob)


def test_wrap_uses_fresh_nonce_each_call():
    key = secrets.token_bytes(32)
    blob_a = aes_gcm_wrap(key, b"same-plaintext")
    blob_b = aes_gcm_wrap(key, b"same-plaintext")
    assert blob_a != blob_b


def test_pseudo_salt_is_deterministic_per_username():
    pepper = secrets.token_bytes(32)
    a = pseudo_salt_for_unknown_user("chris", pepper)
    b = pseudo_salt_for_unknown_user("chris", pepper)
    assert a == b
    assert len(a) == 32


def test_pseudo_salt_is_case_insensitive_and_trimmed():
    pepper = secrets.token_bytes(32)
    assert pseudo_salt_for_unknown_user("Chris", pepper) == pseudo_salt_for_unknown_user("  chris ", pepper)
