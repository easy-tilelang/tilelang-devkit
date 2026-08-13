"""Pass-by-pass IR tracing for TVM and TileLang.

Framework adapters are imported lazily so importing :mod:`tilelang_devkit`
does not require or eagerly import TVM or TileLang.
"""

from __future__ import annotations

from contextlib import contextmanager

from tilelang_devkit import __version__

from .api import lower_trace
from .model import (
    LowerRecord,
    STATUS_CODEGEN,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_SKIPPED,
)

_UNSET = object()


def create_pass_instrument(*, mode=None, trace_dir=None, context: int = 3):
    """Create a standalone TVM ``PassInstrument`` trace collector."""
    from .tvm_adapter import create_pass_instrument as _create

    return _create(mode=mode, trace_dir=trace_dir, context=context)


def phase(name):
    """Label standalone TVM pass records created inside this context."""
    from .tvm_adapter import phase as _phase

    return _phase(name)


def enable(*, mode=_UNSET, trace_dir=_UNSET, codegen_output=_UNSET) -> None:
    """Enable tracing for future TileLang compilation sessions."""
    try:
        from .tilelang_adapter import enable as _enable
    except (ImportError, ModuleNotFoundError) as exc:
        raise RuntimeError(
            "lower_trace requires a TileLang build that provides "
            "tilelang.instrumentation"
        ) from exc

    kwargs = {}
    if mode is not _UNSET:
        kwargs["mode"] = mode
    if trace_dir is not _UNSET:
        kwargs["trace_dir"] = trace_dir
    if codegen_output is not _UNSET:
        kwargs["codegen_output"] = codegen_output
    _enable(**kwargs)


def disable() -> None:
    """Disable tracing for future TileLang compilation sessions."""
    try:
        from .tilelang_adapter import disable as _disable
    except (ImportError, ModuleNotFoundError):
        return

    _disable()


def reset() -> None:
    """Reset the active TileLang trace session, if any."""
    try:
        from .tilelang_adapter import reset as _reset
    except (ImportError, ModuleNotFoundError):
        return

    _reset()


@contextmanager
def trace(*, trace_dir=None):
    """Compatibility context manager that traces TileLang in terminal mode."""
    kwargs = {"mode": "terminal"}
    if trace_dir is not None:
        kwargs["trace_dir"] = trace_dir
    enable(**kwargs)
    try:
        yield
    finally:
        disable()


__all__ = [
    "LowerRecord",
    "__version__",
    "STATUS_CODEGEN",
    "STATUS_COMPLETED",
    "STATUS_FAILED",
    "STATUS_SKIPPED",
    "create_pass_instrument",
    "disable",
    "enable",
    "lower_trace",
    "phase",
    "reset",
    "trace",
]
