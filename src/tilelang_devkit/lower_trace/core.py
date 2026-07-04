"""IR Lower Trace — zero-intrusion debug tool for visualizing tilelang compilation passes.

This module is the core of the ``tilelang-devkit`` package. It monkey-patches
``tvm.ir.transform.Pass.__call__`` and tilelang's phase functions to
automatically capture IR before/after every compilation pass, then prints a
unified diff to the terminal and saves the raw IR to disk.

Architecture
============
``enable()`` installs three layers of monkey-patch hooks::

  Layer 1: Pass.__call__ = _traced_pass_call
           Intercept all TVM Pass calls, snapshot before/after IR → diff → record

  Layer 2: phase functions = _wrap_phase(...)
           Set _current_phase so Layer 1 knows which phase each pass belongs to

  Layer 3: codegen FFI = _wrap_codegen_ffi(...)
           Intercept TIR→C++ conversion, capture final IR and generated source

During kernel compilation::

  phase1_LowerAndLegalize()          ← _wrap_phase sets _current_phase
    ├─ Simplify(mod)                 ← _traced_pass_call intercepts
    ├─ LowerTileOp(mod)              ← _traced_pass_call intercepts
    └─ ...
  phase2_OptimizeForTarget()
    ├─ FlattenBuffer(mod)            ← _traced_pass_call intercepts
    └─ ...
  codegen(mod)                       ← _wrap_codegen_ffi intercepts

Usage
=====
::

    from lower_trace import enable, disable

    enable()                    # install hooks, start tracing
    # ... compile your kernel ...
    disable()                   # uninstall hooks, restore original behavior

Or use the context manager::

    from lower_trace import trace

    with trace():
        # ... compile your kernel ...

Output
======
Terminal diff is printed for each pass, and raw IR is saved to::

    ./tmp/lower_trace/run_<timestamp>_<pid>/
    ├── phase1_LowerAndLegalize/
    │   ├── 00_Simplify_before.tir
    │   ├── 00_Simplify_after.tir
    │   └── ...
    ├── phase2_OptimizeForTarget/...
    └── codegen/
        └── NN_codegen_before.tir
        └── NN_codegen_after.cpp

Dependencies
============
This module imports cleanly without tvm/tilelang installed (so ``pip install``
works on any environment). The actual tracing requires tvm + tilelang at
runtime: ``enable()`` raises ``RuntimeError`` if tvm is missing, and degrades
gracefully (no phase labels) if tilelang's engine module is unavailable.
"""

from __future__ import annotations

