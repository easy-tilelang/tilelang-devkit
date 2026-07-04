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

# When a wheel is built from sdist, setuptools-scm re-renders _version.py
# without .git access, causing __commit__/__commit_date__ to become "None".
# Fall back to scm_version.json which is correctly preserved from the sdist
# build step (it lives in the dist-info metadata directory).
if __commit__ in (None, "None") or __commit_date__ in (None, "None"):
    try:
        import json as _json
        from importlib.metadata import distribution as _distribution

        _meta = _distribution("tilelang-devkit").read_text("scm_version.json")
        if _meta is not None:
            _scm = _json.loads(_meta)
            if __commit__ in (None, "None"):
                __commit__ = _scm.get("node", "unknown")
            if __commit_date__ in (None, "None"):
                __commit_date__ = _scm.get("node_date", "unknown")
    except Exception:
        pass

__all__ = ["__commit__", "__commit_date__", "__version__"]
