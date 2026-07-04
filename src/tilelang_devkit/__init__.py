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

try:
    from ._version import __commit__ as __commit__
    from ._version import __commit_date__ as __commit_date__
    from ._version import __version__ as __version__
except ImportError:
    # Fallback when _version.py hasn't been generated yet (e.g. bare clone
    # without pip install, or building from a zip without .git).
    __version__ = "0.0.0+unknown"
    __commit__ = "unknown"
    __commit_date__ = "unknown"

__all__ = ["__commit__", "__commit_date__", "__version__"]
