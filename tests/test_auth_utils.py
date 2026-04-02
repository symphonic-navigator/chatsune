from datetime import timedelta
from uuid import uuid4

import pytest

from backend.modules.user._auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
    generate_random_password,
)


def test_hash_and_verify_password():
    password = "test-password-123"
    hashed = hash_password(password)
    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("wrong-password", hashed) is False


def test_create_and_decode_access_token():
    user_id = str(uuid4())
    session_id = str(uuid4())
    token = create_access_token(
        user_id=user_id, role="admin", session_id=session_id
    )
    payload = decode_access_token(token)
    assert payload["sub"] == user_id
    assert payload["role"] == "admin"
    assert payload["session_id"] == session_id
    assert "mcp" not in payload


def test_access_token_with_mcp_claim():
    user_id = str(uuid4())
    session_id = str(uuid4())
    token = create_access_token(
        user_id=user_id,
        role="user",
        session_id=session_id,
        must_change_password=True,
    )
    payload = decode_access_token(token)
    assert payload["mcp"] is True


def test_decode_expired_token_raises():
    token = create_access_token(
        user_id="x",
        role="user",
        session_id="y",
        expires_delta=timedelta(seconds=-1),
    )
    with pytest.raises(Exception):
        decode_access_token(token)


def test_generate_random_password():
    pw = generate_random_password()
    assert len(pw) == 20
    assert pw.isalnum()

    # Two calls should produce different passwords
    pw2 = generate_random_password()
    assert pw != pw2
