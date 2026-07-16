"""The `Finding` model — the validator's product surface (DESIGN §9).

Every Finding renders as one what/where/fix paragraph, the same rubric as the
compiler's error messages (`hassle.compiler.errors`), snapshot-tested under
`tests/snapshots/findings/` (mirroring `tests/snapshots/errors/`).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    """One validation finding: *what* / *where* (file:line) / *the fix*.

    ``code`` is a short stable machine-readable identifier (e.g.
    ``"unknown-entity"``) — a distinct Finding type — used by tests and
    (later) `hassle validate --json` to group/filter findings.
    """

    code: str
    severity: str
    file: str | None
    line: int | None
    message: str
    fix: str

    def __str__(self) -> str:
        has_location = self.file is not None and self.line is not None
        where = f" at {self.file}:{self.line}" if has_location else ""
        return f"{self.message}{where} Fix: {self.fix}"
