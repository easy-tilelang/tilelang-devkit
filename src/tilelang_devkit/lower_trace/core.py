"""Compatibility alias for :mod:`tilelang_devkit.lower_trace.tilelang_adapter`."""

import sys

from . import tilelang_adapter as _implementation

sys.modules[__name__] = _implementation
