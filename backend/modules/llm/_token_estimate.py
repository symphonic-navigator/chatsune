"""Conservative token estimation for safeguarding background-job LLM calls.

We deliberately over-estimate (1 token per 3 characters) so the guard
trips early rather than too late. Real tokenisers average ~4 chars/token
for English; we pick 3 to leave headroom for code, non-Latin scripts,
and tokenisation overhead."""

_DEFAULT_CONTEXT_WINDOW = 8192

_CONTEXT_WINDOWS: dict[str, int] = {
    # Populate as needed. Keys are "provider_id:model_slug" or just model_slug.
}


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 3)


def context_window_for(provider_id: str, model_slug: str) -> int:
    key = f"{provider_id}:{model_slug}"
    if key in _CONTEXT_WINDOWS:
        return _CONTEXT_WINDOWS[key]
    if model_slug in _CONTEXT_WINDOWS:
        return _CONTEXT_WINDOWS[model_slug]
    return _DEFAULT_CONTEXT_WINDOW