import contextlib
import difflib
import dis
import functools
import inspect
import os
import re
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .diff import (
    _ANSI_BLUE,
    _ANSI_DIM,
    _ANSI_GREEN,
    _ANSI_RED,
    _ANSI_RESET,
    print_diff,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_TAG = "[lower_trace]"

STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"
STATUS_CODEGEN = "codegen"

_CODEGEN_FFI_NAMES: list[str] = [
    "target.build.tilelang_cuda",
    "target.build.tilelang_cuda_without_compile",
    "target.build.tilelang_cutedsl",
    "target.build.tilelang_cutedsl_without_compile",
    "target.build.tilelang_hip",
    "target.build.tilelang_hip_without_compile",
    "target.build.tilelang_metal",
    "target.build.tilelang_c",
    "target.build.tilelang_c_host",
    "target.build.tilelang_ascend",
    "target.build.tilelang_ascend_pto",
    "target.build.llvm",
    "target.build.webgpu",
    "target.build.tilelang_cpp",
    "target.build.tilelang_webgpu",
]

# ── 全局状态 ──────────────────────────────────────────────────────────────────
# _records: 每次 pass 的记录列表，disable() 时清空
_records: list[LowerRecord] = []

# 原始函数引用：enable() 时保存，disable() 时恢复（保证 monkey-patch 可逆）
_original_pass_call: Callable | None = None
_original_codegen_ffis: dict[str, Callable] = {}
_legacy_patched: bool = False
# (target, attr_name, original_or_MISSING, is_dict) — disable() 据此恢复
_legacy_phase_originals: list[tuple[object, str, object, bool]] = []
_MISSING: object = object()

# 当前 phase 上下文：_wrap_phase 设置，_traced_pass_call 读取
_current_phase: str | None = None
_pass_index: int = 0
_run_dir: str | None = None
_lock = threading.RLock()
_run_counter: int = 0

_UNSCOPED_PHASE = "unscoped"
_DEFAULT_TRACE_DIR = os.path.join(".", "tmp", "lower_trace")
_trace_dir: str = _DEFAULT_TRACE_DIR


@dataclass
class LowerRecord:
    """单次 pass 执行的记录。

    Attributes
    ----------
    phase : str
        所属阶段（如 ``phase1_LowerAndLegalize``、``codegen``、``unscoped``）。
    name : str
        Pass 显示名（如 ``Simplify``、``FlattenBuffer``）。
    index : int
        全局序号（跨 phase 递增）。
    before_text : str
        Pass 执行前的 IR 文本（``str(mod)``）。
    after_text : str
        Pass 执行后的 IR 文本（``str(result)``）；codegen 记录为 C++ 源码。
    changed : bool
        before != after。
    add_lines, del_lines : int
        diff 增删行数。
    status : str
        ``STATUS_COMPLETED`` / ``STATUS_FAILED`` / ``STATUS_CODEGEN``。
    error_msg : str
        失败时的异常信息。
    """

    phase: str
    name: str
    index: int
    before_text: str
    after_text: str
    changed: bool
    add_lines: int = 0
    del_lines: int = 0
    status: str = STATUS_COMPLETED
    error_msg: str = ""


# ── 辅助函数 ──────────────────────────────────────────────────────────────────


def _get_tvm_ffi():
    """返回统一的 FFI 接口（``get_global_func`` / ``register_global_func``）。

    优先用新版 ``tvm.ffi``，回退到 ``3rdparty/tvm`` 的 legacy ``tvm._ffi``
    （注册函数名为 ``register_func`` 而非 ``register_global_func``）。
    """
    try:
        import tvm.ffi as _ffi

        if hasattr(_ffi, "register_global_func") and hasattr(_ffi, "get_global_func"):
            return _ffi
    except ImportError:
        pass
    import tvm._ffi as _ffi

    class _LegacyFFI:
        """Adapter: 在 legacy tvm._ffi 上暴露 register_global_func API。"""

        get_global_func = staticmethod(_ffi.get_global_func)

        @staticmethod
        def register_global_func(name, func=None, override=False):
            return _ffi.register_func(name, func, override=override)

    return _LegacyFFI()


def _inspect_module_source(mod):
    """获取 ``tvm.runtime.Module`` 的源码文本。

    优先 ``inspect_source``（新版），回退 ``get_source``（3rdparty/tvm）。
    用于 codegen 后捕获生成的 C++/CUDA 源码。
    """
    for _attr in ("inspect_source", "get_source"):
        _fn = getattr(mod, _attr, None)
        if callable(_fn):
            return _fn() or ""
    return ""


def _get_pass_display_name(pass_obj) -> str:
    """从 ``pass_info.name`` 提取显示名，如 ``tir.Simplify`` -> ``Simplify``。"""
    try:
        name = str(pass_obj.info.name)
        return name.split(".")[-1] if "." in name else name
    except Exception:
        return type(pass_obj).__name__


def _safe_filename_component(name: str) -> str:
    """净化字符串使其可作为路径组件（防止路径穿越 CWE-22）。"""
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(name))


def _ensure_run_dir() -> str:
    """返回本次 run 的输出目录（首次调用时创建）。

    格式：``<_trace_dir>/run_<timestamp>_<pid>/``
    每次 run 一个新目录，便于区分多次编译。
    """
    global _run_dir

    if _run_dir is not None:
        return _run_dir

    from datetime import datetime

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    _run_dir = os.path.join(_trace_dir, f"run_{timestamp}_{os.getpid()}")
    os.makedirs(_run_dir, exist_ok=True)
    return _run_dir


