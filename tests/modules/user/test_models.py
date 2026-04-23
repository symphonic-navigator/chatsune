from datetime import datetime, UTC

from backend.modules.user._models import (
    UserKeysDocument,
    WrappedDekPair,
    Argon2Params,
)


def test_argon2_params_defaults():
    p = Argon2Params()
    assert p.memory_kib == 65536
    assert p.iterations == 3
    assert p.parallelism == 4


def test_wrapped_dek_pair_is_bytes():
    pair = WrappedDekPair(
        wrapped_by_password=b"\x00" * 60,
        wrapped_by_recovery=b"\x01" * 60,
        created_at=datetime.now(UTC),
    )
    assert isinstance(pair.wrapped_by_password, bytes)
    assert isinstance(pair.wrapped_by_recovery, bytes)


def test_user_keys_document_defaults():
    doc = UserKeysDocument(
        user_id="507f1f77bcf86cd799439011",
        kdf_salt=b"s" * 32,
        kdf_params=Argon2Params(),
        current_dek_version=1,
        deks={"1": WrappedDekPair(
            wrapped_by_password=b"\x00" * 60,
            wrapped_by_recovery=b"\x01" * 60,
            created_at=datetime.now(UTC),
        )},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assert doc.dek_recovery_required is False
