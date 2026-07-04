"""The user-facing DSL callables, in one place (re-exported by the ``hassle`` pkg).

The top-level :mod:`hassle` package (the import surface bundles use, F3) re-exports
from here. Tests and tools can import the same names from a stable module without
depending on the ``hassle`` package layout. Everything here lives in ``hassle_core``
so it is covered by ``pyright --strict``.
"""

from __future__ import annotations

from hassle_core.compiler import (
    automation,
    delay,
    only_if,
    script,
    service,
    state,
    when,
)

__all__ = [
    "automation",
    "delay",
    "only_if",
    "script",
    "service",
    "state",
    "when",
]
