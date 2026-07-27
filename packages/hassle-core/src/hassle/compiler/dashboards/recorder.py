"""The dashboard recorder — a sibling of the automation ``Recorder`` (§6.1).

The automation :class:`~hassle.compiler.recording.Recorder` (triggers /
conditions / actions + one action stack) is the wrong shape for a card TREE, and
widening it would couple every automation code path to dashboard concerns.
:class:`DashboardRecorder` is therefore its own small recorder, following the
established conventions one-for-one:

- the config dict under construction plus a **container stack**
  (dashboard -> view -> section/container-card -> cards);
- its own ``ContextVar`` stack -- nested ``@dashboard`` tracing is impossible in
  practice, but the ContextVar convention buys the same isolation and
  reentrancy the automation recorder has;
- :func:`record_card` / :func:`push_container`, the non-public extension seam
  every ``hassle.cards`` builder drives, mirroring ``record_action`` /
  ``Recorder.push_actions`` (dsl-extensions.md's seam list);
- every recorded card/view/section/badge carries a
  :class:`~hassle.compiler.spans.SourceSpan` sidecar, addressable by PATH
  (:meth:`DashboardRecorder.node_spans`), so tier-2 validation findings point at
  the author's own line.

Span depth note: every structural context manager here and in
:mod:`hassle.compiler.dashboards.structure` is a
``@contextlib.contextmanager``-decorated generator, so it captures its own span
at :data:`_CM_DEPTH` -- the exact convention and empirical frame-chain analysis
documented in ``hassle/compiler/control_flow.py``'s module docstring, and
re-verified against these real constructs by
``tests/test_dashboard_span_depth_empirical.py``. The requirement does not
compound under nesting: each construct's ``capture_span`` call is made from its
own generator frame, one contextlib trampoline away from its own call site.
"""

from __future__ import annotations

import contextlib
from collections.abc import Generator
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from hassle.compiler.dashboards.errors import (
    DashboardNestingError,
    NoDashboardContextError,
    SectionRequiredError,
)
from hassle.compiler.spans import SourceSpan

# The depth verified empirically for every `@contextlib.contextmanager` in the
# dashboard vocabulary (see the module docstring). One named constant so the
# reasoning lives in one place and every construct -- including DB3's card
# builders -- stays consistent if the machinery ever changes.
_CM_DEPTH = 2

# Container roles, in nesting order.
DASHBOARD_ROLE = "dashboard"
VIEW_ROLE = "view"
SECTION_ROLE = "section"
CARD_ROLE = "card"

#: The view types that store a `sections` list rather than a flat `cards` list.
SECTIONS_VIEW_TYPE = "sections"


def _empty_nodes() -> list[RecordedNode]:
    return []


@dataclass
class RecordedNode:
    """One recorded view / section / card / badge plus its source span.

    ``body`` is the dict as it will be stored by HA. Container nodes own it by
    REFERENCE (their children are spliced into it when their context manager
    exits), which is why :func:`record_card` never copies -- the ``raw_*`` verbs
    copy the caller's dict themselves before handing it over.
    """

    body: dict[str, Any]
    span: SourceSpan | None
    #: The key children are emitted under (``"views"``/``"sections"``/
    #: ``"cards"``/…), also the span-path segment for them. ``None`` for a leaf.
    child_key: str | None = None
    children: list[RecordedNode] = field(default_factory=_empty_nodes)
    badges: list[RecordedNode] = field(default_factory=_empty_nodes)


@dataclass
class ContainerFrame:
    """One entry on the recorder's container stack."""

    role: str
    #: Human-readable, used verbatim in placement errors ("a `masonry` view").
    label: str
    node: RecordedNode
    #: For ``role == VIEW_ROLE``: the resolved ``type`` value (``None`` means the
    #: legacy-masonry storage shape, i.e. no ``type`` key at all).
    view_type: str | None = None


def _empty_frames() -> list[ContainerFrame]:
    return []


