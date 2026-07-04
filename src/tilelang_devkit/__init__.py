"""tilelang-devkit — developer tooling for tilelang.

Currently provides:
  - ``tilelang_devkit.lower_trace``: zero-intrusion IR pass tracing for
    tilelang compilation.

Usage::

    from tilelang_devkit.lower_trace import trace

    with trace():
        kernel = tilelang.jit(your_kernel)()
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
