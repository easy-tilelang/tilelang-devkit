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

from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("tilelang-devkit")
except Exception:
    # Fallback for source checkout without installation
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
