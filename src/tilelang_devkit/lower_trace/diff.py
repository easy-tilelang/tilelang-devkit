"""Terminal diff utilities for lower_trace.

Provides unified diff generation with optional ANSI color output, used by
``core._traced_pass_call`` and ``core._wrap_codegen_ffi`` to print before/after
IR diffs to stdout.

This module is self-contained (only depends on ``difflib`` from the stdlib) so
it can be imported without tvm/tilelang installed.
"""

from __future__ import annotations

import difflib

# ── ANSI color codes ──────────────────────────────────────────────────────────
# Used to colorize terminal diff output: red for deletions, green for additions,
# cyan for hunk headers, bold for file headers.
_ANSI_RESET = "\033[0m"
_ANSI_RED = "\033[31m"
_ANSI_GREEN = "\033[32m"
_ANSI_YELLOW = "\033[33m"
_ANSI_BLUE = "\033[34m"
_ANSI_CYAN = "\033[36m"
_ANSI_BOLD = "\033[1m"
_ANSI_DIM = "\033[2m"


def unified_diff(
    before_text: str,
    after_text: str,
    before_label: str = "before",
    after_label: str = "after",
    context: int = 3,
    color: bool = True,
) -> str:
    """Generate a unified diff string, optionally with terminal ANSI colors.

    Parameters
    ----------
    before_text, after_text : str
        The text to compare.
    before_label, after_label : str
        Labels for the ``---``/``+++`` file headers.
    context : int
        Number of context lines around each change (default 3).
    color : bool
        If True, wrap diff lines in ANSI color codes.
    """
    before_lines = before_text.splitlines(keepends=True)
    after_lines = after_text.splitlines(keepends=True)

    diff = list(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=before_label,
            tofile=after_label,
            n=context,
        )
    )

    if not diff:
        return ""

    if not color:
        return "".join(diff)

    colored = []
    for line in diff:
        if line.startswith("---") or line.startswith("+++"):
            colored.append(f"{_ANSI_BOLD}{line}{_ANSI_RESET}")
        elif line.startswith("@@"):
            colored.append(f"{_ANSI_CYAN}{line}{_ANSI_RESET}")
        elif line.startswith("-"):
            colored.append(f"{_ANSI_RED}{line}{_ANSI_RESET}")
        elif line.startswith("+"):
            colored.append(f"{_ANSI_GREEN}{line}{_ANSI_RESET}")
        else:
            colored.append(line)

    return "".join(colored)


def print_diff(
    before_text: str,
    after_text: str,
    before_label: str = "before",
    after_label: str = "after",
    context: int = 3,
    color: bool = True,
) -> bool:
    """Print a unified diff to stdout. Returns True if there were differences.

    Convenience wrapper around :func:`unified_diff` that prints the result and
    returns a boolean indicating whether any changes were detected.
    """
    result = unified_diff(before_text, after_text, before_label, after_label, context, color)
    if result:
        print(result, end="")
        return True
    return False
