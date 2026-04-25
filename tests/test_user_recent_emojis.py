import pytest

from backend.modules.user import UserService
from backend.modules.user._models import DEFAULT_RECENT_EMOJIS


def test_merge_lru_front_loads_new_emoji():
    result = UserService._merge_lru(
        current=["a", "b", "c", "d", "e", "f"],
        incoming=["x"],
        max_size=6,
    )
    assert result == ["x", "a", "b", "c", "d", "e"]


def test_merge_lru_dedupes_within_incoming():
    result = UserService._merge_lru(
        current=["a", "b", "c", "d", "e", "f"],
        incoming=["x", "x", "y"],
        max_size=6,
    )
    assert result == ["x", "y", "a", "b", "c", "d"]


def test_merge_lru_moves_existing_emoji_to_front():
    result = UserService._merge_lru(
        current=["a", "b", "c", "d", "e", "f"],
        incoming=["c"],
        max_size=6,
    )
    assert result == ["c", "a", "b", "d", "e", "f"]


def test_merge_lru_caps_at_max_size():
    result = UserService._merge_lru(
        current=["a", "b", "c", "d", "e", "f"],
        incoming=["x", "y", "z"],
        max_size=6,
    )
    assert result == ["x", "y", "z", "a", "b", "c"]


def test_merge_lru_handles_empty_incoming():
    result = UserService._merge_lru(
        current=["a", "b", "c"],
        incoming=[],
        max_size=6,
    )
    assert result == ["a", "b", "c"]


def test_merge_lru_handles_empty_current():
    result = UserService._merge_lru(
        current=[],
        incoming=["x", "y"],
        max_size=6,
    )
    assert result == ["x", "y"]


class _StubRepo:
    def __init__(self, doc):
        self._doc = doc
        self.last_update: tuple[str, list[str]] | None = None

    async def find_by_id(self, user_id):
        return self._doc

    async def update_recent_emojis(self, user_id, emojis):
        self.last_update = (user_id, emojis)


class _StubBus:
    def __init__(self):
        self.calls = []

    async def publish(self, topic, event, **kwargs):
        self.calls.append((topic, event, kwargs))


def _make_service(repo, bus):
    svc = UserService.__new__(UserService)
    svc._repository = repo
    svc._event_bus = bus
    return svc


@pytest.mark.asyncio
async def test_touch_recent_emojis_uses_default_set_when_field_missing():
    """Pre-existing users (created before this feature) have no recent_emojis
    field. Their first send must front-load the new emoji into the BRANDED
    default set, not into an empty list."""
    repo = _StubRepo({"_id": "u1"})  # no recent_emojis key
    bus = _StubBus()
    svc = _make_service(repo, bus)

    await svc.touch_recent_emojis("u1", ["🌟"])

    assert repo.last_update is not None
    user_id, new_emojis = repo.last_update
    assert user_id == "u1"
    # 🌟 first, then the default set with the last entry dropped to keep size 6
    assert new_emojis == ["🌟", "👍", "❤️", "😂", "🤘", "😊"]


@pytest.mark.asyncio
async def test_touch_recent_emojis_uses_default_set_when_field_is_empty_list():
    repo = _StubRepo({"_id": "u2", "recent_emojis": []})
    bus = _StubBus()
    svc = _make_service(repo, bus)

    await svc.touch_recent_emojis("u2", ["🌟"])

    assert repo.last_update is not None
    _, new_emojis = repo.last_update
    assert new_emojis == ["🌟", "👍", "❤️", "😂", "🤘", "😊"]
