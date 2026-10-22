"""Validate an installed release wheel outside the source tree."""

from __future__ import annotations

import argparse
from datetime import date
from importlib.metadata import distribution
from importlib.resources import files
import re
import sys

from packaging.version import Version


def verify(tag: str, commit: str) -> None:
    import tilelang_devkit

    if not tag.startswith("v"):
        raise ValueError("Release tag must start with v")
    expected = Version(tag[1:])
    dist = distribution("tilelang-devkit")
    if Version(dist.version) != expected or Version(tilelang_devkit.__version__) != expected:
        raise ValueError(f"Installed version {dist.version} does not match tag {tag}")

    node = str(tilelang_devkit.__commit__).removeprefix("g")
    if not re.fullmatch(r"[0-9a-f]{7,40}", node) or not commit.startswith(node):
        raise ValueError(f"Installed commit {node!r} does not match {commit}")
    date.fromisoformat(str(tilelang_devkit.__commit_date__))

    if not files("tilelang_devkit").joinpath("py.typed").is_file():
        raise ValueError("Installed wheel is missing py.typed")
    entries = [
        entry for entry in dist.entry_points
        if entry.group == "tilelang.instrumentation_tools" and entry.name == "lower_trace"
    ]
    if len(entries) != 1 or entries[0].value != "tilelang_devkit.lower_trace:activate":
        raise ValueError("Installed wheel has an incorrect lower_trace entry point")
    if not callable(entries[0].load()):
        raise ValueError("Installed lower_trace entry point is not callable")
    if "tilelang" in sys.modules:
        raise ValueError("Loading the entry point eagerly imported TileLang")
    print(f"Verified tilelang-devkit {dist.version} from {node}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    verify(args.tag, args.commit)
