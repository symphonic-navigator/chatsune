from pathlib import Path
from unittest.mock import patch

import pytest

from backend.modules.persona._avatar_store import AvatarStore


@pytest.fixture
def avatar_root(tmp_path: Path) -> Path:
    root = tmp_path / "avatars"
    root.mkdir()
    return root


def test_duplicate_creates_new_file_with_same_bytes(avatar_root: Path) -> None:
    with patch("backend.modules.persona._avatar_store.settings") as s:
        s.avatar_root = str(avatar_root)
        store = AvatarStore()
        original = store.save(b"hello-avatar", "png")
        duplicate = store.duplicate(original)

        assert duplicate is not None
        assert duplicate != original
        assert duplicate.endswith(".png")
        assert (avatar_root / duplicate).read_bytes() == b"hello-avatar"
        # Source must remain intact.
        assert (avatar_root / original).read_bytes() == b"hello-avatar"


def test_duplicate_returns_none_if_source_missing(avatar_root: Path) -> None:
    with patch("backend.modules.persona._avatar_store.settings") as s:
        s.avatar_root = str(avatar_root)
        store = AvatarStore()
        assert store.duplicate("does-not-exist.png") is None
