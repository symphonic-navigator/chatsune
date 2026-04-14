"""Conservative token estimation for safeguarding background-job LLM calls.

We deliberately over-estimate (1 token per 3 characters) so the guard
trips early rather than too late. Real tokenisers average ~4 chars/token
for English; we pick 3 to leave headroom for code, non-Latin scripts,
and tokenisation overhead."""

DEFAULT_CONTEXT_WINDOW = 8192


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 3)
