"""Framework-neutral trace record types."""

from __future__ import annotations

from dataclasses import dataclass


STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"
STATUS_CODEGEN = "codegen"


@dataclass
class LowerRecord:
    """Result of one compiler pass or code-generation boundary."""

    phase: str
    name: str
    index: int
    before_text: str
    after_text: str
    changed: bool
    add_lines: int = 0
    del_lines: int = 0
    status: str = STATUS_COMPLETED
    error_msg: str = ""
    depth: int = 0
    parent_index: int | None = None