@dataclass
class DashboardRecorder:
    """Accumulates one dashboard's view/card tree.

    ``options`` are the ``@dashboard(...)`` keywords, carried verbatim for the
    envelope builder (``hassle.compiler.dashboards.decorators``); this class
    itself only ever assembles the ``config`` half.
    """

    options: dict[str, Any]
    root: RecordedNode = field(
        default_factory=lambda: RecordedNode(body={}, span=None, child_key="views")
    )
    _stack: list[ContainerFrame] = field(default_factory=_empty_frames)

    def __post_init__(self) -> None:
        self._stack = [
            ContainerFrame(role=DASHBOARD_ROLE, label="the `@dashboard` body", node=self.root)
        ]

    # -- stack -------------------------------------------------------------
    @property
    def current(self) -> ContainerFrame:
        """The innermost open container -- where the next node lands."""
        return self._stack[-1]

    @property
    def depth(self) -> int:
        """Number of open containers, the dashboard root frame included."""
        return len(self._stack)

    @contextlib.contextmanager
    def push(self, frame: ContainerFrame) -> Generator[ContainerFrame]:
        """Redirect recording into ``frame`` for a nested container.

        The dashboard analogue of ``Recorder.push_actions``; the public seam
        card builders use is :func:`push_container`, which is built on this.
        """
        self._stack.append(frame)
        try:
            yield frame
        finally:
            self._stack.pop()

    # -- output ------------------------------------------------------------
    def build_config(self) -> dict[str, Any]:
        """The Lovelace view config -- the ``config`` half of the §3.2 envelope."""
        return {"views": [node.body for node in self.root.children]}

    def node_spans(self) -> dict[str, SourceSpan]:
        """Every recorded node's span, keyed by its PATH inside ``config``.

        Path grammar (frozen with F5, consumed by DB7's validation findings and
        by the decompiler): dot-joined ``<key>[<index>]`` segments relative to
        the dashboard's ``config``, e.g. ``views[0]``, ``views[0].badges[1]``,
        ``views[0].sections[0].cards[2]``, ``views[0].cards[0].cards[1]`` for a
        card nested in a container card. Nodes whose span could not be captured
        are omitted rather than mapped to ``None``.
        """
        out: dict[str, SourceSpan] = {}
        _collect_spans(self.root, prefix="", into=out)
        return out


def _collect_spans(node: RecordedNode, *, prefix: str, into: dict[str, SourceSpan]) -> None:
    for index, badge_node in enumerate(node.badges):
        path = f"{prefix}badges[{index}]"
        if badge_node.span is not None:
            into[path] = badge_node.span
    key = node.child_key
    if key is None:
        return
    for index, child in enumerate(node.children):
        path = f"{prefix}{key}[{index}]"
        if child.span is not None:
            into[path] = child.span
        _collect_spans(child, prefix=f"{path}.", into=into)


# ---------------------------------------------------------------------------
# ContextVar stack (mirrors `recording._CONTEXT_STACK`)
# ---------------------------------------------------------------------------
_CONTEXT_STACK: ContextVar[tuple[DashboardRecorder, ...]] = ContextVar(
    "hassle_dashboard_recorders", default=()
)


def active_dashboard() -> DashboardRecorder | None:
    """The innermost active dashboard recorder, or ``None``.

    Also the flag :mod:`hassle.compiler.recording` consults to tell an author
    who used an automation action verb inside a ``@dashboard`` body what went
    wrong (the §5.6 mirror trap).
    """
    stack = _CONTEXT_STACK.get()
    return stack[-1] if stack else None


def reset_dashboard_context() -> None:
    """Drop any leftover recorder stack (per-compile reset, defensive)."""
    _CONTEXT_STACK.set(())


def _require_active(what: str, *, span: SourceSpan | None) -> DashboardRecorder:
    """Return the active dashboard recorder or raise :class:`NoDashboardContextError`.

    ``what`` is a noun phrase naming the verb for the error message
    (``"`raw_card()`"``, ``"A card builder"``). ``span=`` is always supplied by
    the caller: every dashboard verb is either a
    ``@contextlib.contextmanager`` generator (whose own frame would otherwise be
    reported) or captures at its own call site anyway.
    """
    rec = active_dashboard()
    if rec is None:
        from hassle.compiler.recording import active_recorder

        raise NoDashboardContextError(what, span, in_automation=active_recorder() is not None)
    return rec


@contextlib.contextmanager
def dashboard_recording(**options: Any) -> Generator[DashboardRecorder]:
    """Open a dashboard recording context. Used by the compiler and by tests.

    Nested calls stack; :func:`active_dashboard` returns the innermost one --
    the same contract ``hassle.compiler.recording.recording`` has.
    """
    rec = DashboardRecorder(options=dict(options))
    stack = _CONTEXT_STACK.get()
    token = _CONTEXT_STACK.set((*stack, rec))
    try:
        yield rec
    finally:
        _CONTEXT_STACK.reset(token)


