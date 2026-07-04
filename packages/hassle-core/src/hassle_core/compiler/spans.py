"""Source spans — file:line of the DSL call that produced an IR node (M1 test 6).

A span is captured by walking the call stack at record time to the first frame
*outside* the compiler package — i.e. the user's DSL line. Spans ride on IR nodes
as non-serialized metadata (attached in the compiler's span map, never in the
config body), so they never appear in ``to_ha()`` output (that would break I3 and
hashing). DESIGN §7.2.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from types import FrameType


@dataclass(frozen=True)
class SourceSpan:
    """A file:line location in the user's bundle."""

    file: str
    line: int

    def __str__(self) -> str:
        return f"{self.file}:{self.line}"


# Top-level packages that are Hassle machinery (compiler + user-facing DSL shims).
# A frame belonging to one of these is "internal" and is skipped when walking
# outward to the user's DSL line. Matched on the frame's module ``__name__`` so it
# is robust to the repository/checkout path (never on the filename).
_INTERNAL_ROOTS: tuple[str, ...] = ("hassle_core", "hassle")


def _module_name(frame: FrameType) -> str:
    name = frame.f_globals.get("__name__")
    return name if isinstance(name, str) else ""


def _is_internal(frame: FrameType) -> bool:
    root = _module_name(frame).split(".", 1)[0]
    return root in _INTERNAL_ROOTS


def capture_span(depth: int = 0) -> SourceSpan | None:
    """Return the span of the first user (non-Hassle) frame above the caller.

    ``depth`` skips that many additional inner frames before the outward walk
    begins (used when a helper sits between the DSL call and this function).
    """
    # Start above this function (skip our own frame) plus any requested depth.
    frame: FrameType | None = inspect.currentframe()
    try:
        for _ in range(1 + depth):
            if frame is None:
                return None
            frame = frame.f_back
        while frame is not None:
            if not _is_internal(frame):
                return SourceSpan(file=frame.f_code.co_filename, line=frame.f_lineno)
            frame = frame.f_back
    finally:
        del frame
    return None
