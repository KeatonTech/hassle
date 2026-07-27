"""The structural dashboard verbs (§5.2/§5.5).

The eight names this module backs are the ONLY dashboard additions to
``hassle.__all__`` (card builders live in the ``hassle.cards`` namespace
instead, §5.1): ``view``, ``section``, ``badge``, ``raw_card``,
``raw_section``, ``raw_view`` here, plus ``dashboard``/``raw_dashboard`` in
:mod:`hassle.compiler.dashboards.decorators`.

Every context manager here is a ``@contextlib.contextmanager`` generator
capturing its own span at
:data:`~hassle.compiler.dashboards.recorder._CM_DEPTH` -- see that module's
docstring, and ``tests/test_dashboard_span_depth_empirical.py`` for the
line-pinned proof.
"""

from __future__ import annotations

import contextlib
from collections.abc import Generator, Mapping
from typing import Any

from hassle.compiler.dashboards.builders import (
    VisibilityArg,
    merge_extra,
    normalize_visibility,
    put,
)
from hassle.compiler.dashboards.errors import (
    DashboardNestingError,
    PanelViewArityError,
    SectionOutsideSectionsViewError,
)
from hassle.compiler.dashboards.recorder import (
    _CM_DEPTH,  # pyright: ignore[reportPrivateUsage]
    DASHBOARD_ROLE,
    SECTION_ROLE,
    SECTIONS_VIEW_TYPE,
    VIEW_ROLE,
    ContainerFrame,
    RecordedNode,
    _require_active,  # pyright: ignore[reportPrivateUsage]
    record_badge,
    record_card,
)
from hassle.compiler.spans import SourceSpan, capture_span

# `_require_active`/`_CM_DEPTH` are the recorder's sanctioned cross-module
# names (underscore-prefixed by module-internal convention, not by true
# privacy -- exactly like `recording._require_active` for the control-flow
# constructs). Suppressed once here rather than at each use.
#
# View option keywords, in the order they are written into the stored view body.
# `type` leads because it is the discriminator that decides whether the view
# stores `sections` or `cards`.
_VIEW_OPTION_ORDER: tuple[str, ...] = (
    "title",
    "path",
    "icon",
    "theme",
    "background",
    "max_columns",
    "subview",
    "visible",
    "header",
)
#: Every declared `view()` keyword -- what `extra=` may not shadow (§5.3).
_VIEW_DECLARED: frozenset[str] = frozenset({"type", "visibility", *_VIEW_OPTION_ORDER})
#: Every declared `section()` keyword.
_SECTION_DECLARED: frozenset[str] = frozenset({"type", "column_span", "visibility", "cards"})
#: Every declared `badge()` keyword (its `**options` are added per call).
_BADGE_DECLARED: frozenset[str] = frozenset({"type", "entity", "visibility"})


def _view_label(view_type: str | None) -> str:
    if view_type is None:
        return "a legacy masonry view (`type=None`)"
    return f"a `{view_type}` view"


@contextlib.contextmanager
def view(
    *,
    title: Any = None,
    path: Any = None,
    icon: Any = None,
    type: str | None = SECTIONS_VIEW_TYPE,
    max_columns: Any = None,
    subview: Any = None,
    visible: Any = None,
    theme: Any = None,
    background: Any = None,
    header: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> Generator[RecordedNode]:
    """``with view(...):`` — one view of the enclosing ``@dashboard`` (§5.2).

    One builder covers every view type. ``type=`` accepts:

    - ``"sections"`` (the authoring DEFAULT) — materialized explicitly into the
      stored config; the view holds ``with section():`` blocks, and a card
      recorded directly in it raises ``SectionRequiredError``;
    - ``"masonry"`` / ``"sidebar"`` / ``"panel"`` — the literal value; the view
      holds cards directly. A ``panel`` view must hold exactly one card;
    - ``None`` — emits **no** ``type`` key at all, the legacy-masonry storage
      shape (§2.2 item 4). The decompiler emits exactly what is stored (absent
      key -> ``type=None``, present value -> that value), so byte-stability
      holds in both directions with one builder.

    Any other string passes through verbatim and is treated as a cards-holding
    view, so a view type a future HA release adds is never an error.
    """
    span = capture_span(depth=_CM_DEPTH)
    rec = _require_active("`view()`", span=span)
    frame = rec.current
    if frame.role != DASHBOARD_ROLE:
        raise DashboardNestingError(
            "A view",
            f"inside {frame.label}",
            "Views are the top level of a dashboard's config and never nest inside each "
            "other, inside a section, or inside a card.",
            "close the enclosing block and open this `with view(...):` directly in the "
            "`@dashboard` function body.",
            span,
        )

    body: dict[str, Any] = {}
    put(body, "type", type)
    for name, value in (
        ("title", title),
        ("path", path),
        ("icon", icon),
        ("theme", theme),
        ("background", background),
        ("max_columns", max_columns),
        ("subview", subview),
        ("visible", visible),
        ("header", header),
    ):
        put(body, name, value)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="view", declared=_VIEW_DECLARED, span=span)

    is_sections = type == SECTIONS_VIEW_TYPE
    child_key = "sections" if is_sections else "cards"
    node = RecordedNode(body=body, span=span, child_key=child_key)
    rec.root.children.append(node)
    with rec.push(
        ContainerFrame(role=VIEW_ROLE, label=_view_label(type), node=node, view_type=type)
    ):
        yield node

    if type == "panel" and len(node.children) != 1:
        raise PanelViewArityError(len(node.children), span)
    if node.badges:
        body["badges"] = [badge_node.body for badge_node in node.badges]
    body[child_key] = [child.body for child in node.children]


