"""Reference extraction from a compiled dashboard's card tree (DESIGN §9 tier
2; dashboards-design.md §8's tier-2 row).

Table-driven off `hassle.compiler.dashboards.card_registry.CARD_REGISTRY`
(F5): a card's `entity_params` names the STORED KEYS whose value is an entity
id (or a list of them, or `entities`-shaped rows -- a bare string or a dict
with an `entity` key); a card's `declared` set is every stored key the
builder itself writes, which is what tells this walker a key is a KNOWN,
already-handled option rather than an unmodeled `extra={...}` passthrough
field.

Three things table-driven `entity_params` cannot express, each handled
separately (dashboards-design.md §8, and the DB3/DB7 coordination notes):

- **View/card badges** (both shapes: a bare legacy entity-id string, or the
  modern `{"type": "entity", "entity": ...}` object form) -- badges are not a
  card's own `entity_params`, they live in a `badges` list one level up
  (views), or nested inside a card whose `declared` set happens to include
  `"badges"` (currently only `heading`, whose own badges are entity refs, not
  a flat parameter `CardSpec.entity_params` could name).
- **Visibility / conditional conditions** (`cond.state`/`cond.numeric`'s
  `entity` key, recursing through `cond.any`/`cond.all`/`cond.not_`'s nested
  `conditions` list) -- checked on every node's `visibility` list AND (for the
  `conditional` card specifically) its own `conditions` key, which stores the
  identical condition shape under a different name.
- **The `area` card's `area` key** -- an HA AREA id, not an entity id (DB3c
  deliberately left it out of `entity_params` for exactly this reason). A
  small type->key table drives this the same way `entity_params` drives
  entity extraction; see `_AREA_CARD_PARAMS`.

**Unknown card types (raw/`custom:`/a future HA release's card) and unknown
keys on an otherwise-known card** (an `extra={...}` passthrough field, or any
stored key outside a row's `declared` set) get the same CONSERVATIVE
entity-shaped-string + Jinja scan `raw_action` bodies already get in
`hassle.registry.extract` -- reused directly (`_extract_entity_ids_from_jinja`
does both the Jinja-AST call extraction AND the domain-restricted regex
fallback unconditionally on whatever text it is given, so calling it on a
plain literal string is exactly as valid as calling it on a `{{ ... }}`
template).

**Spans**: every node's span is looked up by PATH against
`CompileResult.node_span` (F5's dot-joined `<key>[<index>]` grammar), falling
back to the nearest ANCESTOR's span when a path does not resolve --
`_resolve_span` also transparently tries the OTHER spelling of a single-child
`card` slot (`"...cards[0].card"` <-> `"...cards[0].card[0]"`) as a second
attempt before falling back to the ancestor span. `c.conditional`/
`c.entity_filter` both pass `child_is_list=False` (DB3-fixes landed it, per
dashboards-design.md §6.1.1), so the recorder emits the BARE spelling in
practice and `_walk_card` uses that as its primary path; the indexed spelling
is kept only as `_resolve_span`'s fallback, for robustness against a future
container that does not set the flag, per dashboards-design.md §8's "note it
and use the nearest ancestor span rather than blocking" guidance, instead of
hard-coding one convention and silently losing spans if the recorder changes
out from under this code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from hassle.compiler.bundle import CompileResult
from hassle.compiler.dashboards.card_registry import CARD_REGISTRY
from hassle.compiler.spans import SourceSpan
from hassle.ir.models import DashboardConfig
from hassle.registry.extract import (
    _extract_entity_ids_from_jinja,  # pyright: ignore[reportPrivateUsage]
    _is_template_string,  # pyright: ignore[reportPrivateUsage]
)

#: Card type -> the stored key holding an HA AREA id (not an entity id).
#: `CardSpec.entity_params` deliberately excludes these (DB3c note,
#: dashboards-design.md §8): a table of its own, exactly parallel in spirit,
#: drives the same table-driven extraction for the one v1 card that needs it.
_AREA_CARD_PARAMS: dict[str, str] = {"area": "area"}

#: Keys handled by dedicated logic elsewhere in this walker -- never rescanned
#: by the conservative fallback (`visibility`/`conditions` are not always in a
#: row's own `declared` set, so they are excluded unconditionally rather than
#: relying on that).
_ALWAYS_HANDLED_KEYS = frozenset({"visibility", "conditions"})


@dataclass(frozen=True)
class DashboardReference:
    """One entity/area reference found in a dashboard's compiled card tree."""

    entity_id: str | None
    area_id: str | None
    object_key: str
    span: SourceSpan | None
    #: Short human tag: "entity_param" | "area_param" | "badge" | "condition"
    #: | "raw-scan".
    source: str


def _append_entity_or_scan(
    value: str,
    *,
    object_key: str,
    span: SourceSpan | None,
    source: str,
    out: list[DashboardReference],
) -> None:
    """One entity-position string: a literal id, or (if Jinja-templated) every
    entity id its embedded `states()`/`state_attr()`/`is_state()` calls name."""
    if _is_template_string(value):
        for entity_id in _extract_entity_ids_from_jinja(value):
            out.append(
                DashboardReference(
                    entity_id=entity_id,
                    area_id=None,
                    object_key=object_key,
                    span=span,
                    source=source,
                )
            )
    else:
        out.append(
            DashboardReference(
                entity_id=value, area_id=None, object_key=object_key, span=span, source=source
            )
        )


