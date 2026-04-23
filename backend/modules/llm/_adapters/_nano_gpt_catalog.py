"""Filter, pair, and map nano-gpt /models dumps to canonical ModelMetaDto.

Pure-function module. Every transformation returns (survivors, rejected)
so no entry is silently lost.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from shared.dtos.llm import ModelMetaDto

MIN_CONTEXT = 80000

RawEntry = dict[str, Any]
Rejected = dict[str, Any]


def filter_context(entries: list[RawEntry]) -> tuple[list[RawEntry], list[Rejected]]:
    """Drop entries with null or sub-80k context_length.

    Covers both legacy small-context LLMs and non-LLM entries (search APIs).
    """
    survivors: list[RawEntry] = []
    rejected: list[Rejected] = []
    for entry in entries:
        ctx = entry.get("context_length")
        if ctx is None or ctx < MIN_CONTEXT:
            rejected.append({
                "id": entry["id"],
                "reason": "low_context_or_non_llm",
                "context_length": ctx,
            })
        else:
            survivors.append(entry)
    return survivors, rejected


_BUDGET_VARIANT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(:thinking:(?:low|medium|max))$", re.IGNORECASE),
    re.compile(r"(:thinking:\d+)$"),
    re.compile(r"(-thinking:\d+)$"),
]


def filter_budget_variants(
    entries: list[RawEntry],
) -> tuple[list[RawEntry], list[Rejected]]:
    """Drop thinking-slugs carrying budget or level suffixes.

    chatsune's ModelMetaDto has no budget field; those are request-level.
    """
    survivors: list[RawEntry] = []
    rejected: list[Rejected] = []
    for entry in entries:
        slug = entry["id"]
        matched = None
        for pattern in _BUDGET_VARIANT_PATTERNS:
            match = pattern.search(slug)
            if match:
                matched = match.group(1)
                break
        if matched is not None:
            rejected.append({
                "id": slug,
                "reason": "budget_variant",
                "matched_suffix": matched,
            })
        else:
            survivors.append(entry)
    return survivors, rejected


Pair = dict[str, Any]


def _detect_suffix(slug: str) -> tuple[str, str] | None:
    """Return (kind, base_lower) if slug ends in a known pair suffix."""
    lower = slug.lower()
    if lower.endswith(":thinking"):
        return ("thinking", lower[: -len(":thinking")])
    if lower.endswith("-thinking"):
        return ("thinking", lower[: -len("-thinking")])
    if lower.endswith("-nothinking"):
        return ("inverted", lower[: -len("-nothinking")])
    return None


def build_pairs(
    entries: list[RawEntry],
) -> tuple[list[Pair], list[RawEntry]]:
    """Identify :thinking, -thinking, and inverted -nothinking pairs.

    Returns (pairs, singles). Case-insensitive base lookup; original-case
    slugs preserved in the Pair dict.
    """
    by_lower: dict[str, RawEntry] = {e["id"].lower(): e for e in entries}
    consumed: set[str] = set()  # lower-case IDs already used in a pair
    pairs: list[Pair] = []

    for entry in entries:
        slug = entry["id"]
        lower = slug.lower()
        if lower in consumed:
            continue
        suffix = _detect_suffix(slug)
        if suffix is None:
            continue
        kind, base_lower = suffix
        base_entry = by_lower.get(base_lower)
        if base_entry is None:
            # Orphan thinking-suffixed slug; leave as single.
            continue
        base_slug = base_entry["id"]
        if kind == "inverted":
            # base_slug is the thinking side; suffixed slug is non-thinking.
            pair: Pair = {
                "model_id": base_slug,
                "non_thinking_slug": slug,
                "thinking_slug": base_slug,
                "inverted": True,
                "raw_non_thinking": entry,
                "raw_thinking": base_entry,
            }
        else:
            pair = {
                "model_id": base_slug,
                "non_thinking_slug": base_slug,
                "thinking_slug": slug,
                "inverted": False,
                "raw_non_thinking": base_entry,
                "raw_thinking": entry,
            }
        pairs.append(pair)
        consumed.add(lower)
        consumed.add(base_lower)

    singles = [e for e in entries if e["id"].lower() not in consumed]
    return pairs, singles


_REASONING_ONLY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^openai/o\d", re.IGNORECASE),
    re.compile(r"-thinking(-|:|$)", re.IGNORECASE),
    re.compile(r"-think$", re.IGNORECASE),
    re.compile(r"-reason(er|ing)(-|$)", re.IGNORECASE),
    re.compile(r"(?:^|/)deepseek-r1", re.IGNORECASE),
    re.compile(r"/R1T", re.IGNORECASE),
    re.compile(r"deep-research", re.IGNORECASE),
    re.compile(r"/K2-Think$", re.IGNORECASE),
]


def filter_reasoning_only(
    entries: list[RawEntry],
) -> tuple[list[RawEntry], list[Rejected]]:
    """Drop reasoning-only models by slug heuristic.

    MUST be called AFTER build_pairs on the singles only. An entry that
    matches a thinking-suffix pattern but is part of a pair is exempt,
    since it is the thinking half of that pair — the filter would
    otherwise reject it incorrectly.
    """
    survivors: list[RawEntry] = []
    rejected: list[Rejected] = []
    for entry in entries:
        slug = entry["id"]
        matched_pattern: str | None = None
        for pattern in _REASONING_ONLY_PATTERNS:
            if pattern.search(slug):
                matched_pattern = pattern.pattern
                break
        if matched_pattern is not None:
            rejected.append({
                "id": slug,
                "reason": "reasoning_only",
                "matched_pattern": matched_pattern,
            })
        else:
            survivors.append(entry)
    return survivors, rejected


def derive_display_name(slug: str) -> str:
    cleaned = slug.replace("/", " ").replace("_", " ").replace("-", " ")
    return " ".join(token.title() for token in cleaned.split() if token)


def to_model_meta(
    entry: RawEntry,
    pair_info: Pair | None,
) -> tuple[ModelMetaDto, dict[str, Any]]:
    """Build a ModelMetaDto plus adapter-internal extras.

    If pair_info is given, the canonical model_id comes from pair_info
    (handling inverted pairs correctly); supports_reasoning = True.
    Otherwise, the entry's own id is used and supports_reasoning = False.
    """
    caps = entry.get("capabilities") or {}
    name = entry.get("name") or derive_display_name(entry["id"])
    subscription = entry.get("subscription") or {}
    is_subscription = bool(subscription.get("included"))
    billing_category = "subscription" if is_subscription else "pay_per_token"

    if pair_info is None:
        model_id = entry["id"]
        supports_reasoning = False
        thinking_slug: str | None = None
        non_thinking_slug = entry["id"]
    else:
        model_id = pair_info.get("model_id") or pair_info["non_thinking_slug"]
        supports_reasoning = True
        thinking_slug = pair_info["thinking_slug"]
        non_thinking_slug = pair_info["non_thinking_slug"]

    meta = ModelMetaDto(
        connection_id="",
        model_id=model_id,
        display_name=name,
        context_window=entry["context_length"],
        supports_reasoning=supports_reasoning,
        supports_vision=bool(caps.get("vision")),
        supports_tool_calls=bool(caps.get("tool_calling")),
        billing_category=billing_category,
    )
    extras = {
        "non_thinking_slug": non_thinking_slug,
        "thinking_slug": thinking_slug,
        "is_subscription": is_subscription,
    }
    return meta, extras


@dataclass
class CatalogueResult:
    canonical: list[dict[str, Any]]
    rejected: list[Rejected]
    pair_map: dict[str, dict[str, Any]]
    summary: dict[str, Any]
    quality_notes: list[dict[str, Any]] = field(default_factory=list)


def build_catalogue(raw: list[RawEntry]) -> CatalogueResult:
    """Orchestrate the full pipeline: filter -> pair -> filter -> map."""
    rejected: list[Rejected] = []

    step1, r1 = filter_context(raw)
    rejected.extend(r1)
    step2, r2 = filter_budget_variants(step1)
    rejected.extend(r2)
    pairs, singles = build_pairs(step2)
    step3_singles, r3 = filter_reasoning_only(singles)
    rejected.extend(r3)

    canonical: list[dict[str, Any]] = []
    pair_map: dict[str, dict[str, Any]] = {}

    # Paired entries first.
    for pair in pairs:
        source_entry = pair["raw_non_thinking"]
        meta, extras = to_model_meta(source_entry, pair_info=pair)
        block = _block(meta, extras)
        canonical.append(block)
        pair_map[meta.model_id] = {
            "non_thinking_slug": extras["non_thinking_slug"],
            "thinking_slug": extras["thinking_slug"],
        }

    # Then singles.
    for entry in step3_singles:
        meta, extras = to_model_meta(entry, pair_info=None)
        block = _block(meta, extras)
        canonical.append(block)
        pair_map[meta.model_id] = {
            "non_thinking_slug": extras["non_thinking_slug"],
            "thinking_slug": None,
        }

    # Quality-note collection (for nano-gpt curation-team feedback).
    quality_notes: list[dict[str, Any]] = []
    for pair in pairs:
        nt = pair["raw_non_thinking"]
        th = pair["raw_thinking"]
        # Case inconsistency inside a pair.
        nt_has_upper = any(c.isupper() for c in nt["id"])
        th_has_upper = any(c.isupper() for c in th["id"])
        if nt_has_upper != th_has_upper:
            quality_notes.append({
                "kind": "case_inconsistency",
                "id": f"{nt['id']} ↔ {th['id']}",
                "detail": "Pair halves differ in casing; matched via case-insensitive lookup.",
            })
        # Reasoning-flag dissonance on the thinking half.
        th_flag = (th.get("capabilities") or {}).get("reasoning")
        if th_flag is None or th_flag is False:
            quality_notes.append({
                "kind": "reasoning_flag_dissonance",
                "id": th["id"],
                "detail": "Thinking-side of a pair has reasoning=null/false in raw data; slug semantics say otherwise.",
            })

    canonical.sort(key=lambda b: b["model_id"])
    rejected.sort(key=lambda r: (r["reason"], r["id"]))

    summary = {
        "input_count": len(raw),
        "after_filter_context": len(step1),
        "after_filter_budget_variants": len(step2),
        "pair_count": len(pairs),
        "pair_inverted_count": sum(1 for p in pairs if p["inverted"]),
        "singles_after_reasoning_only": len(step3_singles),
        "canonical_count": len(canonical),
        "rejected_count": len(rejected),
    }
    return CatalogueResult(
        canonical=canonical,
        rejected=rejected,
        pair_map=pair_map,
        summary=summary,
        quality_notes=quality_notes,
    )


def _block(meta: ModelMetaDto, extras: dict[str, Any]) -> dict[str, Any]:
    return {
        "model_id": meta.model_id,
        "display_name": meta.display_name,
        "context_window": meta.context_window,
        "supports_reasoning": meta.supports_reasoning,
        "supports_vision": meta.supports_vision,
        "supports_tool_calls": meta.supports_tool_calls,
        "billing_category": meta.billing_category,
        "is_subscription": extras["is_subscription"],
        "pair": {
            "non_thinking_slug": extras["non_thinking_slug"],
            "thinking_slug": extras["thinking_slug"],
        },
    }
