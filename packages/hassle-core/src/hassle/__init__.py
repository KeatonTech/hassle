"""``hassle`` — the user-facing DSL import surface (DESIGN §5.3).

Bundle files write ``from hassle import automation, when, ...``. This package is
the *public* face of the DSL; the machinery lives in :mod:`hassle_core`. Physical
home (decision, M1): a second top-level package shipped inside the ``hassle-core``
distribution (``packages/hassle-core/src/hassle``), so there is exactly one wheel
to install and the public surface and its implementation version together.

``__all__`` here is the **F3 freeze candidate** declared at the end of M1: additions
are allowed in later milestones, changes are not (R5). It is deliberately minimal —
only the M1-core primitives plus the names the two follow-on M1 workstreams
(triggers/conditions, actions/control-flow) will extend. Each of those adds its own
names to this list in its own PR.
"""

from __future__ import annotations

from hassle_core.compiler import (
    CompileTimeBranchError,
    ElseWithoutIfError,
    automation,
    choose,
    delay,
    else_if,
    else_then,
    event,
    if_then,
    only_if,
    parallel,
    repeat_count,
    repeat_for_each,
    repeat_until,
    repeat_while,
    script,
    service,
    service_ext,
    state,
    stop,
    variables,
    wait_for,
    wait_template,
    when,
)

# F3 freeze candidate (sorted; ruff RUF022). Grouped by role for the reader:
#   decorators: automation, script
#   recording verbs: when, only_if
#   M1-core builders: state, service, delay
#   trap error (assertable by bundles/tests): CompileTimeBranchError
#   control-flow (actions/control-flow workstream, DESIGN §5.5): if_then,
#     else_then, else_if, choose, repeat_count, repeat_while, repeat_until,
#     repeat_for_each, parallel, wait_for, wait_template
#   action primitives: stop, variables, event, service_ext
#   else-without-if trap error: ElseWithoutIfError
__all__ = [
    "CompileTimeBranchError",
    "ElseWithoutIfError",
    "automation",
    "choose",
    "delay",
    "else_if",
    "else_then",
    "event",
    "if_then",
    "only_if",
    "parallel",
    "repeat_count",
    "repeat_for_each",
    "repeat_until",
    "repeat_while",
    "script",
    "service",
    "service_ext",
    "state",
    "stop",
    "variables",
    "wait_for",
    "wait_template",
    "when",
]