@contextlib.contextmanager
def section(
    *,
    column_span: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> Generator[RecordedNode]:
    """``with section():`` — one grid section of a ``sections`` view (§5.2).

    Stored as ``{"type": "grid", "cards": [...]}``: HA's sections are grid cards
    living in the view's own ``sections`` list, which only a ``sections`` view
    has — anywhere else raises :class:`SectionOutsideSectionsViewError`.
    """
    span = capture_span(depth=_CM_DEPTH)
    rec = _require_active("`section()`", span=span)
    # Options are resolved BEFORE the block runs, so an `extra=` shadow error
    # points at the `with section(...)` line rather than at its last card;
    # `cards` is appended last, so a stored section reads options-then-contents.
    body = _section_body(column_span=column_span, visibility=visibility, extra=extra, span=span)
    node = _open_section(span=span, body=body)
    with rec.push(ContainerFrame(role=SECTION_ROLE, label="a section", node=node)):
        yield node
    body["cards"] = [child.body for child in node.children]


def _section_body(
    *,
    column_span: Any,
    visibility: VisibilityArg | None,
    extra: Mapping[str, Any] | None,
    span: SourceSpan | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"type": "grid"}
    put(body, "column_span", column_span)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="section", declared=_SECTION_DECLARED, span=span)
    return body


def _open_section(
    *,
    span: SourceSpan | None,
    body: dict[str, Any] | None = None,
    what: str = "`section()`",
) -> RecordedNode:
    """Place a section node in the enclosing view, enforcing §5.2's discipline."""
    rec = _require_active(what, span=span)
    frame = rec.current
    if frame.role == DASHBOARD_ROLE:
        raise DashboardNestingError(
            "A section",
            "directly in the `@dashboard` body",
            "Sections live in a view's own `sections` list, so one outside every view has "
            "nowhere to be written.",
            'open a view first -- `with view():` (its default `type="sections"` is the one '
            "that holds sections) -- and put the `with section():` inside it.",
            span,
        )
    if frame.role != VIEW_ROLE:
        raise SectionOutsideSectionsViewError(frame.label, span)
    if frame.view_type != SECTIONS_VIEW_TYPE:
        raise SectionOutsideSectionsViewError(_view_label(frame.view_type), span)
    node = RecordedNode(body=body if body is not None else {}, span=span, child_key="cards")
    frame.node.children.append(node)
    return node


def badge(
    entity_or_dict: Any,
    *,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
    **options: Any,
) -> None:
    """Record a badge on the enclosing view (§5.2).

    An entity id (or an ``e.``-registry ref / helper handle — anything that is a
    ``str``) builds the modern object form
    ``{"type": "entity", "entity": ..., **options}``; a plain ``dict`` passes
    through verbatim, which is how legacy bare-string badges and unknown badge
    shapes round-trip (§2.2 item 6). ``**options`` are HA's badge options,
    merged verbatim either way.
    """
    span = capture_span(depth=0)
    body: dict[str, Any]
    if isinstance(entity_or_dict, dict):
        body = dict(entity_or_dict)  # pyright: ignore[reportUnknownArgumentType]
    else:
        body = {"type": "entity", "entity": str(entity_or_dict)}
    body.update(options)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(
        body,
        extra,
        builder="badge",
        declared=_BADGE_DECLARED | frozenset(options),
        span=span,
    )
    record_badge(body, span=span)


# ---------------------------------------------------------------------------
# The structural raw ladder (§5.5) -- dicts, not YAML strings, exactly like
# every other `raw_*` verb.
# ---------------------------------------------------------------------------
def raw_card(body: Mapping[str, Any]) -> None:
    """Record a verbatim card dict inside any container (§5.5).

    The bottom rung: a third-party card (``custom:bubble-card``), a built-in
    card Hassle does not model yet, anything at all. The dict is copied, so the
    caller may keep and mutate their own.
    """
    span = capture_span(depth=0)
    record_card(dict(body), span=span, what="`raw_card()`")


def raw_section(body: Mapping[str, Any]) -> None:
    """Record a verbatim section dict inside a ``sections`` view (§5.5)."""
    span = capture_span(depth=0)
    node = _open_section(span=span, body=dict(body), what="`raw_section()`")
    node.child_key = None  # its cards are inside the verbatim dict, not recorded


def raw_view(body: Mapping[str, Any]) -> None:
    """Record a verbatim view dict inside a ``@dashboard`` body (§5.5).

    The rung for a view whose own top level is unmodelled — a strategy view, a
    view type a future HA release adds.
    """
    span = capture_span(depth=0)
    rec = _require_active("`raw_view()`", span=span)
    frame = rec.current
    if frame.role != DASHBOARD_ROLE:
        raise DashboardNestingError(
            "A raw view",
            f"inside {frame.label}",
            "Views are the top level of a dashboard's config and never nest inside each "
            "other, inside a section, or inside a card.",
            "close the enclosing block and call `raw_view({...})` directly in the "
            "`@dashboard` function body.",
            span,
        )
    rec.root.children.append(RecordedNode(body=dict(body), span=span))
