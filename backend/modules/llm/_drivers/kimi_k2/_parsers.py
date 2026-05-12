"""Response-chunk parsers for Kimi K2.5 / K2.6.

Per the driver-layer spec, each driver fully owns its chunk semantics —
the logic in this file is structurally identical to DSv4's Ollama and
Novita parsers but is intentionally NOT imported from there. Duplication
prevents a Kimi change from accidentally affecting DSv4 (and vice versa).
"""
from __future__ import annotations

import json  # noqa: F401  # filled in Task 4
from typing import Any
from uuid import uuid4  # noqa: F401  # filled in Task 4

from backend.modules.llm._adapters._events import (
    ContentDelta,  # noqa: F401  # filled in Task 4/5
    ProviderStreamEvent,
    StreamDone,  # noqa: F401  # filled in Task 4/5
    StreamRefused,  # noqa: F401  # filled in Task 4/5
    ThinkingDelta,  # noqa: F401  # filled in Task 4/5
    ToolCallEvent,  # noqa: F401  # filled in Task 4/5
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
