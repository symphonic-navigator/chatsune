"""Response-chunk parsers for Kimi K2.5 / K2.6.

Per the driver-layer spec, each driver fully owns its chunk semantics —
the logic in this file is structurally identical to DSv4's Ollama and
Novita parsers but is intentionally NOT imported from there. Duplication
prevents a Kimi change from accidentally affecting DSv4 (and vice versa).
"""
from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from backend.modules.llm._adapters._events import (
    ContentDelta,
    ProviderStreamEvent,
    StreamDone,
    StreamRefused,
    ThinkingDelta,
    ToolCallEvent,
)
from backend.modules.llm._drivers._tool_call_accumulator import (
    ToolCallAccumulator,
)


# Local copy of refusal markers — keeps the driver free of adapter
# internals (per the Driver-Layer spec boundary). Same set as MiMo/DSv4.
_REFUSAL_REASONS: frozenset[str] = frozenset({"content_filter", "refusal"})


def parse_chunk_ollama_cloud(*, chunk: dict[str, Any]) -> list[ProviderStreamEvent]:
    raise NotImplementedError("filled in Task 4")


def parse_chunk_novita(
    *, chunk: dict[str, Any], tool_acc: ToolCallAccumulator,
) -> list[ProviderStreamEvent]:
    raise NotImplementedError("filled in Task 5")
