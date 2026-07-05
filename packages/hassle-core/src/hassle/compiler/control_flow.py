"""Runtime control-flow constructs (DESIGN §5.5) — the actions/control-flow workstream.

Python ``if``/``for`` run at compile time (DESIGN §5.5); *runtime* branching on a
live HA state must go through these context managers, which compile to HA's
``if``/``choose``/``repeat``/``parallel`` action containers. Built entirely on the
extension seam documented in docs/m1-internal-api.md §2
(``Recorder.push_actions``/``current_actions``/``record_action``) — this module
never reaches into ``_CONTEXT_STACK`` and never edits ``recording.py``.

Span depth note (docs/m1-internal-api.md §2 flagged this as unverified): every
construct here is a ``@contextlib.contextmanager``-decorated generator function.
Empirically (see the depth probe run before writing this file), the frame chain
at the point ``capture_span`` is called *inside* such a generator, walking
outward, is:

    0: this generator's own frame (the ``def foo(): ...`` body)      -- internal, skip
    1: contextlib's ``_GeneratorContextManager.__enter__`` trampoline  -- NOT skipped by
       ``_is_internal`` (module root is ``contextlib``, not ``hassle``/``hassle``),
       but it is a frame we must still walk past
    2: the user's ``with foo(...):`` call site                        -- correct target

So ``capture_span(depth=2)`` is correct for every one of these constructs, and
critically the depth requirement does **not** compound under nesting: each
context manager's own ``capture_span(depth=2)`` call is made from its own
generator frame, one contextlib trampoline away from its own call site, no
matter how many other constructs are active above it on the stack. Verified
with a line-pinned test (``test_span_depth_empirical.py``).
"""

from __future__ import annotations

import contextlib
from collections.abc import Generator, Iterable
from typing import Any

from hassle.compiler.action_verbs import _RawAction  # pyright: ignore[reportPrivateUsage]
from hassle.compiler.errors import ElseWithoutIfError
from hassle.compiler.protocols import ConditionBuilder, TriggerBuilder
from hassle.compiler.recording import (
    RecordedNode,
    _require_active,  # pyright: ignore[reportPrivateUsage]
    record_action,
)
from hassle.compiler.spans import capture_span

# The depth verified empirically for every context manager in this module (see
# module docstring). Kept as one named constant so the reasoning lives in one
# place and every construct stays consistent if the machinery ever changes.
_CM_DEPTH = 2

# ``_require_active`` is the extension seam's sanctioned cross-module name
# (docs/m1-internal-api.md §2: "import it from hassle.compiler.recording"),
# underscore-prefixed by module-internal convention rather than by true
# privacy; ``_RawAction`` is this workstream's own adapter, shared between its
# two sibling modules. Both trip pyright's reportPrivateUsage in --strict
# mode, which the imports above suppress once, here, rather than at each call
# site below.


def _condition_body(condition: ConditionBuilder) -> dict[str, Any]:
    return condition.to_condition()


# ---------------------------------------------------------------------------
# if / then / else_if / else_then
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def if_then(
    condition: ConditionBuilder, *, alias: str | None = None, enabled: bool | None = None
) -> Generator[None]:
    """``with if_then(cond): ...`` -> HA ``{"if": [...], "then": [...]}``.

    ``alias=``/``enabled=`` (residue-coverage round 2, docs/ha-api-notes.md
    §20): the UI names/toggles the whole ``if`` block, not just leaf actions.
    Both land on the assembled container body, same key names HA stores.
    """
    rec = _require_active("if_then")
    span = capture_span(depth=_CM_DEPTH)
    then_nodes: list[RecordedNode] = []
    with rec.push_actions(then_nodes):
        yield
    body: dict[str, Any] = {}
    if alias is not None:
        body["alias"] = alias
    body["if"] = [_condition_body(condition)]
    body["then"] = [n.body for n in then_nodes]
    if enabled is not None:
        body["enabled"] = enabled
    rec.current_actions.append(RecordedNode(body, span))


