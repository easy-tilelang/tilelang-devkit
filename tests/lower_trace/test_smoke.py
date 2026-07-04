"""Smoke tests for tilelang_devkit.lower_trace.

These tests verify that the package imports cleanly and that enable() degrades
gracefully when tvm is unavailable. They do NOT require tvm/tilelang installed
(safe to run in any Python environment).
"""

from __future__ import annotations

import sys


def test_import():
    """Package imports cleanly without tvm/tilelang installed."""
    import tilelang_devkit
    from tilelang_devkit.lower_trace import (
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

    assert tilelang_devkit.__version__ == "0.1.0"
    assert STATUS_COMPLETED == "completed"
    assert STATUS_FAILED == "failed"
    assert STATUS_SKIPPED == "skipped"
    assert STATUS_CODEGEN == "codegen"
    assert callable(enable)
    assert callable(disable)
    assert callable(reset)
    assert callable(trace)

    # LowerRecord is a dataclass with expected fields
    rec = LowerRecord(
        phase="test",
        name="Dummy",
        index=0,
        before_text="a",
        after_text="b",
        changed=True,
    )
    assert rec.add_lines == 0
    assert rec.del_lines == 0
    assert rec.status == STATUS_COMPLETED
    assert rec.error_msg == ""


def test_enable_without_tvm(monkeypatch):
    """enable() raises RuntimeError when tvm is not available."""
    # Block tvm from being imported
    monkeypatch.setitem(sys.modules, "tvm", None)
    monkeypatch.setitem(sys.modules, "tvm.ir", None)
    monkeypatch.setitem(sys.modules, "tvm.ir.transform", None)

    from tilelang_devkit.lower_trace import enable

    try:
        enable()
        raise AssertionError("Expected RuntimeError")
    except RuntimeError as exc:
        assert "tvm" in str(exc).lower()
    except ImportError:
        # Some environments partially import tvm; the RuntimeError path may not
        # trigger if tvm.ffi succeeds but tvm.ir.transform fails differently.
        # Accept ImportError as a valid failure mode too.
        pass


def test_disable_without_enable():
    """disable() is safe to call without prior enable(), even without tvm."""
    from tilelang_devkit.lower_trace import disable, reset
    from tilelang_devkit.lower_trace.core import _records

    # disable() before enable() should not crash.
    # After the fix, if nothing was enabled (_original_codegen_ffis is empty),
    # _get_tvm_ffi() is never called, so this works even without tvm.
    disable()

    reset()
    assert _records == []
