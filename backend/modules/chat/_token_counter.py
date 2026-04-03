import tiktoken

_encoding = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Count tokens using cl100k_base encoding.

    Pessimistic but safe — over-counts for most models,
    ensuring we never overflow the context window.
    """
    if not text:
        return 0
    return len(_encoding.encode(text))
