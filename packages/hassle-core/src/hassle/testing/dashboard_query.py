"""``DashboardQuery`` — a thin read-only wrapper over compiled dashboard IR
(DESIGN §10; docs/internals/dashboards-design.md §9.1).

Dashboards don't execute, so the simulator is not the vehicle for testing
them; assertions instead run against the COMPILED IR (I5's spirit: test the
artifact), exactly like reading a `CompileResult` directly. `DashboardQuery`
is deliberately dumb: `.meta`, `.config`, `.views`, `.view(path_or_index)`,
`.cards(type=, entity=)` (a recursive walk through sections/stacks/
conditional/entity-filter -- any node holding a `cards` list or a `card`
dict), each node exposing the plain stored dict plus `.parent`. No assertion
DSL beyond that -- plain dict asserts keep tests honest and future-proof.

This module is intentionally NOT table-driven off
`hassle.compiler.dashboards.card_registry.CARD_REGISTRY` (unlike
`hassle.registry.dashboard_extract`): the package-layering rule
(`tests/test_package_layering.py`) only allows `hassle.testing` to import
`hassle.ir`/`hassle.compiler`, not `hassle.registry` (where the card
registry's *consumers* live) or `hassle.compiler.dashboards` (an internal
compiler seam, not part of this package's contract). Walking purely by SHAPE
(a `cards` list or a `card` dict is a container, regardless of its `type`)
needs no registry at all, and is also more permissive for a testing helper: a
custom/raw card that happens to nest children the same way still gets walked.
"""

from __future__ import annotations

from typing import Any, cast

from hassle.ir.models import DashboardConfig


class DashboardNode(dict[str, Any]):
    """One recorded view/section/card, exposed read-only as the plain stored
    dict, plus `.parent` (the enclosing node, or `None` at the top)."""

    def __init__(self, data: dict[str, Any], parent: DashboardNode | None = None) -> None:
        super().__init__(data)
        self.parent = parent


def _collect_cards(node: DashboardNode, out: list[DashboardNode]) -> None:
    """Recurse into `cards` (a list container: stacks, grids, sections'
    own card list) and `card` (a single-child container: `conditional`,
    `entity_filter`) -- every child found is itself a candidate card AND is
    recursed into for its own children."""
    cards = node.get("cards")
    if isinstance(cards, list):
        for child in cast("list[Any]", cards):
            if isinstance(child, dict):
                child_node = DashboardNode(cast("dict[str, Any]", child), parent=node)
                out.append(child_node)
                _collect_cards(child_node, out)
    card = node.get("card")
    if isinstance(card, dict):
        child_node = DashboardNode(cast("dict[str, Any]", card), parent=node)
        out.append(child_node)
        _collect_cards(child_node, out)


def _node_mentions_entity(node: DashboardNode, entity: str) -> bool:
    """Best-effort "does this card reference this entity" check -- the same
    shapes `hassle.registry.dashboard_extract` handles: a scalar `entity`/
    `camera_image` field, or an `entities`-shaped list of rows (bare string or
    a dict with an `entity` key). Deliberately not registry-driven (this
    module's own docstring); a card this heuristic misses is still reachable
    by `type=` or a plain dict assert on the returned node."""
    for key in ("entity", "camera_image"):
        if node.get(key) == entity:
            return True
    rows = node.get("entities")
    if isinstance(rows, list):
        for row in cast("list[Any]", rows):
            if row == entity:
                return True
            if isinstance(row, dict) and cast("dict[str, Any]", row).get("entity") == entity:
                return True
    return False


class DashboardQuery:
    """A read-only view over one compiled `DashboardConfig` (dashboards-design
    §9.1). Construct via `Simulator.dashboard(url_path)` (the `sim` pytest
    fixture) or directly: `DashboardQuery(compile_result.objects["dashboard:<url_path>"])`.
    """

    def __init__(self, obj: DashboardConfig) -> None:
        body = obj.to_ha()
        #: The registry-item half of the envelope (`None` for the default
        #: dashboard), exactly as stored (dashboards-design.md §3.2).
        self.meta: Any = body.get("meta")
        #: The Lovelace view config, verbatim.
        self.config: Any = body.get("config")

    @property
    def views(self) -> list[DashboardNode]:
        """Every top-level view, in stored order."""
        config = self.config
        views = cast("dict[str, Any]", config).get("views") if isinstance(config, dict) else None
        if not isinstance(views, list):
            return []
        return [
            DashboardNode(cast("dict[str, Any]", v), parent=None)
            for v in cast("list[Any]", views)
            if isinstance(v, dict)
        ]

    def view(self, path_or_index: str | int) -> DashboardNode:
        """One view, by its stored `path` (a string) or its position (an int).

        Raises a clear `KeyError` listing every view this dashboard actually
        has, rather than a bare `IndexError`/`KeyError` on the raw list/dict.
        """
        views = self.views
        if isinstance(path_or_index, int):
            if 0 <= path_or_index < len(views):
                return views[path_or_index]
            raise KeyError(
                f"no view at index {path_or_index}; this dashboard has {len(views)} "
                f"view(s) (indices 0..{len(views) - 1})."
                if views
                else f"no view at index {path_or_index}; this dashboard has no views."
            )
        for v in views:
            if v.get("path") == path_or_index:
                return v
        known = [v.get("path") for v in views]
        raise KeyError(
            f"no view with path {path_or_index!r} in this dashboard; known view paths: {known}."
        )

    def cards(self, *, type: str | None = None, entity: str | None = None) -> list[DashboardNode]:
        """Every card in this dashboard, recursively (sections, stacks,
        conditional's/entity-filter's wrapped card, ...), optionally filtered
        by stored `type` and/or a referenced entity id (best-effort, see
        `_node_mentions_entity`)."""
        out: list[DashboardNode] = []
        for view_node in self.views:
            sections = view_node.get("sections")
            if isinstance(sections, list):
                for section in cast("list[Any]", sections):
                    if isinstance(section, dict):
                        section_node = DashboardNode(
                            cast("dict[str, Any]", section), parent=view_node
                        )
                        _collect_cards(section_node, out)
            # A masonry/panel/sidebar/legacy view's own flat `cards` list.
            _collect_cards(view_node, out)
        if type is not None:
            out = [c for c in out if c.get("type") == type]
        if entity is not None:
            out = [c for c in out if _node_mentions_entity(c, entity)]
        return out
