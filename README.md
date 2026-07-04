# tilelang-devkit

Developer tooling for [tilelang](https://github.com/TileLang-Ascend).

Currently ships **`lower_trace`** — a zero-intrusion IR pass tracing tool that
monkey-patches TVM's `Pass.__call__` and tilelang's phase functions to
automatically capture IR before/after every compilation pass, then prints a
unified diff to the terminal and saves the raw IR to disk.

## Install

From PyPI (once published):

```bash
pip install tilelang-devkit
```

From source (editable, recommended for development):

```bash
git clone https://github.com/easy-tilelang/tilelang-devkit.git
cd tilelang-devkit
pip install -e .
```

Or install directly from git:

```bash
pip install git+https://github.com/easy-tilelang/tilelang-devkit.git
```

> **Note:** `tilelang-devkit` has zero hard dependencies (Python stdlib only).
> The actual tracing requires `tvm` + `tilelang` at runtime — install tilelang
> first from the [tilelang-ascend](https://github.com/TileLang-Ascend) project.

## Quick start

```python
import tilelang
import tilelang.language as T
from tilelang_devkit.lower_trace import trace

@tilelang.jit(out_idx=[-1])
def vec_add(M, N, block_M, block_N, dtype="float"):
    @T.prim_func
    def main(A: T.Tensor((M, N), dtype), B: T.Tensor((M, N), dtype), C: T.Tensor((M, N), dtype)):
        with T.Kernel(M // block_M, is_npu=True) as (cid,):
            a_ub = T.alloc_ub((block_M, block_N), dtype)
            b_ub = T.alloc_ub((block_M, block_N), dtype)
            c_ub = T.alloc_ub((block_M, block_N), dtype)
            with T.Scope("V"):
                T.copy(A[cid * block_M, 0], a_ub)
                T.copy(B[cid * block_M, 0], b_ub)
                T.barrier_all()
                T.tile.add(c_ub, a_ub, b_ub)
                T.barrier_all()
                T.copy(c_ub, C[cid * block_M, 0])
    return main

with trace():                       # start tracing
    func = vec_add(256, 256, 128, 256)
# hooks auto-removed on exit
```

### Manual enable/disable

```python
from tilelang_devkit.lower_trace import enable, disable

enable()                            # install hooks
func = vec_add(256, 256, 128, 256)  # compile under trace
disable()                           # remove hooks
```

### Custom output directory

```python
with trace(trace_dir="/tmp/my_trace"):
    func = vec_add(256, 256, 128, 256)
```

## Output

### Terminal

Each pass prints a status line and, if the IR changed, a unified diff:

```
  [lower_trace] phase1_LowerAndLegalize/00_InjectTmpBuffer: NO-OP
  [lower_trace] phase1_LowerAndLegalize/03_BufferShapeCollector: CHANGED
  --- phase1_LowerAndLegalize/BufferShapeCollector (before)
  +++ phase1_LowerAndLegalize/BufferShapeCollector (after)
  @@ -5,6 +5,10 @@
   class Module:
       @T.prim_func
       def main(...):
   +        a_ub = T.handle("float32", "shared")
   +        ...
  [lower_trace] codegen/38_codegen: CODEGEN (+54/-22)
```

### Disk

Raw IR files are saved under `./tmp/lower_trace/` (or your `trace_dir`):

```
./tmp/lower_trace/run_<timestamp>_<pid>/
├── phase1_LowerAndLegalize/
│   ├── 00_Simplify_before.tir      # IR before the pass
│   ├── 00_Simplify_after.tir       # IR after the pass
│   └── ...
├── phase2_OptimizeForTarget/
│   └── ...
├── unscoped/                       # passes outside any phase
│   └── ...
└── codegen/
    ├── 38_codegen_before.tir       # final lowered TIR
    └── 38_codegen_after.cpp        # generated C++ source
```

## How it works

`enable()` installs three layers of monkey-patch hooks:

| Layer | Hook | Purpose |
|-------|------|---------|
| 1 | `Pass.__call__ = _traced_pass_call` | Intercept **all** TVM Pass calls — snapshot before/after IR, compute diff, record |
| 2 | phase functions = `_wrap_phase(...)` | Set `_current_phase` so Layer 1 knows which phase each pass belongs to |
| 3 | codegen FFI = `_wrap_codegen_ffi(...)` | Intercept TIR→C++ conversion, capture final IR and generated source |

`disable()` restores all originals (fully reversible).

## API reference (`tilelang_devkit.lower_trace`)

### `trace(*, trace_dir=None)` — context manager
Enables tracing on entry, disables on exit (even on exception).

### `enable(*, trace_dir=None)`
Install hooks. Idempotent. Raises `RuntimeError` if `tvm` is not installed.

### `disable()`
Remove all hooks and restore originals. Clears records.

### `reset()`
Clear collected records without removing hooks.

### `LowerRecord` (dataclass)
Fields: `phase`, `name`, `index`, `before_text`, `after_text`, `changed`, `add_lines`, `del_lines`, `status`, `error_msg`.

### Status constants
`STATUS_COMPLETED`, `STATUS_FAILED`, `STATUS_SKIPPED`, `STATUS_CODEGEN`.

## Graceful degradation

| Environment | Behavior |
|-------------|----------|
| tvm + tilelang | Full tracing (Pass + phase labels + codegen) |
| tvm only | Pass tracing works; all passes tagged `unscoped`; codegen FFI wrapping prints warnings |
| no tvm | `enable()` raises `RuntimeError`; `import tilelang_devkit.lower_trace` still works |

## License

Apache-2.0
