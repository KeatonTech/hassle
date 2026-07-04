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
    automation,
    delay,
    only_if,
    script,
    service,
    state,
    when,
)

# F3 freeze candidate (sorted; ruff RUF022). Grouped by role for the reader:
#   decorators: automation, script
#   recording verbs: when, only_if
#   M1-core builders: state, service, delay
#   trap error (assertable by bundles/tests): CompileTimeBranchError
__all__ = [
    "CompileTimeBranchError",
    "automation",
    "delay",
    "only_if",
    "script",
    "service",
    "state",
    "when",
]