def _save_raw_files(record: LowerRecord):
    """把 before/after IR 文本落盘。

    路径：``<run_dir>/<phase>/<index>_<name>_before|after.<ext>``

    codegen 记录的 after 是 C++ 源码，扩展名用 ``.cpp``；其余用 ``.tir``。
    落盘是 best-effort：失败只打 warning，不中断编译。
    """
    try:
        trace_dir = _ensure_run_dir()
        phase_dir = os.path.join(trace_dir, _safe_filename_component(record.phase))
        os.makedirs(phase_dir, exist_ok=True)

        prefix = f"{record.index:02d}_{_safe_filename_component(record.name)}"
        before_ext = ".tir"
        after_ext = ".cpp" if record.status == STATUS_CODEGEN else ".tir"
        with open(
            os.path.join(phase_dir, f"{prefix}_before{before_ext}"), "w", encoding="utf-8"
        ) as f:
            f.write(record.before_text)
        with open(
            os.path.join(phase_dir, f"{prefix}_after{after_ext}"), "w", encoding="utf-8"
        ) as f:
            f.write(record.after_text)
    except Exception as exc:
        print(f"  {_ANSI_RED}{_TAG} WARNING: could not save raw trace files: {exc}{_ANSI_RESET}")


def _count_diff(before_text: str, after_text: str) -> tuple[int, int]:
    """用 SequenceMatcher 统计增删行数，返回 (add_count, del_count)。"""
    add_count = del_count = 0
    sm = difflib.SequenceMatcher(None, before_text.splitlines(), after_text.splitlines())
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "insert":
            add_count += j2 - j1
        elif tag == "delete":
            del_count += i2 - i1
        elif tag == "replace":
            add_count += j2 - j1
            del_count += i2 - i1
    return add_count, del_count


# ── Layer 1: 核心 Pass 拦截 ───────────────────────────────────────────────────


def _traced_pass_call(self, mod):
    """★ 核心钩子：拦截所有 ``Pass.__call__`` 调用。

    这是整个工具的心脏。``enable()`` 时 ``Pass.__call__`` 被替换为本函数，
    之后 **所有** TVM Pass 调用（无论在哪个 phase）都会经过这里。

    流程：
      1. 调用前 ``str(mod)`` 拍 before 快照
      2. 分配全局递增序号 ``idx``
      3. 调用原始 ``Pass.__call__``
      4. 调用后 ``str(result)`` 拍 after 快照
      5. 计算 diff 统计 → 构造 ``LowerRecord`` → 落盘 → 终端打印
      6. 如果有变化，打印终端 unified diff

    ``_current_phase`` 由 Layer 2 (``_wrap_phase``) 设置，告诉本函数
    当前 pass 属于哪个阶段。未设置时标记为 ``unscoped``。
    """
    global _pass_index

    phase = _current_phase or _UNSCOPED_PHASE
    before_text = str(mod)

    with _lock:
        idx = _pass_index
        _pass_index += 1

    try:
        result = _original_pass_call(self, mod)
    except Exception as e:
        with _lock:
            record = LowerRecord(
                phase=phase,
                name=_get_pass_display_name(self),
                index=idx,
                before_text=before_text,
                after_text="",
                changed=False,
                status=STATUS_FAILED,
                error_msg=str(e),
            )
            _records.append(record)
            _save_raw_files(record)
            print(f"  {_ANSI_RED}{_TAG} {phase}/{idx:02d}_{record.name}: FAILED ({e}){_ANSI_RESET}")
        raise

    after_text = str(result)
    changed = before_text != after_text
    pass_name = _get_pass_display_name(self)
    add_count, del_count = _count_diff(before_text, after_text) if changed else (0, 0)

    with _lock:
        record = LowerRecord(
            phase=phase,
            name=pass_name,
            index=idx,
            before_text=before_text,
            after_text=after_text,
            changed=changed,
            add_lines=add_count,
            del_lines=del_count,
            status=STATUS_COMPLETED,
        )
        _records.append(record)
        _save_raw_files(record)
        tag = "CHANGED" if changed else "NO-OP"
        tag_color = _ANSI_GREEN if changed else _ANSI_DIM
        print(f"  {_TAG} {phase}/{idx:02d}_{pass_name}: {tag_color}{tag}{_ANSI_RESET}")

    if changed:
        label = f"{phase}/{pass_name}"
        print_diff(before_text, after_text, f"{label} (before)", f"{label} (after)")

    return result


