"""The user-facing DSL callables, in one place (re-exported by the ``hassle`` pkg).

The top-level :mod:`hassle` package (the import surface bundles use, F3) re-exports
from here. Tests and tools can import the same names from a stable module without
depending on the ``hassle`` package layout. Everything here lives in ``hassle_core``
so it is covered by ``pyright --strict``.
"""

from __future__ import annotations

from hassle_core.compiler import (
    automation,
    choose,
    delay,
    else_if,
    else_then,
    event,
    expr,
    if_then,
    macro,
    only_if,
    parallel,
    param,
    raw_action,
    raw_condition,
    raw_trigger,
    repeat_count,
    repeat_for_each,
    repeat_until,
    repeat_while,
    script,
    service,
    service_ext,
    shared_script,
    state,
    stop,
    template,
    variables,
    wait_for,
    wait_template,
    when,
)

__all__ = [
    "automation",
    "choose",
    "delay",
    "else_if",
    "else_then",
    "event",
    "expr",
    "if_then",
    "macro",
    "only_if",
    "parallel",
    "param",
    "raw_action",
    "raw_condition",
    "raw_trigger",
    "repeat_count",
    "repeat_for_each",
    "repeat_until",
    "repeat_while",
    "script",
    "service",
    "service_ext",
    "shared_script",
    "state",
    "stop",
    "template",
    "variables",
    "wait_for",
    "wait_template",
    "when",
]
