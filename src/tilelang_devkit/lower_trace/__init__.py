"""lower_trace — zero-intrusion IR pass tracing for tilelang compilation.

Part of the tilelang-devkit package.

Usage::

    from tilelang_devkit.lower_trace import trace

    with trace():
        kernel = tilelang.jit(your_kernel)()
"""

from __future__ import annotations

from .core import (
    LowerRecord,
    STATUS_CODEGEN,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_SKIPPED,
    disable,
    enable,
    reset,
    trace,
)

__all__ = [
    "LowerRecord",
    "STATUS_CODEGEN",
    "STATUS_COMPLETED",
    "STATUS_FAILED",
    "STATUS_SKIPPED",
    "disable",
    "enable",
    "reset",
    "trace",
]
