from backend.modules.chat._token_counter import count_tokens


def test_count_tokens_empty_string():
    assert count_tokens("") == 0


def test_count_tokens_simple_text():
    result = count_tokens("Hello world")
    assert isinstance(result, int)
    assert result > 0


def test_count_tokens_longer_text():
    short = count_tokens("Hi")
    long = count_tokens("This is a much longer sentence with more tokens")
    assert long > short


def test_count_tokens_deterministic():
    text = "The quick brown fox jumps over the lazy dog"
    assert count_tokens(text) == count_tokens(text)
