"""Soft Chain-of-Thought instruction block and visibility helper.

Internal module — must not be imported from outside ``backend.modules.chat``.

The instruction text is intentionally a single curated block covering both
analytical step-by-step reasoning and relational/empathic reasoning. It is
maintained centrally; per-persona overrides are out of scope.
"""

# Stable marker substring used by tests to assert the block was injected
# without coupling them to the full prose. Do not change without updating
# the test assertions.
SOFT_COT_MARKER = "<<<SOFT_COT_BLOCK_V1>>>"

SOFT_COT_INSTRUCTIONS = f"""<softcot priority="high">
{SOFT_COT_MARKER}
Before giving your final answer, think step by step and write your reasoning
inside a single <think>...</think> block. Then, on the next line, write the
final answer for the user. Do not put the final answer inside <think>.

Apply this to two complementary modes of reasoning:

1. Analytical reasoning — for technical, factual, or hard-science questions:
   enumerate your assumptions, work through them in order, double-check before
   you commit to a conclusion. Show the work, do not skip steps.

2. Relational reasoning — for psychology, emotion, subtext, mood, and
   interpretation: read between the lines, name the emotional state you
   suspect, and be willing to make associative leaps and bold interpretations
   rather than hedging. Empathy is itself a step-by-step process: notice,
   name, connect, respond.

If the user's question only needs one of these modes, use that one. If both
apply, use both. The thinking block can be as short or as long as the
question demands.
</softcot>"""


def is_soft_cot_active(
    soft_cot_enabled: bool,
    supports_reasoning: bool,
    reasoning_enabled: bool,
) -> bool:
    """Decide whether the Soft-CoT block should be injected for an inference call.

    Active if:
      - the user has opted in via the persona toggle, AND
      - either the model has no native reasoning capability,
        or the model has it but the user has turned Hard-CoT off for this call.

    The persona's ``soft_cot_enabled`` flag is never silently mutated by this
    helper; visibility is recomputed at every inference call.
    """
    if not soft_cot_enabled:
        return False
    if not supports_reasoning:
        return True
    return not reasoning_enabled
