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

from hassle.compiler.errors import (
    NoRecordingContextError,
    OnlyIfBlockCoverageError,
    UnknownAutomationOptionError,
)
from hassle.compiler.protocols import (
    ActionBuilder,
    ConditionBuilder,
    TriggerBuilder,
)
from hassle.compiler.spans import SourceSpan, capture_span

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

    ``_only_if_block_closed_at`` (``ux/dsl-ergonomics``, item 1): set once a
    ``with only_if(...):`` block has closed, to the number of top-level actions recorded so far
    (i.e. the block's own actions) -- so :func:`record_action` can reject any FURTHER top-level
    action as "outside the block" (the "all actions inside the block" invariant). ``None`` means
    no block has closed yet (either the bare form was used, or no ``only_if`` at all).
    """

    kind: str  # "automation" | "script"
    options: dict[str, Any]
    triggers: list[RecordedNode] = field(default_factory=_empty_nodes)
    conditions: list[RecordedNode] = field(default_factory=_empty_nodes)
    actions: list[RecordedNode] = field(default_factory=_empty_nodes)
    _action_stack: list[list[RecordedNode]] = field(default_factory=_empty_stack)
    _only_if_block_closed_at: int | None = None

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

    def only_if_block_has_closed(self) -> bool:
        """True once a ``with only_if(...):`` block has closed on this recorder
        (``ux/dsl-ergonomics``, item 1) -- the public seam :func:`record_action`
        uses to check the "all actions inside the block" invariant, so it never
        has to reach into the private ``_only_if_block_closed_at`` field."""
        return self._only_if_block_closed_at is not None

    def close_only_if_block(self) -> None:
        """Mark a ``with only_if(...):`` block as closed, at the current top-level
        action count -- called by :class:`OnlyIfBlock`'s ``__exit__``."""
        self._only_if_block_closed_at = len(self.actions)


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
    resolved_span = span or capture_span(depth=1)
    # `with only_if(...):` coverage check (item 1, ``ux/dsl-ergonomics``): once a block has
    # opened and closed on this recorder, every subsequent TOP-LEVEL action is "outside" it --
    # a nested container's own actions (recorded via `push_actions`, so `current_actions` is not
    # `rec.actions` itself) are unaffected, since they were necessarily opened from inside the
    # block that's still active, or don't interact with `only_if` at all.
    if rec.only_if_block_has_closed() and rec.current_actions is rec.actions:
        raise OnlyIfBlockCoverageError(resolved_span)
    rec.current_actions.append(RecordedNode(builder.to_action(), resolved_span))


# ---------------------------------------------------------------------------
# User-facing recording verbs.
# ---------------------------------------------------------------------------
def when(*triggers: TriggerBuilder) -> None:
    """Register one or more triggers on the active automation (DESIGN §5.3)."""
    span = capture_span(depth=0)
    for trig in triggers:
        record_trigger(trig, span=span)


class OnlyIfBlock:
    """The object ``only_if(...)`` returns -- usable bare (F3, unchanged) or as
    ``with only_if(...):`` (``ux/dsl-ergonomics``, item 1, DESIGN §5.3/§5.5).

    The conditions are recorded at CALL time (``only_if(...)`` itself), before ``__enter__``
    ever runs -- so the bare-call form is byte-for-byte the pre-existing behavior (F3: a bundle
    that never writes ``with`` in front of the call cannot tell this object exists at all,
    since nothing about the recorded IR or the call's side effects changed). ``__enter__`` only
    arms the "every action must be inside this block" check; ``__exit__`` disarms recording and
    leaves a marker so a LATER top-level action (recorded after the block closes) is rejected by
    :func:`record_action`, not silently accepted.

    Only one ``with only_if(...):`` block is meaningful per automation -- there is exactly one
    automation-level conditions list, so a second bare/with call in the same automation still
    just appends more conditions (unchanged), but only the FIRST ``with`` use establishes the
    "actions before this point" baseline; using ``with only_if(...):`` more than once in the
    same automation is unusual but not specially rejected here (the coverage check still holds:
    every action must land after the first block closes and the last block's own actions are,
    definitionally, "inside a block").
    """

    def __init__(self, rec: Recorder) -> None:
        self._rec = rec

    def __enter__(self) -> None:
        # Armed only if no action has been recorded yet at top level (DESIGN: "the block must
        # contain all of the automation's actions" -- an action already recorded before this
        # point can never retroactively become "inside" the block). `depth=0` is correct here
        # (verified empirically, same convention as control_flow.py's module docstring): unlike
        # the `@contextlib.contextmanager`-decorated generators in that module, `OnlyIfBlock` is
        # a plain class -- Python's `with` statement calls `__enter__` directly, with no
        # contextlib trampoline frame to walk past.
        if self._rec.actions:
            raise OnlyIfBlockCoverageError(capture_span(depth=0))

    def __exit__(self, *exc: object) -> None:
        self._rec.close_only_if_block()


def only_if(*conditions: ConditionBuilder) -> OnlyIfBlock:
    """Register one or more conditions on the active automation (DESIGN §5.3).

    Dual-form (``ux/dsl-ergonomics``, item 1): a bare call (``only_if(cond1, cond2)``, no
    ``with``) keeps the exact pre-existing behavior -- it records the conditions and its return
    value is ignored, exactly as when this returned ``None``. Used as ``with only_if(...):``
    instead, it ALSO requires that every action the automation records lives inside that block --
    HA has no notion of a conditional subset of an automation's actions, so a bare `only_if` call
    that "looks like an empty if" (owner feedback) is clarified by making the block form show,
    visually, exactly what it gates: everything.
    """
    span = capture_span(depth=0)
    for cond in conditions:
        record_condition(cond, span=span)
    return OnlyIfBlock(_require_active("only_if"))


def check_options(kind: str, options: dict[str, Any], span: SourceSpan | None) -> None:
    """Reject any option not in HA's automation/script option set (M1 test 5)."""
    allowed = _AUTOMATION_OPTIONS if kind == "automation" else _SCRIPT_OPTIONS
    for key in options:
        if key not in allowed:
            raise UnknownAutomationOptionError(key, sorted(allowed), span)
