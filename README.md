# tilelang-devkit

Developer tooling for [TileLang](https://github.com/tile-ai/tilelang).

The package currently ships `lower_trace`, a pass-by-pass IR tracing tool built
on TVM `PassInstrument` and TileLang's compilation instrumentation interfaces.
It records raw before/after IR, prints terminal diffs, and generates a
self-contained HTML report without patching TVM globals.

## Install

```bash
pip install tilelang-devkit
```

The package has no hard dependencies. Install it into the Python environment
that already provides the compatible TileLang/TVM build you want to inspect.
Python 3.10 or newer is required.

For development:

```bash
git clone https://github.com/easy-tilelang/tilelang-devkit.git
cd tilelang-devkit
pip install -e '.[dev]'
```

## Trace a complete TileLang compilation

Compatible TileLang versions discover the package through the
`tilelang.instrumentation_tools` entry point:

```bash
TL_LOWER_TRACE=both python kernel.py
```

Supported values are `terminal`, `html`, and `both`. The truthy shorthand
values `1`, `true`, `yes`, and `on` select `html`; `0`, `false`, `no`, and
`off` disable tracing.

Reports are written below `./tmp/lower_trace_dir/<script-name>/` by default.
Select another base directory with:

```bash
TL_LOWER_TRACE=both \
TL_LOWER_TRACE_DIR="$PWD/tmp/lower_trace_dir" \
python kernel.py
```

The latest report is available as `<script-name>/report.html`; immutable run
data lives under `<script-name>/.run_records/run_<timestamp>_<pid>_<id>/`.
If TileLang serves a cached compilation result, no lowering passes execute and
there is nothing new to trace; disable the TileLang kernel cache when you need
a fresh compilation trace.

Tracing can also be controlled from Python:

```python
import tilelang_devkit.lower_trace as lt

lt.enable(mode="both", trace_dir="./traces")
# tilelang.compile(...)
lt.disable()
```

The v0.1 context-manager API remains available and selects terminal mode:

```python
from tilelang_devkit.lower_trace import trace

with trace(trace_dir="./traces"):
    # compile a TileLang kernel
    ...
```

## Trace selected TVM passes

Apply and compare a fixed pass chain:

```python
import tilelang_devkit.lower_trace as lt

results = lt.lower_trace(
    mod,
    [("Simplify", simplify_pass)],
    mode="both",
    html_path="lower-trace.html",
)
```

Or instrument an existing `PassContext`:

```python
from tvm.ir.transform import PassContext
import tilelang_devkit.lower_trace as lt

instrument = lt.create_pass_instrument(mode="html", trace_dir="./traces")
with PassContext(instruments=[instrument]):
    with lt.phase("optimization"):
        # run TVM passes
        ...
instrument.finish()
```

## Public API

- `lower_trace(...)`: run and compare selected passes.
- `create_pass_instrument(...)`: create a standalone TVM pass instrument.
- `phase(name)`: label records produced by the standalone instrument.
- `enable(...)`, `disable()`, `reset()`: control future TileLang sessions.
- `trace(trace_dir=None)`: compatibility context manager.
- `LowerRecord`: one pass or code-generation record.

Importing `tilelang_devkit.lower_trace` does not eagerly import TileLang. The
TileLang-specific adapter is loaded only when its API or plugin entry point is
used.

## License

Apache-2.0