# ── Layer 2: Phase 发现与包装 ─────────────────────────────────────────────────


def _discover_phases(lower_func) -> list:
    """通过字节码扫描发现旧架构的 phase 函数。

    扫描 ``tilelang.engine.lower`` 函数的字节码，找出其引用的
    ``tilelang.engine.phase`` 模块中的 phase 函数
    （如 ``LowerAndLegalize``、``OptimizeForTarget``）。

    原理：``tilelang.engine.lower`` 内部调用各 phase 函数，这些调用在
    字节码中表现为 ``LOAD_GLOBAL <phase_name>``。扫描这些指令即可发现
    所有被引用的 phase 函数。

    按 source line 排序，保证 phase 顺序与定义顺序一致。
    """
    try:
        from tilelang.engine import phase as phase_module
    except ImportError:
        return []

    phase_funcs = []
    seen_names = set()
    try:
        for instr in dis.get_instructions(lower_func):
            if instr.opname == "LOAD_GLOBAL" and instr.argval not in seen_names:
                name = instr.argval
                seen_names.add(name)
                func = getattr(phase_module, name, None)
                if func is not None and callable(func):
                    phase_funcs.append(func)
    except (TypeError, OSError):
        pass

    # 回退：字节码扫描失败时，取 phase 模块所有公共 callable
    if not phase_funcs:
        phase_funcs = [
            getattr(phase_module, name)
            for name in sorted(dir(phase_module))
            if not name.startswith("_") and callable(getattr(phase_module, name, None))
        ]

    def _src_line(f):
        try:
            return inspect.getsourcelines(f)[1]
        except (OSError, TypeError):
            return 999999

    phase_funcs.sort(key=_src_line)
    return phase_funcs


def _wrap_phase(original_func, phase_index, total_phases):
    """包装一个 phase 函数，在调用期间设置 ``_current_phase`` 上下文。

    这样 Layer 1 的 ``_traced_pass_call`` 就知道当前 pass 属于哪个 phase。
    phase 名格式：``phase<N>_<func_name>``（多次 run 时加 ``run<M>_`` 前缀）。

    ``phase_index == 1`` 时递增 ``_run_counter``；非首次 run 时重置 ``_run_dir``
    使后续 pass 落盘到新目录。
    """
    base_phase_name = f"phase{phase_index}_{original_func.__name__}"

    @functools.wraps(original_func)
    def wrapper(*args, **kwargs):
        global _run_counter, _current_phase, _run_dir

        with _lock:
            if phase_index == 1:
                _run_counter += 1
                # 非首次 run 时重置 _run_dir，使新 run 落盘到新目录
                if _run_counter > 1:
                    _run_dir = None
            run_prefix = f"run{_run_counter}_" if _run_counter > 1 else ""
            phase_name = f"{run_prefix}{base_phase_name}"
            _current_phase = phase_name

        try:
            result = original_func(*args, **kwargs)
        except Exception as e:
            with _lock:
                _current_phase = None
                print(f"  {_ANSI_RED}{_TAG} EXCEPTION in {phase_name}: {e}{_ANSI_RESET}")
            raise

        with _lock:
            _current_phase = None
            if phase_index == total_phases:
                print(
                    f"  {_TAG} run {_run_counter} ({phase_name}) complete: {len(_records)} total records"
                )

        return result

    return wrapper


# ── Layer 3: Codegen 拦截（简化版，只捕获不编辑）─────────────────────────────


