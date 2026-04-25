"""In-RAM trigger index for PTI matching.

`TriggerIndex` is a per-session structure mapping normalised phrases to
the document IDs they trigger. `PtiIndexCache` is a process-wide cache
keyed by session_id.

The cache holds plain-text trigger phrases. Future E2EE work will treat
this cache as the decryption boundary: phrases are encrypted at rest and
only ever decrypted into this in-memory structure for matching.
"""

from __future__ import annotations

from threading import RLock

from backend.modules.knowledge._pti_normalisation import normalise


class TriggerIndex:
    """A per-session phrase → doc_ids map."""

    def __init__(self) -> None:
        self.phrase_to_docs: dict[str, list[str]] = {}

    def add(self, phrase: str, doc_id: str) -> None:
        bucket = self.phrase_to_docs.setdefault(phrase, [])
        if doc_id not in bucket:
            bucket.append(doc_id)

    def remove_doc(self, doc_id: str) -> None:
        """Remove all phrase entries for the given document."""
        empty_phrases: list[str] = []
        for phrase, docs in self.phrase_to_docs.items():
            if doc_id in docs:
                docs.remove(doc_id)
                if not docs:
                    empty_phrases.append(phrase)
        for p in empty_phrases:
            del self.phrase_to_docs[p]


class PtiIndexCache:
    """Process-wide cache of TriggerIndex per session, thread-safe via lock."""

    def __init__(self) -> None:
        self._per_session: dict[str, TriggerIndex] = {}
        self._lock = RLock()

    def get(self, session_id: str) -> TriggerIndex | None:
        with self._lock:
            return self._per_session.get(session_id)

    def set(self, session_id: str, index: TriggerIndex) -> None:
        with self._lock:
            self._per_session[session_id] = index

    def invalidate(self, session_id: str) -> None:
        with self._lock:
            self._per_session.pop(session_id, None)

    def drop_session(self, session_id: str) -> None:
        """Alias for invalidate — used when a session ends."""
        self.invalidate(session_id)

    def all_session_ids(self) -> list[str]:
        with self._lock:
            return list(self._per_session.keys())


def match_phrases(
    message: str, index: TriggerIndex
) -> list[tuple[str, str, int]]:
    """Find all phrase hits in `message`.

    Returns a list of (doc_id, matched_phrase, position) tuples sorted
    by position of first occurrence in the normalised message. If a
    phrase maps to multiple docs, every doc is emitted at the same
    position.
    """
    norm = normalise(message)
    hits: list[tuple[str, str, int]] = []
    for phrase, doc_ids in index.phrase_to_docs.items():
        pos = norm.find(phrase)
        if pos >= 0:
            for doc_id in doc_ids:
                hits.append((doc_id, phrase, pos))
    hits.sort(key=lambda x: x[2])
    return hits