# ---------------------------------------------------------------------------
# Extension seam: what every card builder calls (mirrors `record_action` /
# `push_actions`). Non-public -- documented in dsl-extensions.md's seam list.
# ---------------------------------------------------------------------------
def record_card(
    body: dict[str, Any], *, span: SourceSpan | None, what: str = "A card builder"
) -> RecordedNode:
    """Record one card into the innermost open container.

    Takes OWNERSHIP of ``body`` (it is not copied): a container card's builder
    keeps mutating the same dict after its children are collected, and the
    ``raw_*`` verbs copy the caller's dict themselves before calling this.
    Returns the created node so a container builder can attach children to it.

    Placement discipline (§5.2): a card straight in the ``@dashboard`` body has
    no view to live in (:class:`DashboardNestingError`), and a card directly
    under a ``sections`` view has no section to live in
    (:class:`SectionRequiredError`).

    ``what`` names the calling verb for the "no dashboard context" message; a
    builder should pass its own spelling (``"`c.tile()`"``).
    """
    rec = _require_active(what, span=span)
    frame = rec.current
    if frame.role == DASHBOARD_ROLE:
        raise DashboardNestingError(
            "A card",
            "directly in the `@dashboard` body",
            "A dashboard stores its cards inside views, so a card at the top level has "
            "nowhere to be written.",
            'open a view first -- `with view(title="..."):` -- and record the card inside '
            "it (inside a `with section():` too, for the default `sections` view type).",
            span,
        )
    if frame.role == VIEW_ROLE and frame.view_type == SECTIONS_VIEW_TYPE:
        raise SectionRequiredError(span)
    node = RecordedNode(body=body, span=span)
    frame.node.children.append(node)
    return node


def record_badge(body: dict[str, Any], *, span: SourceSpan | None) -> RecordedNode:
    """Record one badge into the innermost open VIEW (§5.2).

    Badges belong to a view, never to a section or a card, so anything other
    than a view frame is a :class:`DashboardNestingError`.
    """
    rec = _require_active("`badge()`", span=span)
    frame = rec.current
    if frame.role != VIEW_ROLE:
        raise DashboardNestingError(
            "A badge",
            f"in {frame.label}",
            "HA stores badges on the view itself, in its own `badges` list -- sections and "
            "cards have no badge list at all.",
            "move the `badge(...)` call up so it sits directly inside the `with view(...):` block.",
            span,
        )
    node = RecordedNode(body=body, span=span)
    frame.node.badges.append(node)
    return node


@contextlib.contextmanager
def push_container(
    body: dict[str, Any],
    *,
    label: str,
    span: SourceSpan | None,
    child_key: str = "cards",
    assign: bool = True,
) -> Generator[RecordedNode]:
    """Record ``body`` as a container CARD and collect its children into it.

    The seam every container-card builder (``c.vertical_stack``, ``c.grid``,
    ``c.conditional``, ``c.entity_filter``, …) is implemented on top of, and the
    reason a third-party builder pack needs no recorder access of its own:

    - ``body`` is placed in the current frame through :func:`record_card`, so
      it obeys exactly the same placement discipline a leaf card does;
    - subsequent ``record_card`` calls land inside it;
    - on clean exit, ``body[child_key]`` is set to the children's bodies, in
      order. Pass ``assign=False`` when the builder wants to place the children
      itself (e.g. a `conditional` card's single ``card:`` key, or an arity
      check first) -- the yielded node's ``children`` are final once the ``with``
      block exits, and ``body`` may still be mutated afterwards because it was
      recorded by reference. ``child_key`` still names the span-path segment
      those children are addressed by, so pass the real stored key either way.

    ``span`` is always supplied by the caller: this generator is itself
    ``@contextlib.contextmanager``-decorated, so a span captured here would
    point at the BUILDER's line, not the bundle author's. A builder captures
    ``capture_span(depth=_CM_DEPTH)`` in its own generator and passes it in.
    """
    what = f"A card builder ({label})"
    rec = _require_active(what, span=span)
    node = record_card(body, span=span, what=what)
    node.child_key = child_key
    frame = ContainerFrame(role=CARD_ROLE, label=label, node=node)
    with rec.push(frame):
        yield node
    if assign:
        body[child_key] = [child.body for child in node.children]