def _wrap_codegen_ffi(original_build, ffi_name=""):
    """包装 codegen FFI，捕获 TIR-before / C++-after 作为一条 ``STATUS_CODEGEN`` 记录。

    只做 **捕获**：调用 codegen 前后各拍一个快照，记录差异。

    临时设置 ``_current_phase = 'codegen'``，使 codegen 内部的 pass
    （如 ``device_codegen`` 中的 ``tir.transform.Simplify``）也被 Layer 1 捕获，
    并归属于 codegen 阶段。

    Parameters
    ----------
    original_build : Callable
        原始 codegen FFI 函数（如 ``target.build.tilelang_ascend``）。
    ffi_name : str
        FFI 注册名，用于调试日志。
    """

    @functools.wraps(original_build)
    def wrapper(*args, **kwargs):
        global _pass_index, _current_phase

        if _original_pass_call is None:
            return original_build(*args, **kwargs)

        mod = args[0] if args else kwargs.get("mod")
        before_text = str(mod)

        with _lock:
            previous_phase = _current_phase
            _current_phase = "codegen"

        after_text = ""
        try:
            result = original_build(*args, **kwargs)
        except Exception as e:
            with _lock:
                idx = _pass_index
                _pass_index += 1
                record = LowerRecord(
                    phase="codegen",
                    name=getattr(original_build, "__name__", "codegen"),
                    index=idx,
                    before_text=before_text,
                    after_text="",
                    changed=False,
                    status=STATUS_FAILED,
                    error_msg=str(e),
                )
                _records.append(record)
                _save_raw_files(record)
                _current_phase = previous_phase
                print(f"  {_ANSI_RED}{_TAG} codegen/{idx:02d}_codegen: FAILED ({e}){_ANSI_RESET}")
            raise

        try:
            with _lock:
                idx = _pass_index
                _pass_index += 1
            after_text = _inspect_module_source(result)
            add_count, del_count = _count_diff(before_text, after_text)

            with _lock:
                record = LowerRecord(
                    phase="codegen",
                    name="codegen",
                    index=idx,
                    before_text=before_text,
                    after_text=after_text,
                    changed=True,
                    add_lines=add_count,
                    del_lines=del_count,
                    status=STATUS_CODEGEN,
                )
                _records.append(record)
                _save_raw_files(record)
                print(
                    f"  {_TAG} codegen/{idx:02d}_codegen: {_ANSI_BLUE}CODEGEN{_ANSI_RESET} (+{add_count}/-{del_count})"
                )
        except Exception as exc:
            print(f"  {_ANSI_RED}{_TAG} WARNING: post-codegen tracing failed: {exc}{_ANSI_RESET}")
        finally:
            with _lock:
                _current_phase = previous_phase

        print_diff(before_text, after_text, "codegen (TIR before)", "codegen (C++ after)")
        return result

    return wrapper


# ── 启停控制 ──────────────────────────────────────────────────────────────────


