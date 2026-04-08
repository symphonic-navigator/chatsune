from backend.jobs._retry import compute_backoff


def test_attempt_one_returns_base():
    assert compute_backoff(1) == 15


def test_attempt_two_doubles():
    assert compute_backoff(2) == 30


def test_attempt_three():
    assert compute_backoff(3) == 60


def test_attempt_four():
    assert compute_backoff(4) == 120


def test_attempt_five():
    assert compute_backoff(5) == 240


def test_attempt_six_capped():
    assert compute_backoff(6) == 300


def test_attempt_ten_still_capped():
    assert compute_backoff(10) == 300


def test_custom_base_and_cap():
    assert compute_backoff(1, base=10, cap=100) == 10


def test_custom_cap_enforced():
    assert compute_backoff(5, base=10, cap=100) == 100


def test_defensive_floor_zero():
    assert compute_backoff(0) == 15
