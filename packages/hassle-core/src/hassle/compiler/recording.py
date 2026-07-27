"""Recording context: the trace-a-function compiler core (DESIGN §7.2).

A ``@automation`` decorator *registers* a function; the compiler later invokes it
once inside an active :class:`Recorder` context. Inside that context:

- ``when(...)`` appends triggers, ``only_if(...)`` appends conditions,
- action builders (service calls, ``delay``, and — from builder families built
  on top of this seam — ``if_then``/``choose``/``repeat``/…) append actions,

each carrying a source span captured at the call site. The context is a stack (a
``ContextVar``) so nested contexts (``with if_then(...)``) push a child
action target and pop it on exit; plain module-level DSL inside a body
needs no explicit context argument.

This module owns the extension seam other builder families build against
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
    ConditionArgumentTypeError,
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
# here (and widen the frozen DSL surface additively).
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
# Lovelace dashboards (docs/internals/dashboards-design.md §5.2/§6.1): the
# identity kwargs plus HA's dashboard-REGISTRY fields (the registry item minus
# `id`, HA-assigned, and minus `mode`, always "storage"). `@dashboard` declares
# these as explicit keywords, so this allow-list is the same defence-in-depth
# `_AUTOMATION_OPTIONS` is for a programmatic registration.
_DASHBOARD_OPTIONS: frozenset[str] = frozenset(
    {"url_path", "default", "title", "icon", "show_in_sidebar", "require_admin"}
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
    next recorded action lands. ``push_actions`` (used by ``with if_then(...)``)
    pushes a child list and pops it on exit.

    ``_only_if_block_closed_at``: set once a
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
        -- the public seam :func:`record_action`
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


def active_recorder() -> Recorder | None:
    """The innermost active automation/script recorder, or ``None``.

    The read-only counterpart of
    :func:`hassle.compiler.dashboards.recorder.active_dashboard`: the two
    recorders are siblings, and each one's "wrong context" error consults the
    other so the message can name the actual mix-up (dashboards-design §5.6).
    """
    return _active()


def _require_active(call: str, *, span: SourceSpan | None = None) -> Recorder:
    """Return the active recorder, or raise :class:`NoRecordingContextError`.

    ``span=`` lets a caller pre-capture the span at its OWN call site (needed
    when ``_require_active`` is invoked from inside a
    ``@contextlib.contextmanager``-decorated generator -- see
    ``control_flow.py``'s module docstring on the extra contextlib trampoline
    frame -- ``depth=1`` here would otherwise point into ``contextlib.py``
    instead of the user's ``with ...():`` line). Defaults to ``depth=1``
    (this function's immediate caller), correct for every plain-function
    recording verb (``when``/``only_if``/``record_action`` and friends).

    A DASHBOARD body is the one place where "no recording context" has a
    specific, teachable cause -- an automation action/trigger verb used where
    only cards can be recorded -- so the message says so (the §5.6 mirror
    trap). Imported lazily: `recording` is below `dashboards` in the module
    graph and must not depend on it at import time.
    """
    rec = _active()
    if rec is None:
        from hassle.compiler.dashboards.recorder import active_dashboard

        raise NoRecordingContextError(
            call,
            span or capture_span(depth=1),
            in_dashboard=active_dashboard() is not None,
        )
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
    resolved_span = span or capture_span(depth=1)
    # Bool guard: a plain `bool` here is always the classic `==`/`!=` mistake
    # (`only_if(x.state == "on" and other_thing)` collapsing to a bare bool,
    # or simply passing a Python comparison of two ordinary values) -- catch
    # it before it reaches `builder.to_condition()`, which would otherwise
    # raise a bare, unhelpful `AttributeError`.
    #
    # pyright statically sees `bool` can never satisfy `ConditionBuilder`
    # (`to_condition()`), so this looks "unnecessary" against the declared
    # type -- it defends a caller who ignored/couldn't satisfy that
    # annotation at runtime, since Python itself does not enforce it.
    if isinstance(builder, bool):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise ConditionArgumentTypeError("only_if", builder, resolved_span)
    rec.conditions.append(RecordedNode(builder.to_condition(), resolved_span))


def record_action(builder: ActionBuilder, *, span: SourceSpan | None = None) -> None:
    rec = _require_active("action")
    resolved_span = span or capture_span(depth=1)
    # `with only_if(...):` coverage check: once a block has
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
    """The object ``only_if(...)`` returns -- usable bare (unchanged) or as
    ``with only_if(...):`` (DESIGN §5.3/§5.5).

    The conditions are recorded at CALL time (``only_if(...)`` itself), before ``__enter__``
    ever runs -- so the bare-call form is byte-for-byte the pre-existing behavior (a bundle
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

    Dual-form: a bare call (``only_if(cond1, cond2)``, no
    ``with``) keeps the exact pre-existing behavior -- it records the conditions and its return
    value is ignored, exactly as when this returned ``None``. Used as ``with only_if(...):``
    instead, it ALSO requires that every action the automation records lives inside that block --
    HA has no notion of a conditional subset of an automation's actions, so a bare `only_if` call
    that "looks like an empty if" is clarified by making the block form show,
    visually, exactly what it gates: everything.
    """
    span = capture_span(depth=0)
    for cond in conditions:
        record_condition(cond, span=span)
    return OnlyIfBlock(_require_active("only_if"))


@contextlib.contextmanager
def capture_actions() -> Generator[list[dict[str, Any]]]:
    """``with capture_actions() as bodies:`` -- capture a block's actions as
    plain action-body dicts, WITHOUT appending them to the enclosing sequence.

    The public counterpart of ``push_actions`` for ``lib/`` recipe builders
    that cannot legitimately reach the internal ``Recorder``/``RecordedNode``
    seam ``if_then``/``choose`` are built on (docs/internals/compiler-api.md §2):
    a builder wants to record a block of actions once and then splice the
    SAME bodies into one or more containers it assembles itself (e.g. one
    notification action list reused across several ``choose()`` branches
    keyed by which button the user tapped).

    ``bodies`` is a plain ``list[dict[str, Any]]`` -- the same shape every
    action builder's ``to_action()`` produces -- with no ``RecordedNode``/span
    wrapper (those stay compiler-internal); mutate-in-place is intentionally
    not required, callers should treat the yielded list as complete only once
    the ``with`` block exits. Pass it to :func:`emit_actions` to splice the
    bodies into the CURRENT recording context, each re-wrapped with a span
    captured at the ``emit_actions(...)`` call site.

    Requires an active recording context (what/where/fix, same style as
    every other recording verb): raises :class:`NoRecordingContextError`
    otherwise.
    """
    # `depth=2` (not the default 1): this generator is itself
    # `@contextlib.contextmanager`-decorated, so the frame between here and the
    # user's `with capture_actions():` line is contextlib's own
    # `_GeneratorContextManager.__enter__` trampoline -- exactly the depth
    # documented in `control_flow.py`'s module docstring for every construct
    # there, for the same reason.
    span = capture_span(depth=2)
    rec = _require_active("capture_actions", span=span)
    nodes: list[RecordedNode] = []
    captured: list[dict[str, Any]] = []
    with rec.push_actions(nodes):
        yield captured
    captured.extend(n.body for n in nodes)


def emit_actions(bodies: list[dict[str, Any]], *, span: SourceSpan | None = None) -> None:
    """Splice previously captured action bodies (:func:`capture_actions`) into
    the CURRENT recording context.

    Each body is appended, in order, to ``rec.current_actions`` (so this
    respects whatever nested container -- ``if_then``, a ``choose()`` branch,
    etc. -- is active when ``emit_actions`` is called, exactly like a direct
    action-builder call would). Every emitted action gets its OWN span
    captured at the ``emit_actions(...)`` call site (or the given ``span``),
    never the span of the original recording -- so an error later raised
    against an emitted action points at the splice site, not some unrelated
    earlier line. ``bodies`` is read, never consumed: emitting the same
    captured list more than once (e.g. into two different branches) is
    supported and produces independent, equal-but-distinct action entries.

    Requires an active recording context (what/where/fix): raises
    :class:`NoRecordingContextError` otherwise.
    """
    rec = _require_active("emit_actions")
    resolved_span = span or capture_span(depth=1)
    for body in bodies:
        rec.current_actions.append(RecordedNode(dict(body), resolved_span))


def check_options(kind: str, options: dict[str, Any], span: SourceSpan | None) -> None:
    """Reject any option not in HA's automation/script/dashboard option set."""
    allowed = {
        "automation": _AUTOMATION_OPTIONS,
        "dashboard": _DASHBOARD_OPTIONS,
    }.get(kind, _SCRIPT_OPTIONS)
    for key in options:
        if key not in allowed:
            raise UnknownAutomationOptionError(key, sorted(allowed), span)