def enable(*, trace_dir: str | None = None):
    """安装三层 monkey-patch 钩子，开始跟踪编译 Pass。

    幂等：重复调用不会重复安装。

    Parameters
    ----------
    trace_dir : str, optional
        输出根目录，默认 ``./tmp/lower_trace``。

    Raises
    ------
    RuntimeError
        如果 tvm 未安装。tvm 是 tracing 的硬依赖（Pass.__call__ 拦截需要）。
        请先安装 tilelang（会带 tvm）。
    """
    global _trace_dir, _original_pass_call, _legacy_patched

    if trace_dir is not None:
        _trace_dir = str(trace_dir)

    # tvm 是硬依赖：没有 tvm 无法拦截 Pass.__call__
    try:
        from tvm.ir.transform import Pass
    except ImportError as exc:
        raise RuntimeError(
            "lower_trace requires tvm to enable tracing. "
            "Install tilelang first: pip install tilelang (or use the tilelang-ascend environment)."
        ) from exc

    # Layer 1: 拦截所有 Pass.__call__
    if _original_pass_call is None:
        _original_pass_call = Pass.__call__
        Pass.__call__ = _traced_pass_call

    # Layer 3: 拦截 codegen FFI
    if not _original_codegen_ffis:
        _ffi = _get_tvm_ffi()
        for ffi_name in _CODEGEN_FFI_NAMES:
            try:
                orig = _ffi.get_global_func(ffi_name)
                if orig is not None:
                    wrapped = _wrap_codegen_ffi(orig, ffi_name)
                    _original_codegen_ffis[ffi_name] = orig
                    _ffi.register_global_func(ffi_name, wrapped, override=True)
            except Exception as exc:
                print(f"{_TAG} WARNING: could not wrap codegen FFI {ffi_name}: {exc}")

    if _legacy_patched:
        return

    # Layer 2: 包装 phase 函数（tilelang 专用）
    # tilelang 缺失时降级：Pass 跟踪仍可用（全标 unscoped），但无 phase 标签
    try:
        import tilelang.engine.lower as lower_mod

        lower_func = lower_mod.lower
        patch_mod = lower_mod
    except (ImportError, AttributeError):
        try:
            from tilelang.engine import lower as lower_func

            import tilelang.engine as patch_mod
        except (ImportError, AttributeError) as e:
            print(
                f"{_TAG} WARNING: tilelang engine not found ({e}); phase tracing disabled (passes will be tagged 'unscoped')."
            )
            return

    phase_funcs = _discover_phases(lower_func)
    for i, phase_func in enumerate(phase_funcs):
        wrapped = _wrap_phase(phase_func, i + 1, len(phase_funcs))
        name = phase_func.__name__

        # 在三个位置保存原始引用，disable() 时据此恢复
        _legacy_phase_originals.append((patch_mod, name, getattr(patch_mod, name, _MISSING), False))
        setattr(patch_mod, name, wrapped)
        try:
            from tilelang.engine import phase as phase_module

            if hasattr(phase_module, name):
                _legacy_phase_originals.append(
                    (phase_module, name, getattr(phase_module, name, _MISSING), False)
                )
                setattr(phase_module, name, wrapped)
        except ImportError:
            pass
        glbls = getattr(lower_func, "__globals__", None)
        if glbls is not None and name in glbls:
            _legacy_phase_originals.append((glbls, name, glbls[name], True))
            glbls[name] = wrapped

    _legacy_patched = True
    print(f"{_TAG} IR pass tracing enabled ({len(phase_funcs)} phases, trace_dir={_trace_dir}).")


def disable():
    """卸载所有 monkey-patch 钩子，恢复原始行为。

    完全可逆：恢复 ``Pass.__call__``、codegen FFI、phase 函数，
    清空记录和状态。
    """
    global _original_pass_call, _legacy_patched, _legacy_phase_originals
    global _run_counter, _run_dir, _trace_dir

    if _original_pass_call is not None:
        from tvm.ir.transform import Pass

        Pass.__call__ = _original_pass_call
        _original_pass_call = None

    # 恢复 codegen FFI（仅在实际包装过时才需要 FFI）
    if _original_codegen_ffis:
        _ffi = _get_tvm_ffi()
        for ffi_name, orig in _original_codegen_ffis.items():
            with contextlib.suppress(Exception):
                _ffi.register_global_func(ffi_name, orig, override=True)
        _original_codegen_ffis.clear()

    # 恢复 phase 函数（三个位置）
    for target, name, original, is_dict in _legacy_phase_originals:
        with contextlib.suppress(Exception):
            if original is _MISSING:
                if is_dict:
                    del target[name]
                else:
                    delattr(target, name)
            else:
                if is_dict:
                    target[name] = original
                else:
                    setattr(target, name, original)
    _legacy_phase_originals = []

    _legacy_patched = False
    _run_counter = 0
    _run_dir = None
    _trace_dir = _DEFAULT_TRACE_DIR
    reset()


def reset():
    """清空已收集的记录和 pass 序号。

    ``_run_dir`` 不清空：清空会导致同一次 run 的 pass 分散到多个目录
    （pre-pipeline pass 先于 phase 创建 ``_run_dir``）。
    新 run 的 ``_run_dir`` 由 ``_wrap_phase`` 在 ``_run_counter > 1`` 时重置。
    """
    global _records, _current_phase, _pass_index
    _records = []
    _current_phase = None
    _pass_index = 0


# ── 便捷上下文管理器 ──────────────────────────────────────────────────────────


@contextlib.contextmanager
def trace(*, trace_dir: str | None = None):
    """上下文管理器：``with trace(): ...`` 自动 enable/disable。

    Example::

        with trace():
            kernel = tilelang.jit(func)()
    """
    enable(trace_dir=trace_dir)
    try:
        yield
    finally:
        disable()
