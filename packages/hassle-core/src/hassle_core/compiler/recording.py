"""Recording context: the trace-a-function compiler core (DESIGN §7.2).

A ``@automation`` decorator *registers* a function; the compiler later invokes it
once inside an active :class:`Recorder` context. Inside that context:

- ``when(...)`` appends triggers, ``only_if(...)`` appends conditions,
- action builders (service calls, ``delay``, and — from the follow-on workstream —
  ``if_then``/``choose``/``repeat``/…) append actions,

each carrying a source span captured at the call site. The context is a stack (a
``ContextVar``) so nested contexts (``with if_then(...)`` — a follow-on workstream)
push a child action target and pop it on exit; plain module-level DSL inside a body
needs no explicit context argument.

This module owns the extension seam the other M1 workstreams build against
(``record_trigger``/``record_condition``/``record_action`` + ``push_actions`` for
nested contexts). It does not import any builder family — builders depend on it.
"""

from __future__ import annotations

import contextlib
from collections.abc import Generator
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from hassle_core.compiler.errors import (
    NoRecordingContextError,
    UnknownAutomationOptionError,
)
from hassle_core.compiler.protocols import (
    ActionBuilder,
    ConditionBuilder,
    TriggerBuilder,
)
from hassle_core.compiler.spans import SourceSpan, capture_span

# ---------------------------------------------------------------------------
# HA automation/script option allow-lists (DESIGN §5.3/§5.7). `id`/`alias` are
# always accepted; the rest is HA's automation option surface. New options land
# here (with a MILESTONES note if they widen the F3 surface).
# ---------------------------------------------------------------------------
_AUTOMATION_OPTIONS: frozenset[str] = frozenset(
    {
        "id",
        "alias",
        "description",
        "mode",
        "max",
        "max_exceeded",
        "trigger_variables",
        "variables",
        "initial_state",
    }
)
_SCRIPT_OPTIONS: frozenset[str] = frozenset(
    {"id", "alias", "description", "mode", "max", "max_exceeded", "icon", "fields", "variables"}
)


@dataclass
class RecordedNode:
    """One recorded trigger/condition/action plus its source span."""

    body: dict[str, Any]
    span: SourceSpan | None


# Typed empty-list factories (pyright --strict infers a bare ``list`` factory as
# ``list[Unknown]``; these give it the element type).
def _empty_nodes() -> list[RecordedNode]:
    return []


def _empty_stack() -> list[list[RecordedNode]]:
    return []


@dataclass
class Recorder:
    """Accumulates the triggers/conditions/actions of one automation or script.

    ``action_stack`` is the nested-context target stack: the top list is where the
    next recorded action lands. ``push_actions`` (used by ``with if_then(...)`` in
    the follow-on workstream) pushes a child list and pops it on exit.
    """

    kind: str  # "automation" | "script"
    options: dict[str, Any]
    triggers: list[RecordedNode] = field(default_factory=_empty_nodes)
    conditions: list[RecordedNode] = field(default_factory=_empty_nodes)
    actions: list[RecordedNode] = field(default_factory=_empty_nodes)
    _action_stack: list[list[RecordedNode]] = field(default_factory=_empty_stack)

    def __post_init__(self) -> None:
        self._action_stack = [self.actions]

    @property
    def current_actions(self) -> list[RecordedNode]:
        return self._action_stack[-1]

    @contextlib.contextmanager
    def push_actions(self, target: list[RecordedNode]) -> Generator[None]:
        """Redirect action recording into ``target`` for nested contexts."""
        self._action_stack.append(target)
        try:
            yield
        finally:
            self._action_stack.pop()


_CONTEXT_STACK: ContextVar[tuple[Recorder, ...]] = ContextVar("hassle_recorders", default=())


def _active() -> Recorder | None:
    stack = _CONTEXT_STACK.get()
    return stack[-1] if stack else None


def _require_active(call: str) -> Recorder:
    rec = _active()
    if rec is None:
        raise NoRecordingContextError(call, capture_span(depth=1))
    return rec


@contextlib.contextmanager
def recording(*, kind: str = "automation", **options: Any) -> Generator[Recorder]:
    """Open a recording context. Used by the compiler and by tests.

    Nested calls stack; ``_active()`` returns the innermost recorder.
    """
    rec = Recorder(kind=kind, options=dict(options))
    stack = _CONTEXT_STACK.get()
    token = _CONTEXT_STACK.set((*stack, rec))
    try:
        yield rec
    finally:
        _CONTEXT_STACK.reset(token)


# ---------------------------------------------------------------------------
# Extension seam: the three record functions the builder families call. Each
# captures a span at the DSL call site (depth=1 skips this frame).
# ---------------------------------------------------------------------------
def record_trigger(builder: TriggerBuilder, *, span: SourceSpan | None = None) -> None:
    rec = _require_active("when")
    rec.triggers.append(RecordedNode(builder.to_trigger(), span or capture_span(depth=1)))


def record_condition(builder: ConditionBuilder, *, span: SourceSpan | None = None) -> None:
    rec = _require_active("only_if")
    rec.conditions.append(RecordedNode(builder.to_condition(), span or capture_span(depth=1)))


def record_action(builder: ActionBuilder, *, span: SourceSpan | None = None) -> None:
    rec = _require_active("action")
    rec.current_actions.append(RecordedNode(builder.to_action(), span or capture_span(depth=1)))


# ---------------------------------------------------------------------------
# User-facing recording verbs.
# ---------------------------------------------------------------------------
def when(*triggers: TriggerBuilder) -> None:
    """Register one or more triggers on the active automation (DESIGN §5.3)."""
    span = capture_span(depth=0)
    for trig in triggers:
        record_trigger(trig, span=span)


def only_if(*conditions: ConditionBuilder) -> None:
    """Register one or more conditions on the active automation (DESIGN §5.3)."""
    span = capture_span(depth=0)
    for cond in conditions:
        record_condition(cond, span=span)


def check_options(kind: str, options: dict[str, Any], span: SourceSpan | None) -> None:
    """Reject any option not in HA's automation/script option set (M1 test 5)."""
    allowed = _AUTOMATION_OPTIONS if kind == "automation" else _SCRIPT_OPTIONS
    for key in options:
        if key not in allowed:
            raise UnknownAutomationOptionError(key, sorted(allowed), span)
