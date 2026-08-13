"""Environment configuration shared by framework adapters."""

from __future__ import annotations

import os


def parse_mode(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in ("", "0", "false", "no", "off"):
        return None
    if normalized in ("1", "true", "yes", "on"):
        return "html"
    if normalized in ("terminal", "html", "both"):
        return normalized
    return "html"


def env_mode() -> str | None:
    return parse_mode(os.environ.get("TL_LOWER_TRACE"))


def env_trace_dir() -> str:
    return os.environ.get("TL_LOWER_TRACE_DIR", "").strip() or os.path.join(
        ".", "tmp", "lower_trace_dir"
    )
