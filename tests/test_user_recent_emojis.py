from backend.modules.user import UserService


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
