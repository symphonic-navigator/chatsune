"""Ported catalogue-logic tests for the nano-gpt adapter.

Consolidates the four source test modules (filters, pairing, mapping,
catalogue orchestration) from the ``nano-explore`` prototype into a single
file. The logic under test is a byte-identical port of
``nano_explore.catalog`` with two deliberate modifications (import-swap
to the real ``ModelMetaDto`` and populating the ``billing_category`` DTO
field) — see ``backend/modules/llm/_adapters/_nano_gpt_catalog.py``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.modules.llm._adapters._nano_gpt_catalog import (
    MIN_CONTEXT,
    build_catalogue,
    build_pairs,
    derive_display_name,
    filter_budget_variants,
    filter_context,
    filter_reasoning_only,
    to_model_meta,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "nano_gpt"


@pytest.fixture
def load_fixture():
    def _load(name: str) -> list[dict]:
        path = FIXTURE_DIR / f"{name}.json"
        return json.loads(path.read_text())
    return _load


# --- Filters ---


def test_filter_context_removes_null_context(load_fixture):
    entries = load_fixture("non_llm")
    survivors, rejected = filter_context(entries)
    assert survivors == []
    assert len(rejected) == 3
    assert all(r["reason"] == "low_context_or_non_llm" for r in rejected)
    assert all(r["context_length"] is None for r in rejected)


def test_filter_context_removes_low_context(load_fixture):
    entries = load_fixture("low_context")
    survivors, rejected = filter_context(entries)
    assert survivors == []
    assert len(rejected) == 3
    assert all(r["reason"] == "low_context_or_non_llm" for r in rejected)
    assert {r["context_length"] for r in rejected} == {8000, 12000}


def test_filter_context_keeps_large_context(load_fixture):
    entries = load_fixture("pair_colon")
    survivors, rejected = filter_context(entries)
    assert len(survivors) == 2
    assert rejected == []


def test_filter_context_boundary_at_80k():
    entries = [
        {"id": "just-below", "context_length": 79999},
        {"id": "exactly", "context_length": 80000},
        {"id": "above", "context_length": 80001},
    ]
    survivors, rejected = filter_context(entries)
    survivor_ids = {e["id"] for e in survivors}
    assert survivor_ids == {"exactly", "above"}
    assert {r["id"] for r in rejected} == {"just-below"}


def test_min_context_sentinel():
    assert MIN_CONTEXT == 80000


def test_filter_budget_variants_drops_all(load_fixture):
    entries = load_fixture("budget_variants")
    survivors, rejected = filter_budget_variants(entries)
    assert survivors == []
    assert len(rejected) == 4
    assert all(r["reason"] == "budget_variant" for r in rejected)
    matched_suffixes = {r["matched_suffix"] for r in rejected}
    assert "-thinking:8192" in matched_suffixes
    assert "-thinking:32768" in matched_suffixes
    assert ":thinking:low" in matched_suffixes
    assert ":thinking:max" in matched_suffixes


def test_filter_budget_variants_keeps_bare_thinking():
    entries = [
        {"id": "z-ai/glm-4.6:thinking", "context_length": 200000},
        {"id": "z-ai/glm-4.6", "context_length": 200000},
    ]
    survivors, rejected = filter_budget_variants(entries)
    assert len(survivors) == 2
    assert rejected == []


def test_filter_budget_variants_matches_dash_thinking_with_number():
    entries = [
        {"id": "claude-sonnet-4-thinking:1024", "context_length": 1000000},
        {"id": "claude-opus-4-1-thinking:32000", "context_length": 200000},
    ]
    survivors, rejected = filter_budget_variants(entries)
    assert survivors == []
    assert len(rejected) == 2


def test_filter_reasoning_only_o_series(load_fixture):
    entries = load_fixture("reasoning_only_o_series")
    survivors, rejected = filter_reasoning_only(entries)
    assert survivors == []
    assert len(rejected) == 3
    assert all(r["reason"] == "reasoning_only" for r in rejected)


def test_filter_reasoning_only_named(load_fixture):
    entries = load_fixture("reasoning_only_named")
    survivors, rejected = filter_reasoning_only(entries)
    assert survivors == []
    assert len(rejected) == 5


def test_filter_reasoning_only_keeps_flagships_with_reasoning_true(load_fixture):
    """gpt-5 and claude-sonnet-latest must survive despite reasoning=true."""
    entries = load_fixture("flagship_no_pair")
    survivors, rejected = filter_reasoning_only(entries)
    assert len(survivors) == 2
    assert rejected == []


def test_filter_reasoning_only_odd_thinking_names(load_fixture):
    """Qwen-Thinking-2507 and qwen3-vl-…-thinking fall through."""
    entries = load_fixture("odd_thinking_naming")
    survivors, rejected = filter_reasoning_only(entries)
    assert survivors == []
    assert len(rejected) == 2


def test_filter_reasoning_only_records_matched_pattern():
    entries = [{"id": "openai/o3-mini", "context_length": 200000}]
    survivors, rejected = filter_reasoning_only(entries)
    assert rejected[0]["matched_pattern"].startswith("^openai/o")


# --- Pairing ---


def test_build_pairs_colon_suffix(load_fixture):
    entries = load_fixture("pair_colon")
    pairs, singles = build_pairs(entries)
    assert len(pairs) == 1
    assert singles == []
    p = pairs[0]
    assert p["model_id"] == "z-ai/glm-4.6"
    assert p["non_thinking_slug"] == "z-ai/glm-4.6"
    assert p["thinking_slug"] == "z-ai/glm-4.6:thinking"
    assert p["inverted"] is False


def test_build_pairs_dash_suffix(load_fixture):
    entries = load_fixture("pair_dash")
    pairs, singles = build_pairs(entries)
    assert len(pairs) == 1
    assert singles == []
    p = pairs[0]
    assert p["non_thinking_slug"] == "claude-haiku-4-5-20251001"
    assert p["thinking_slug"] == "claude-haiku-4-5-20251001-thinking"


def test_build_pairs_inverted_nothinking(load_fixture):
    entries = load_fixture("pair_inverted")
    pairs, singles = build_pairs(entries)
    assert len(pairs) == 1
    assert singles == []
    p = pairs[0]
    assert p["model_id"] == "gemini-2.5-flash"
    assert p["non_thinking_slug"] == "gemini-2.5-flash-nothinking"
    assert p["thinking_slug"] == "gemini-2.5-flash"
    assert p["inverted"] is True


def test_build_pairs_case_insensitive(load_fixture):
    entries = load_fixture("pair_case_mixed")
    pairs, singles = build_pairs(entries)
    assert len(pairs) == 1
    assert singles == []
    p = pairs[0]
    # Canonical model_id is the non-thinking original-case slug.
    assert p["non_thinking_slug"] == "nousresearch/hermes-4-70b"
    assert p["thinking_slug"] == "NousResearch/Hermes-4-70B:thinking"


def test_build_pairs_singles_pass_through(load_fixture):
    entries = load_fixture("flagship_no_pair")
    pairs, singles = build_pairs(entries)
    assert pairs == []
    assert {s["id"] for s in singles} == {
        "openai/gpt-5",
        "anthropic/claude-sonnet-latest",
    }


def test_build_pairs_orphan_thinking_slug_becomes_single():
    """A :thinking slug whose base is missing stays a single."""
    entries = [
        {"id": "foo/bar:thinking", "context_length": 200000},
    ]
    pairs, singles = build_pairs(entries)
    assert pairs == []
    assert len(singles) == 1
    assert singles[0]["id"] == "foo/bar:thinking"


def test_build_pairs_no_double_counting(load_fixture):
    """When both halves are present, neither appears in singles."""
    entries = load_fixture("pair_colon")
    pairs, singles = build_pairs(entries)
    pair_slugs = {pairs[0]["non_thinking_slug"], pairs[0]["thinking_slug"]}
    for s in singles:
        assert s["id"] not in pair_slugs


# --- Mapping ---


def test_derive_display_name_from_slashed_slug():
    assert derive_display_name("google/gemma-4-26b-a4b-it") == "Google Gemma 4 26B A4B It"


def test_derive_display_name_plain():
    assert derive_display_name("claude-haiku-4-5-20251001") == "Claude Haiku 4 5 20251001"


def test_to_model_meta_single_no_pair_no_name():
    entry = {
        "id": "openai/gpt-5",
        "context_length": 400000,
        "capabilities": {"vision": True, "tool_calling": True},
    }
    meta, extras = to_model_meta(entry, pair_info=None)
    assert meta.model_id == "openai/gpt-5"
    assert meta.display_name == "Openai Gpt 5"
    assert meta.context_window == 400000
    assert meta.supports_reasoning is False
    assert meta.supports_vision is True
    assert meta.supports_tool_calls is True
    assert extras["non_thinking_slug"] == "openai/gpt-5"
    assert extras["thinking_slug"] is None
    assert extras["is_subscription"] is False


def test_to_model_meta_prefers_explicit_name():
    entry = {
        "id": "z-ai/glm-4.6",
        "name": "GLM 4.6",
        "context_length": 200000,
        "capabilities": {},
    }
    meta, _ = to_model_meta(entry, pair_info=None)
    assert meta.display_name == "GLM 4.6"


def test_to_model_meta_defaults_missing_capabilities_to_false():
    entry = {"id": "amazon/nova-pro-v1", "context_length": 300000}
    meta, _ = to_model_meta(entry, pair_info=None)
    assert meta.supports_vision is False
    assert meta.supports_tool_calls is False


def test_to_model_meta_with_pair_info_sets_supports_reasoning_true():
    non_thinking = {
        "id": "z-ai/glm-4.6",
        "name": "GLM 4.6",
        "context_length": 200000,
        "capabilities": {"vision": False, "tool_calling": True},
        "subscription": {"included": True},
    }
    pair_info = {
        "non_thinking_slug": "z-ai/glm-4.6",
        "thinking_slug": "z-ai/glm-4.6:thinking",
        "inverted": False,
    }
    meta, extras = to_model_meta(non_thinking, pair_info=pair_info)
    assert meta.supports_reasoning is True
    assert extras["thinking_slug"] == "z-ai/glm-4.6:thinking"
    assert extras["is_subscription"] is True


def test_to_model_meta_switchable_singleton_via_reasoning_flag():
    entry = {
        "id": "xiaomi/mimo-v2.5",
        "context_length": 1048576,
        "capabilities": {"reasoning": True, "tool_calling": True, "vision": True},
    }
    meta, extras = to_model_meta(entry, pair_info=None)
    assert meta.supports_reasoning is True
    assert extras["switching_mode"] == "flag"
    assert extras["non_thinking_slug"] == "xiaomi/mimo-v2.5"
    assert extras["thinking_slug"] == "xiaomi/mimo-v2.5"


def test_to_model_meta_plain_singleton_switching_mode_none():
    entry = {
        "id": "vendor/plain",
        "context_length": 200000,
        "capabilities": {"reasoning": False, "tool_calling": True},
    }
    meta, extras = to_model_meta(entry, pair_info=None)
    assert meta.supports_reasoning is False
    assert extras["switching_mode"] == "none"
    assert extras["thinking_slug"] is None


def test_to_model_meta_inverted_pair_canonical_is_non_suffix_slug():
    non_thinking_raw = {
        "id": "gemini-2.5-flash-nothinking",
        "name": "Gemini 2.5 Flash (no thinking)",
        "context_length": 1048756,
        "capabilities": {"vision": True},
    }
    pair_info = {
        "non_thinking_slug": "gemini-2.5-flash-nothinking",
        "thinking_slug": "gemini-2.5-flash",
        "inverted": True,
        "model_id": "gemini-2.5-flash",
    }
    meta, _ = to_model_meta(non_thinking_raw, pair_info=pair_info)
    assert meta.model_id == "gemini-2.5-flash"
    assert meta.supports_reasoning is True


def test_to_model_meta_sets_subscription_when_included():
    entry = {
        "id": "provider/model-x",
        "context_length": 128000,
        "capabilities": {"vision": False, "tool_calling": False},
        "subscription": {"included": True},
    }
    dto, _extras = to_model_meta(entry, pair_info=None)
    assert dto.billing_category == "subscription"


def test_to_model_meta_sets_pay_per_token_when_not_included():
    entry = {
        "id": "provider/model-y",
        "context_length": 128000,
        "capabilities": {"vision": False, "tool_calling": False},
        "subscription": {"included": False},
    }
    dto, _extras = to_model_meta(entry, pair_info=None)
    assert dto.billing_category == "pay_per_token"


# --- Catalogue orchestration ---


def test_build_catalogue_end_to_end():
    dump = json.loads((FIXTURE_DIR / "mini_dump.json").read_text())
    result = build_catalogue(dump["data"])

    canonical_ids = {c["model_id"] for c in result.canonical}
    assert "z-ai/glm-4.6" in canonical_ids
    assert "claude-haiku-4-5-20251001" in canonical_ids
    assert "gemini-2.5-flash" in canonical_ids
    assert "openai/gpt-5" in canonical_ids
    # rejected
    rejected_ids = {r["id"] for r in result.rejected}
    assert "exa-research" in rejected_ids
    assert "glm-zero-preview" in rejected_ids
    assert "openai/o1" in rejected_ids
    assert "claude-opus-4-1-thinking:8192" in rejected_ids

    # thinking pairs produce supports_reasoning=True with switching_mode='slug'
    glm = next(c for c in result.canonical if c["model_id"] == "z-ai/glm-4.6")
    assert glm["supports_reasoning"] is True
    assert glm["switching_mode"] == "slug"
    assert glm["pair"]["thinking_slug"] == "z-ai/glm-4.6:thinking"

    # switchable singleton: gpt-5 has capabilities.reasoning=true and no pair
    gpt5 = next(c for c in result.canonical if c["model_id"] == "openai/gpt-5")
    assert gpt5["supports_reasoning"] is True
    assert gpt5["switching_mode"] == "flag"
    assert gpt5["pair"]["non_thinking_slug"] == "openai/gpt-5"
    assert gpt5["pair"]["thinking_slug"] == "openai/gpt-5"


def test_build_catalogue_counts_match_inputs():
    dump = json.loads((FIXTURE_DIR / "mini_dump.json").read_text())
    raw = dump["data"]
    result = build_catalogue(raw)
    # Every raw entry is either in canonical or rejected. Slug-switched
    # pairs consume two raw entries (one canonical + zero rejected);
    # flag- and none-mode entries consume one each.
    canonical_consumed = 0
    for c in result.canonical:
        canonical_consumed += 2 if c["switching_mode"] == "slug" else 1
    assert canonical_consumed + len(result.rejected) == len(raw)


def test_build_catalogue_plain_singleton_no_switching():
    raw = [
        {
            "id": "vendor/plain-chat-model",
            "context_length": 200000,
            "capabilities": {"reasoning": False, "tool_calling": True},
        },
    ]
    result = build_catalogue(raw)
    block = next(c for c in result.canonical if c["model_id"] == "vendor/plain-chat-model")
    assert block["supports_reasoning"] is False
    assert block["switching_mode"] == "none"
    assert block["pair"]["thinking_slug"] is None
    assert result.summary["switchable_singleton_count"] == 0


def test_build_catalogue_counts_switchable_singletons():
    dump = json.loads((FIXTURE_DIR / "mini_dump.json").read_text())
    result = build_catalogue(dump["data"])
    # gpt-5 in mini_dump qualifies as a switchable singleton.
    assert result.summary["switchable_singleton_count"] >= 1


def test_build_catalogue_summary_counts():
    dump = json.loads((FIXTURE_DIR / "mini_dump.json").read_text())
    result = build_catalogue(dump["data"])
    assert result.summary["input_count"] == len(dump["data"])
    assert result.summary["canonical_count"] == len(result.canonical)
    assert result.summary["pair_count"] >= 1


def test_quality_notes_reasoning_flag_dissonance():
    # Entry has reasoning=null but slug clearly signals thinking (via pair).
    # Chatsune-authoritative is pair presence → supports_reasoning=True.
    # We expect a quality note when raw.reasoning is null and slug is thinking side.
    raw = [
        {"id": "z-ai/glm-4.6", "context_length": 200000, "capabilities": {"reasoning": True}},
        {"id": "z-ai/glm-4.6:thinking", "context_length": 200000, "capabilities": {"reasoning": None}},
    ]
    result = build_catalogue(raw)
    kinds = {n["kind"] for n in result.quality_notes}
    assert "reasoning_flag_dissonance" in kinds


def test_quality_notes_case_inconsistency_in_pair():
    raw = [
        {"id": "nousresearch/hermes-4-70b", "context_length": 128000, "capabilities": {}},
        {"id": "NousResearch/Hermes-4-70B:thinking", "context_length": 128000, "capabilities": {}},
    ]
    result = build_catalogue(raw)
    kinds = {n["kind"] for n in result.quality_notes}
    assert "case_inconsistency" in kinds