def _last_if_or_choose(call: str, span: Any) -> tuple[Any, dict[str, Any]]:
    """Return (Recorder, body) of the just-recorded ``if``/``choose`` action.

    Raises :class:`ElseWithoutIfError` (what/where/fix, R6) if the immediately
    preceding action in the current list isn't an ``if``/``choose`` container.
    ``span`` is captured by the caller (at its own call site) rather than here,
    so the depth math never has to account for this extra helper frame.
    """
    rec = _require_active(call)
    actions = rec.current_actions
    if not actions:
        raise ElseWithoutIfError(call, span)
    last = actions[-1]
    is_if_or_choose = "if" in last.body or "choose" in last.body
    # An `if`/`choose` whose else-slot (`else`/`default`) is already filled no
    # longer accepts another `else_then`/`else_if` -- the slot is structurally
    # one-shot in HA's schema, so a second call must trap, not silently
    # overwrite (or, for `choose`, silently append another branch after the
    # default that HA would never reach).
    already_closed = "else" in last.body or "default" in last.body
    if not is_if_or_choose or already_closed:
        raise ElseWithoutIfError(call, span)
    return rec, last.body


@contextlib.contextmanager
def else_then() -> Generator[None]:
    """``with else_then(): ...`` attaches to the immediately-preceding ``if``.

    For a preceding ``choose`` (built up via ``else_if`` chaining), attaches as
    the ``default`` branch instead — the two constructs share one trailing-else
    slot in HA's action schema.
    """
    span = capture_span(depth=_CM_DEPTH)
    rec, body = _last_if_or_choose("else_then", span)
    else_nodes: list[RecordedNode] = []
    with rec.push_actions(else_nodes):
        yield
    branch = [n.body for n in else_nodes]
    if "choose" in body:
        body["default"] = branch
    else:
        body["else"] = branch


@contextlib.contextmanager
def else_if(condition: ConditionBuilder) -> Generator[None]:
    """``with else_if(cond): ...`` — chains onto a preceding ``if``/``else_if``.

    Converts a preceding bare ``if`` into HA's ``choose`` form (moving its
    ``then`` into the first ``choose`` branch) so multiple mutually-exclusive
    branches compile to one ``choose`` action, matching
    fixtures/configs/automation_choose_action.json's shape.
    """
    span = capture_span(depth=_CM_DEPTH)
    rec, body = _last_if_or_choose("else_if", span)
    if "if" in body:
        # First else_if: promote the bare `if` into a `choose` with one branch.
        first_branch = {"conditions": body.pop("if"), "sequence": body.pop("then")}
        body["choose"] = [first_branch]
    branch_nodes: list[RecordedNode] = []
    with rec.push_actions(branch_nodes):
        yield
    body["choose"].append(
        {"conditions": [_condition_body(condition)], "sequence": [n.body for n in branch_nodes]}
    )


# ---------------------------------------------------------------------------
# choose(...) / when_(cond) / default()
# ---------------------------------------------------------------------------


class _ChooseBuilder:
    """The object yielded by ``with choose() as c:`` — records branches on it.

    ``with c.when_(cond): ...`` appends a ``{conditions, sequence}`` branch;
    ``with c.default(): ...`` sets the ``default`` sequence (HA allows at most
    one; a second call overwrites, matching "last wins" elsewhere in the DSL).

    ``with c.when_(cond, alias=, enabled=): ...`` (residue-coverage round 3,
    docs/ha-api-notes.md §21): names/toggles *that branch* specifically — the
    HA UI names individual ``choose`` branches, distinct from the whole
    ``choose`` block's own ``alias``/``enabled`` (``choose()``'s kwargs of the
    same name) and from any step's own ``alias``/``enabled`` inside it.
    """

    def __init__(self) -> None:
        self._branches: list[dict[str, Any]] = []
        self._default: list[dict[str, Any]] | None = None

    @contextlib.contextmanager
    def when_(
        self,
        condition: ConditionBuilder,
        *,
        alias: str | None = None,
        enabled: bool | None = None,
    ) -> Generator[None]:
        rec = _require_active("when_")
        nodes: list[RecordedNode] = []
        with rec.push_actions(nodes):
            yield
        branch: dict[str, Any] = {}
        if alias is not None:
            branch["alias"] = alias
        branch["conditions"] = [_condition_body(condition)]
        branch["sequence"] = [n.body for n in nodes]
        if enabled is not None:
            branch["enabled"] = enabled
        self._branches.append(branch)

    @contextlib.contextmanager
    def default(self) -> Generator[None]:
        rec = _require_active("default")
        nodes: list[RecordedNode] = []
        with rec.push_actions(nodes):
            yield
        self._default = [n.body for n in nodes]

    def build_action_body(
        self, *, alias: str | None = None, enabled: bool | None = None
    ) -> dict[str, Any]:
        """Assemble the ``{"choose": [...], "default": [...]}`` action body.

        Not part of the DSL surface a bundle author calls directly (the
        ``choose()`` context manager calls it at ``with`` exit) but not
        underscore-private either, since it is used from the same module just
        outside the class body.

        ``alias=``/``enabled=`` (residue-coverage round 2): forwarded by
        ``choose()``'s own kwargs of the same name.
        """
        body: dict[str, Any] = {}
        if alias is not None:
            body["alias"] = alias
        body["choose"] = self._branches
        if self._default is not None:
            body["default"] = self._default
        if enabled is not None:
            body["enabled"] = enabled
        return body


