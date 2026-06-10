/**
 * Mirror of backend ``is_anthropic_model``.
 *
 * Used by the persona-edit form to conditionally render the prompt-cache
 * dropdown. Must stay in lock-step with
 * ``backend/modules/llm/_adapters/_anthropic_cache.py``.
 *
 * Strategy: take everything after the last ``/`` (or the whole string
 * if there is no ``/``), then test for ``claude.*haiku|sonnet|opus|fable``
 * with the wildcard bounded to non-slash chars (linear evaluation).
 */
const CLAUDE_RE = /claude[^/]*\b(haiku|sonnet|opus|fable)\b/i

export function isAnthropicModel(modelId: string): boolean {
  const tail = modelId.split('/').pop() ?? ''
  return CLAUDE_RE.test(tail)
}