def _extract_entity_param(
    value: Any, *, object_key: str, span: SourceSpan | None, out: list[DashboardReference]
) -> None:
    """One `entity_params` value: a bare entity id, or an `entities`-shaped
    list of rows (each a bare id string or a dict with an `entity` key)."""
    if value is None:
        return
    if isinstance(value, str):
        _append_entity_or_scan(
            value, object_key=object_key, span=span, source="entity_param", out=out
        )
    elif isinstance(value, list):
        for row in cast("list[Any]", value):
            if isinstance(row, str):
                _append_entity_or_scan(
                    row, object_key=object_key, span=span, source="entity_param", out=out
                )
            elif isinstance(row, dict):
                entity = cast("dict[str, Any]", row).get("entity")
                if isinstance(entity, str):
                    _append_entity_or_scan(
                        entity, object_key=object_key, span=span, source="entity_param", out=out
                    )


def _extract_area_param(
    card_type: str,
    card: dict[str, Any],
    *,
    object_key: str,
    span: SourceSpan | None,
    out: list[DashboardReference],
) -> None:
    key = _AREA_CARD_PARAMS.get(card_type)
    if key is None:
        return
    value = card.get(key)
    if isinstance(value, str) and not _is_template_string(value):
        out.append(
            DashboardReference(
                entity_id=None, area_id=value, object_key=object_key, span=span, source="area_param"
            )
        )


def _extract_badges(
    badges: Any, *, object_key: str, span: SourceSpan | None, out: list[DashboardReference]
) -> None:
    """A `badges` list -- view-level, or a card's own (currently only
    `heading`) -- bare legacy string or `{"type": "entity", "entity": ...}`."""
    if not isinstance(badges, list):
        return
    for item in cast("list[Any]", badges):
        if isinstance(item, str):
            _append_entity_or_scan(item, object_key=object_key, span=span, source="badge", out=out)
        elif isinstance(item, dict):
            entity = cast("dict[str, Any]", item).get("entity")
            if isinstance(entity, str):
                _append_entity_or_scan(
                    entity, object_key=object_key, span=span, source="badge", out=out
                )


def _extract_conditions(
    conditions: Any, *, object_key: str, span: SourceSpan | None, out: list[DashboardReference]
) -> None:
    """A `visibility` (or `conditional`'s own `conditions`) list: `entity`
    keys off `state`/`numeric_state` conditions, recursing through
    `and`/`or`/`not`'s nested `conditions` list."""
    if not isinstance(conditions, list):
        return
    for condition in cast("list[Any]", conditions):
        if not isinstance(condition, dict):
            continue
        condition_dict = cast("dict[str, Any]", condition)
        entity = condition_dict.get("entity")
        if isinstance(entity, str):
            _append_entity_or_scan(
                entity, object_key=object_key, span=span, source="condition", out=out
            )
        nested = condition_dict.get("conditions")
        if isinstance(nested, list):
            _extract_conditions(nested, object_key=object_key, span=span, out=out)


def _conservative_scan(
    value: Any, *, object_key: str, span: SourceSpan | None, out: list[DashboardReference]
) -> None:
    """The raw/unknown-node fallback (dashboards-design.md §8): every string
    found anywhere in `value` is scanned via the SAME machinery
    `raw_action` bodies get (`_extract_entity_ids_from_jinja` -- both its
    Jinja-AST call extraction and its domain-restricted regex fallback run
    unconditionally on whatever text they are given, template or not)."""
    if isinstance(value, str):
        for entity_id in _extract_entity_ids_from_jinja(value):
            out.append(
                DashboardReference(
                    entity_id=entity_id,
                    area_id=None,
                    object_key=object_key,
                    span=span,
                    source="raw-scan",
                )
            )
    elif isinstance(value, dict):
        for v in cast("dict[str, Any]", value).values():
            _conservative_scan(v, object_key=object_key, span=span, out=out)
    elif isinstance(value, list):
        for v in cast("list[Any]", value):
            _conservative_scan(v, object_key=object_key, span=span, out=out)


def _resolve_span(
    result: CompileResult, obj: DashboardConfig, path: str, ancestor_span: SourceSpan | None
) -> SourceSpan | None:
    """`CompileResult.node_span(obj, path)`, falling back to the OTHER
    spelling of a single-child slot (`"...card"` <-> `"...card[0]"`, tried in
    whichever direction `path` did not already use) and then to
    `ancestor_span` -- see the module docstring's span-grammar note."""
    span = result.node_span(obj, path)
    if span is not None:
        return span
    alt_path = path[: -len("[0]")] if path.endswith("[0]") else f"{path}[0]"
    span = result.node_span(obj, alt_path)
    if span is not None:
        return span
    return ancestor_span