@contextlib.contextmanager
def choose(*, alias: str | None = None, enabled: bool | None = None) -> Generator[_ChooseBuilder]:
    """``with choose() as c:`` -> HA ``{"choose": [...], "default": [...]}``.

    Matches fixtures/configs/automation_choose_action.json's stored shape
    exactly: a list of ``{conditions, sequence}`` branches plus an optional
    trailing ``default`` sequence.

    ``alias=``/``enabled=`` (residue-coverage round 2, docs/ha-api-notes.md
    §20): names/toggles the whole ``choose`` block.
    """
    rec = _require_active("choose")
    span = capture_span(depth=_CM_DEPTH)
    builder = _ChooseBuilder()
    yield builder
    body = builder.build_action_body(alias=alias, enabled=enabled)
    rec.current_actions.append(RecordedNode(body, span))


# ---------------------------------------------------------------------------
# repeat_count / repeat_while / repeat_until / repeat_for_each
# ---------------------------------------------------------------------------


def _repeat_cm(
    key: str, value: Any, *, alias: str | None = None, enabled: bool | None = None
) -> Any:
    @contextlib.contextmanager
    def _cm() -> Generator[None]:
        rec = _require_active(f"repeat_{key}")
        span = capture_span(depth=_CM_DEPTH)
        nodes: list[RecordedNode] = []
        with rec.push_actions(nodes):
            yield
        body: dict[str, Any] = {}
        if alias is not None:
            body["alias"] = alias
        body["repeat"] = {key: value, "sequence": [n.body for n in nodes]}
        if enabled is not None:
            body["enabled"] = enabled
        rec.current_actions.append(RecordedNode(body, span))

    return _cm()


def repeat_count(n: int, *, alias: str | None = None, enabled: bool | None = None) -> Any:
    """``with repeat_count(3): ...`` -> ``{"repeat": {"count": 3, "sequence": [...]}}``.

    ``alias=``/``enabled=`` (residue-coverage round 2): names/toggles the
    whole ``repeat`` block.
    """
    return _repeat_cm("count", n, alias=alias, enabled=enabled)


def repeat_while(
    condition: ConditionBuilder, *, alias: str | None = None, enabled: bool | None = None
) -> Any:
    """``with repeat_while(cond): ...`` -> HA ``repeat.while`` (list of one condition)."""
    return _repeat_cm("while", [_condition_body(condition)], alias=alias, enabled=enabled)


def repeat_until(
    condition: ConditionBuilder, *, alias: str | None = None, enabled: bool | None = None
) -> Any:
    """``with repeat_until(cond): ...`` -> HA ``repeat.until`` (list of one condition)."""
    return _repeat_cm("until", [_condition_body(condition)], alias=alias, enabled=enabled)


def repeat_for_each(
    items: Iterable[Any], *, alias: str | None = None, enabled: bool | None = None
) -> Any:
    """``with repeat_for_each([...]): ...`` -> HA ``repeat.for_each``."""
    return _repeat_cm("for_each", list(items), alias=alias, enabled=enabled)


# ---------------------------------------------------------------------------
# parallel() / p.branch(...)
# ---------------------------------------------------------------------------

# Sentinel recorded in `parallel()`'s node list in place of a bare action, at
# the position an explicit `p.branch(...)` was opened -- lets the assembly
# step below interleave auto-derived one-action branches and explicit
# multi-step/optioned branches in declaration order without a second parallel
# tracking structure.
_PARALLEL_BRANCH_MARKER = "__hassle_parallel_branch__"


