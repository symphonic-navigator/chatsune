"""PTI service-level logic: cooldown filtering, dedupe, cap enforcement.

Pure functions over plain dataclasses — no DB or event-bus dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass

from shared.dtos.chat import KnowledgeContextItem, PtiOverflow

REFRESH_TO_N: dict[str, int] = {
    "rarely": 10,
    "standard": 7,
    "often": 5,
}


@dataclass
class DocumentCandidate:
    """A trigger hit that still needs cooldown/cap filtering."""

    doc_id: str
    title: str
    library_name: str
    triggered_by: str
    position: int
    content: str
    token_count: int
    refresh: str | None
    library_default_refresh: str


def _effective_n(candidate: DocumentCandidate) -> int:
    setting = candidate.refresh or candidate.library_default_refresh
    return REFRESH_TO_N[setting]


def apply_cooldown_and_caps(
    candidates: list[DocumentCandidate],
    pti_last_inject: dict[str, int],
    user_msg_index: int,
    token_cap: int,
    doc_cap: int,
) -> tuple[list[KnowledgeContextItem], PtiOverflow | None]:
    """Apply dedupe → cooldown filter → caps."""
    seen_doc_ids: set[str] = set()
    eligible: list[DocumentCandidate] = []
    for c in candidates:
        if c.doc_id in seen_doc_ids:
            continue
        seen_doc_ids.add(c.doc_id)
        n = _effective_n(c)
        last = pti_last_inject.get(c.doc_id)
        if last is not None and (user_msg_index - last) < n:
            continue
        eligible.append(c)

    items: list[KnowledgeContextItem] = []
    dropped_titles: list[str] = []
    running_tokens = 0
    for c in eligible:
        if len(items) >= doc_cap or running_tokens + c.token_count > token_cap:
            dropped_titles.append(c.title)
            continue
        items.append(
            KnowledgeContextItem(
                library_name=c.library_name,
                document_title=c.title,
                heading_path=[],
                preroll_text=None,
                content=c.content,
                score=None,
                source="trigger",
                triggered_by=c.triggered_by,
            )
        )
        running_tokens += c.token_count

    overflow = (
        PtiOverflow(dropped_count=len(dropped_titles), dropped_titles=dropped_titles)
        if dropped_titles
        else None
    )
    return items, overflow
