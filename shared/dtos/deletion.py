"""DTOs for cascading delete reports.

When a persona or knowledge library is deleted, every owning module returns
how many of its records (and physical files) were removed. The handler
collects these into a ``DeletionReportDto`` and returns it to the caller so
the user gets a transparent, line-by-line summary of what privacy data was
actually purged.

Tolerance contract:
- Each module deletes best-effort. Failures are recorded as warnings but
  never abort the cascade — except for "file does not exist" which is
  semantically equivalent to a successful deletion and is NOT a warning.
- ``success`` reflects whether the *target* document itself was removed,
  not whether every sub-step succeeded.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DeletionStepDto(BaseModel):
    """A single line in the deletion report.

    ``label`` is human-readable text such as ``"chat sessions"`` or
    ``"committed memory journal entries"``. ``deleted_count`` is the
    number of records or files that were actually removed in this step.
    ``warnings`` lists any non-fatal issues — typically I/O errors or
    unexpected DB states that were tolerated.
    """

    label: str
    deleted_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class DeletionReportDto(BaseModel):
    """End-to-end report of a cascading delete.

    Returned by the persona and knowledge-library DELETE handlers so the
    frontend can show the user exactly what was purged and what — if
    anything — went wrong along the way.
    """

    target_type: Literal["persona", "knowledge_library"]
    target_id: str
    target_name: str
    success: bool
    steps: list[DeletionStepDto] = Field(default_factory=list)
    timestamp: datetime

    @property
    def total_warnings(self) -> int:
        return sum(len(step.warnings) for step in self.steps)