class _ParallelBuilder:
    """The object yielded by ``with parallel() as p:`` (residue-coverage round 3).

    Existing bundles that write ``with parallel(): action(); action()`` with no
    ``as p:`` binding are unaffected — each bare top-level action still becomes
    its own single-action branch, exactly as before (F3-additive). ``with
    p.branch(alias=, enabled=): ...`` is new: it groups one or more steps into
    one explicit branch and optionally names/toggles *that branch* (distinct
    from any of its steps' own ``alias``/``enabled``) — the shape a real
    UI-authored ``parallel`` with a multi-step branch actually stores
    (docs/ha-api-notes.md §21).
    """

    def __init__(self, rec: Any, nodes: list[RecordedNode]) -> None:
        self._rec = rec
        self._nodes = nodes
        self._explicit_branches: dict[int, dict[str, Any]] = {}

    @contextlib.contextmanager
    def branch(self, *, alias: str | None = None, enabled: bool | None = None) -> Generator[None]:
        marker_span = capture_span(depth=_CM_DEPTH)
        marker_index = len(self._nodes)
        self._nodes.append(RecordedNode({_PARALLEL_BRANCH_MARKER: True}, marker_span))
        branch_nodes: list[RecordedNode] = []
        with self._rec.push_actions(branch_nodes):
            yield
        branch: dict[str, Any] = {}
        if alias is not None:
            branch["alias"] = alias
        branch["sequence"] = [n.body for n in branch_nodes]
        if enabled is not None:
            branch["enabled"] = enabled
        self._explicit_branches[marker_index] = branch


@contextlib.contextmanager
def parallel(
    *, alias: str | None = None, enabled: bool | None = None
) -> Generator[_ParallelBuilder]:
    """``with parallel(): ...`` -> HA ``{"parallel": [{"sequence": [...]}, ...]}``.

    Each bare *top-level* action recorded directly in the body becomes its own
    single-action branch (HA runs each list entry in the ``parallel`` array
    concurrently) — matching
    fixtures/configs/automation_parallel_action.json, where each parallel
    branch is a one-action ``sequence``. Bind ``as p:`` and use ``with
    p.branch(alias=, enabled=): ...`` (residue-coverage round 3) for an
    explicit branch grouping multiple steps, or naming/toggling one branch —
    both interleave with bare actions in declaration order.

    ``alias=``/``enabled=`` (residue-coverage round 2, docs/ha-api-notes.md
    §20): names/toggles the whole ``parallel`` block.
    """
    rec = _require_active("parallel")
    span = capture_span(depth=_CM_DEPTH)
    nodes: list[RecordedNode] = []
    builder = _ParallelBuilder(rec, nodes)
    with rec.push_actions(nodes):
        yield builder
    branches: list[dict[str, Any]] = []
    for i, n in enumerate(nodes):
        explicit = builder._explicit_branches.get(i)  # pyright: ignore[reportPrivateUsage]
        if explicit is not None:
            branches.append(explicit)
        elif n.body != {_PARALLEL_BRANCH_MARKER: True}:
            branches.append({"sequence": [n.body]})
    body: dict[str, Any] = {}
    if alias is not None:
        body["alias"] = alias
    body["parallel"] = branches
    if enabled is not None:
        body["enabled"] = enabled
    rec.current_actions.append(RecordedNode(body, span))


# ---------------------------------------------------------------------------
# wait_for(trigger, ...) / wait_template(...)
# ---------------------------------------------------------------------------


def wait_for(
    *triggers: TriggerBuilder,
    timeout: Any = None,
    continue_on_timeout: bool | None = None,
    alias: str | None = None,
    enabled: bool | None = None,
) -> None:
    """Record a ``wait_for_trigger`` action (DESIGN §5.5).

    ``alias=``/``enabled=`` (residue-coverage round 2, docs/ha-api-notes.md
    §20): names/toggles the whole ``wait_for_trigger`` step.
    """
    body: dict[str, Any] = {}
    if alias is not None:
        body["alias"] = alias
    body["wait_for_trigger"] = [t.to_trigger() for t in triggers]
    if timeout is not None:
        body["timeout"] = timeout
    if continue_on_timeout is not None:
        body["continue_on_timeout"] = continue_on_timeout
    if enabled is not None:
        body["enabled"] = enabled
    record_action(_RawAction(body), span=capture_span(depth=0))


def wait_template(
    template: str,
    *,
    timeout: Any = None,
    continue_on_timeout: bool | None = None,
    alias: str | None = None,
    enabled: bool | None = None,
) -> None:
    """Record a ``wait_template`` action (DESIGN §5.5).

    ``alias=``/``enabled=`` (residue-coverage round 2): names/toggles the
    whole ``wait_template`` step.
    """
    body: dict[str, Any] = {}
    if alias is not None:
        body["alias"] = alias
    body["wait_template"] = template
    if timeout is not None:
        body["timeout"] = timeout
    if continue_on_timeout is not None:
        body["continue_on_timeout"] = continue_on_timeout
    if enabled is not None:
        body["enabled"] = enabled
    record_action(_RawAction(body), span=capture_span(depth=0))
