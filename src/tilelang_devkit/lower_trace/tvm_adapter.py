"""Standalone adapter for public TVM ``PassInstrument`` APIs."""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Generator

from .api import _import_tvm
from .config import env_mode, env_trace_dir, parse_mode
from .diff import print_diff
from .html import generate_html
from .model import LowerRecord, STATUS_FAILED


_current_phase: ContextVar[str] = ContextVar("tilelang_devkit.lower_trace_phase", default="unscoped")


@contextmanager
def phase(name: str) -> Generator[None, None, None]:
    """Attach a phase label to standalone TVM pass records."""
    token = _current_phase.set(str(name))
    try:
        yield
    finally:
        _current_phase.reset(token)


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", value.rsplit(".", 1)[-1])


def _line_changes(before: str, after: str) -> tuple[int, int]:
    import difflib

    additions = deletions = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
        None, before.splitlines(), after.splitlines()
    ).get_opcodes():
        if tag in ("insert", "replace"):
            additions += j2 - j1
        if tag in ("delete", "replace"):
            deletions += i2 - i1
    return additions, deletions


@dataclass
class _Frame:
    phase: str
    name: str
    before: str
    index: int
    depth: int
    parent_index: int | None


class StandaloneTrace:
    """User-facing owner for a TVM pass instrument and its trace records."""

    def __init__(self, *, mode: str | None, trace_dir: str, context: int) -> None:
        self.mode = mode
        self.trace_dir = trace_dir
        self.context = context
        self.records: list[LowerRecord] = []
        self._stack: list[_Frame] = []
        self._next_index = 0
        self._finished = False
        self.instrument = self._build_instrument()

    def _build_instrument(self):
        tvm = _import_tvm()
        owner = self

        @tvm.ir.instrument.pass_instrument
        class LowerTraceInstrument:
            def run_before_pass(self, mod, info):
                index = owner._next_index
                owner._next_index += 1
                owner._stack.append(
                    _Frame(
                        phase=_current_phase.get(),
                        name=str(info.name).rsplit(".", 1)[-1],
                        before=mod.script(),
                        index=index,
                        depth=len(owner._stack),
                        parent_index=owner._stack[-1].index if owner._stack else None,
                    )
                )

            def run_after_pass(self, mod, info):
                if not owner._stack:
                    return
                frame = owner._stack.pop()
                after = mod.script()
                additions, deletions = _line_changes(frame.before, after)
                record = LowerRecord(
                    phase=frame.phase,
                    name=frame.name,
                    index=frame.index,
                    before_text=frame.before,
                    after_text=after,
                    changed=additions > 0 or deletions > 0,
                    add_lines=additions,
                    del_lines=deletions,
                    depth=frame.depth,
                    parent_index=frame.parent_index,
                )
                owner.records.append(record)
                owner.records.sort(key=lambda item: item.index)
                owner._write_raw(record)
                if owner.mode in ("terminal", "both") and record.changed:
                    print_diff(
                        record.before_text,
                        record.after_text,
                        f"{record.name} (before)",
                        f"{record.name} (after)",
                        context=owner.context,
                    )
                owner._flush_html()

            def exit_pass_ctx(self):
                owner._record_incomplete()
                owner.finish()

        return LowerTraceInstrument()

    def _write_raw(self, record: LowerRecord) -> None:
        output_dir = os.path.join(self.trace_dir, "tvm", _safe_name(record.phase))
        os.makedirs(output_dir, exist_ok=True)
        prefix = f"{record.index:02d}_{_safe_name(record.name)}"
        with open(os.path.join(output_dir, prefix + "_before.tir"), "w", encoding="utf-8") as file:
            file.write(record.before_text)
        with open(os.path.join(output_dir, prefix + "_after.tir"), "w", encoding="utf-8") as file:
            file.write(record.after_text)

    def _record_incomplete(self) -> None:
        while self._stack:
            frame = self._stack.pop()
            record = LowerRecord(
                phase=frame.phase,
                name=frame.name,
                index=frame.index,
                before_text=frame.before,
                after_text="",
                changed=False,
                status=STATUS_FAILED,
                error_msg="pass did not complete",
                depth=frame.depth,
                parent_index=frame.parent_index,
            )
            self.records.append(record)
            self.records.sort(key=lambda item: item.index)
            self._write_raw(record)

    def _flush_html(self) -> None:
        if self.mode not in ("html", "both") or not self.records:
            return
        output_dir = os.path.join(self.trace_dir, "tvm")
        os.makedirs(output_dir, exist_ok=True)
        generate_html(self.records, os.path.join(output_dir, "report.html"))

    def finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        self._flush_html()

    def __getattr__(self, name):
        return getattr(self.instrument, name)


def create_pass_instrument(*, mode=None, trace_dir=None, context: int = 3):
    """Return a TVM pass instrument with a public ``finish()`` helper."""
    resolved_mode = env_mode() if mode is None else parse_mode(mode)
    if resolved_mode is None:
        resolved_mode = "html"
    owner = StandaloneTrace(
        mode=resolved_mode,
        trace_dir=trace_dir or env_trace_dir(),
        context=context,
    )
    # TVM requires the decorated runtime object, so expose owner state through
    # attributes on that object rather than returning a Python proxy.
    instrument = owner.instrument
    instrument.finish = owner.finish
    instrument.records = owner.records
    instrument.trace_owner = owner
    return instrument
