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
    expr,
    macro,
    only_if,
    param,
    raw_action,
    raw_condition,
    raw_trigger,
    script,
    service,
    shared_script,
    state,
    template,
    when,
)

__all__ = [
    "automation",
    "delay",
    "expr",
    "macro",
    "only_if",
    "param",
    "raw_action",
    "raw_condition",
    "raw_trigger",
    "script",
    "service",
    "shared_script",
    "state",
    "template",
    "when",
]
