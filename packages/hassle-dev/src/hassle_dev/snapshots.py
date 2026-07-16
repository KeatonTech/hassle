"""Snapshot helpers shared by the workspace test suites.

Error messages are product surface, so the test suites pin them with text
snapshots. Set ``HASSLE_UPDATE_SNAPSHOTS=1`` to (re)write snapshots instead of
comparing; review the resulting diff like any other golden-file change.
"""

from __future__ import annotations

import os
import re
from pathlib import Path


def check_snapshot(snap_dir: Path, name: str, actual: str) -> None:
    """Compare ``actual`` against ``snap_dir/<name>.txt``.

    Writes the snapshot instead when ``HASSLE_UPDATE_SNAPSHOTS`` is set.
    """
    actual = actual.rstrip("\n")
    path = snap_dir / f"{name}.txt"
    if os.environ.get("HASSLE_UPDATE_SNAPSHOTS"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual + "\n", encoding="utf-8")
    assert path.is_file(), f"missing snapshot {path}; set HASSLE_UPDATE_SNAPSHOTS=1 to write it"
    assert actual == path.read_text(encoding="utf-8").rstrip("\n")


def normalize_error(msg: str, *, mask_lines_for: str | None = None) -> str:
    """Make an error message snapshot-stable.

    Absolute paths are reduced to basenames so snapshots are portable across
    checkouts. When ``mask_lines_for`` names a file (typically the calling test
    file), its line numbers are replaced with ``<line>`` — call-site lines in a
    test file drift with every edit, while line numbers that point into
    tmp-written bundle sources stay exact and remain asserted.
    """
    msg = re.sub(r"(/[^\s:]+/)([^/\s:]+\.py)", r"\2", msg)
    if mask_lines_for is not None:
        msg = re.sub(rf"({re.escape(mask_lines_for)}):\d+", r"\1:<line>", msg)
    return msg
