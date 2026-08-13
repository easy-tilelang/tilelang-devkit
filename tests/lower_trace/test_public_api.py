from __future__ import annotations

import os


def _module():
    from tilelang import tvm

    return tvm, tvm.IRModule.from_expr(tvm.tirx.PrimFunc([], tvm.tirx.Evaluate(0)))


def test_standalone_pass_instrument(tmp_path):
    import tilelang_devkit.lower_trace as lt

    tvm, mod = _module()
    instrument = lt.create_pass_instrument(mode="html", trace_dir=str(tmp_path))
    with tvm.transform.PassContext(instruments=[instrument]), lt.phase("simplification"):
        tvm.tirx.transform.Simplify()(mod)

    assert len(instrument.records) == 1
    assert (tmp_path / "tvm" / "report.html").is_file()
    assert instrument.records[0].phase == "simplification"
    assert list((tmp_path / "tvm" / "simplification").glob("*_before.tir"))


def test_package_import_does_not_eagerly_import_tilelang(monkeypatch):
    # This contract is enforced structurally as well: framework adapters are
    # imported only inside their public wrapper functions.
    import subprocess
    import sys

    env = os.environ.copy()
    env.pop("TL_LOWER_TRACE", None)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, tilelang_devkit.lower_trace; assert 'tilelang' not in sys.modules",
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
