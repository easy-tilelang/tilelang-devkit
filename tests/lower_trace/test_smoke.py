"""Framework-neutral smoke tests for :mod:`tilelang_devkit.lower_trace`."""

from __future__ import annotations


def test_import():
    import tilelang_devkit
    from tilelang_devkit.lower_trace import (
        LowerRecord,
        STATUS_CODEGEN,
        STATUS_COMPLETED,
        STATUS_FAILED,
        STATUS_SKIPPED,
        create_pass_instrument,
        disable,
        enable,
        lower_trace,
        phase,
        reset,
        trace,
    )

    assert tilelang_devkit.__version__ != "0.0.0+unknown"
    assert STATUS_COMPLETED == "completed"
    assert STATUS_FAILED == "failed"
    assert STATUS_SKIPPED == "skipped"
    assert STATUS_CODEGEN == "codegen"
    for value in (create_pass_instrument, disable, enable, lower_trace, phase, reset, trace):
        assert callable(value)

    record = LowerRecord("test", "Dummy", 0, "a", "b", True)
    assert record.status == STATUS_COMPLETED
    assert record.depth == 0
    assert record.parent_index is None


def test_disable_without_enable():
    from tilelang_devkit.lower_trace import disable, reset

    disable()
    reset()