def _walk_card(
    card: Any,
    *,
    path: str,
    object_key: str,
    obj: DashboardConfig,
    result: CompileResult,
    ancestor_span: SourceSpan | None,
    out: list[DashboardReference],
) -> None:
    if not isinstance(card, dict):
        return
    card_dict = cast("dict[str, Any]", card)
    span = _resolve_span(result, obj, path, ancestor_span)
    card_type = card_dict.get("type")
    spec = CARD_REGISTRY.get(card_type) if isinstance(card_type, str) else None

    if spec is None:
        # Unknown card type (raw_card/custom:/a future HA release's card):
        # the whole body, conservatively.
        _conservative_scan(card_dict, object_key=object_key, span=span, out=out)
        return

    for param in spec.entity_params:
        _extract_entity_param(card_dict.get(param), object_key=object_key, span=span, out=out)

    if isinstance(card_type, str):
        _extract_area_param(card_type, card_dict, object_key=object_key, span=span, out=out)

    _extract_conditions(card_dict.get("visibility"), object_key=object_key, span=span, out=out)
    _extract_conditions(card_dict.get("conditions"), object_key=object_key, span=span, out=out)

    if "badges" in spec.declared:
        _extract_badges(card_dict.get("badges"), object_key=object_key, span=span, out=out)

    if spec.container == "cards":
        children = card_dict.get("cards")
        if isinstance(children, list):
            for i, child in enumerate(cast("list[Any]", children)):
                _walk_card(
                    child,
                    path=f"{path}.cards[{i}]",
                    object_key=object_key,
                    obj=obj,
                    result=result,
                    ancestor_span=span,
                    out=out,
                )
    elif spec.container == "card":
        child = card_dict.get("card")
        if isinstance(child, dict):
            _walk_card(
                child,
                # Bare spelling is primary: `child_is_list=False` containers
                # (`c.conditional`/`c.entity_filter`) now emit the bare
                # `"...card"` path, not the indexed `"...card[0]"` one
                # (DB3-fixes landed the flag) -- `_resolve_span` still tries
                # the indexed spelling as a fallback for robustness.
                path=f"{path}.card",
                object_key=object_key,
                obj=obj,
                result=result,
                ancestor_span=span,
                out=out,
            )

    # The conservative fallback scan for every UNDECLARED key on an otherwise
    # known card -- typically an `extra={...}` passthrough field (§8: "unknown
    # keys"). Declared-but-non-entity options (`title`, `icon`, ...) are known,
    # non-entity-shaped surface and are never rescanned here.
    handled_keys = spec.declared | _ALWAYS_HANDLED_KEYS
    for key, value in card_dict.items():
        if key in handled_keys:
            continue
        _conservative_scan(value, object_key=object_key, span=span, out=out)


def _walk_view(
    view: Any,
    *,
    path: str,
    object_key: str,
    obj: DashboardConfig,
    result: CompileResult,
    out: list[DashboardReference],
) -> None:
    if not isinstance(view, dict):
        return
    view_dict = cast("dict[str, Any]", view)
    span = _resolve_span(result, obj, path, None)

    _extract_badges(view_dict.get("badges"), object_key=object_key, span=span, out=out)
    _extract_conditions(view_dict.get("visibility"), object_key=object_key, span=span, out=out)

    sections = view_dict.get("sections")
    if isinstance(sections, list):
        for i, section in enumerate(cast("list[Any]", sections)):
            if not isinstance(section, dict):
                continue
            section_dict = cast("dict[str, Any]", section)
            section_path = f"{path}.sections[{i}]"
            section_span = _resolve_span(result, obj, section_path, span)
            _extract_conditions(
                section_dict.get("visibility"), object_key=object_key, span=section_span, out=out
            )
            cards = section_dict.get("cards")
            if isinstance(cards, list):
                for j, card in enumerate(cast("list[Any]", cards)):
                    _walk_card(
                        card,
                        path=f"{section_path}.cards[{j}]",
                        object_key=object_key,
                        obj=obj,
                        result=result,
                        ancestor_span=section_span,
                        out=out,
                    )

    # A masonry/panel/sidebar/legacy view's own flat `cards` list.
    cards = view_dict.get("cards")
    if isinstance(cards, list):
        for i, card in enumerate(cast("list[Any]", cards)):
            _walk_card(
                card,
                path=f"{path}.cards[{i}]",
                object_key=object_key,
                obj=obj,
                result=result,
                ancestor_span=span,
                out=out,
            )


def extract_dashboard_references(result: CompileResult) -> list[DashboardReference]:
    """Extract every entity/area reference from every compiled dashboard's card tree."""
    refs: list[DashboardReference] = []
    for object_key, obj in result.objects.items():
        if not isinstance(obj, DashboardConfig):
            continue
        body = obj.to_ha()
        config = body.get("config")
        if not isinstance(config, dict):
            continue
        views = cast("dict[str, Any]", config).get("views")
        if not isinstance(views, list):
            continue
        for i, view in enumerate(cast("list[Any]", views)):
            _walk_view(
                view, path=f"views[{i}]", object_key=object_key, obj=obj, result=result, out=refs
            )
    return refs
