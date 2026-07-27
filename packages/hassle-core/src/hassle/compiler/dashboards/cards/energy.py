"""DB3c (energy half) -- the 12 built-in Energy dashboard cards (§2.3).

docs/internals/dashboards-design.md §5.3/§6.1.1, same conventions as
``cards/visual.py``/``cards/media.py``/``cards/domain.py`` (DB3b/DB3c) --
those modules' docstrings have the fuller rationale. Every builder here is a
plain leaf-card function on the shared ``put``/``merge_extra``/
``normalize_visibility`` conventions and the ``record_card`` seam, registered
into ``CARD_REGISTRY`` at import time.

Design §2.3 calls this family "leaf, mostly option-free": every card here
reads from the dashboard's shared Energy data collection rather than from an
entity of its own, so none of them carry an ``entity_params`` row --
``CardSpec.entity_params`` is ``()`` for all twelve. The one option common to
the whole family is ``collection_key=`` (which energy-collection instance to
read from -- HA defaults it when omitted); ``energy_distribution`` alone also
takes ``link_dashboard=`` (show a link back to the Energy dashboard).

**Implementation note (2026-07-27), for DB0 to confirm:** ``energy_sankey``
additionally models ``title=``. Unlike the other eleven cards (whose HA
frontend schemas are genuinely option-free besides ``collection_key``), the
Sankey card is the newest and most configurable of the family and is believed
to accept a card-level ``title``; this is the one shape in this batch not
corroborated by a second source (the DB0 HA-version pin this design doc calls
for hadn't landed yet when this batch was written). Nothing is lost either
way: an unrecognized ``title=`` would simply round-trip through ``extra=``
instead, so a correction here is a one-line change plus a golden
regeneration -- flagged in the DB3c report rather than silently assumed.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hassle.compiler.dashboards.builders import (
    VisibilityArg,
    merge_extra,
    normalize_visibility,
    put,
)
from hassle.compiler.dashboards.card_registry import CardSpec, register_card
from hassle.compiler.dashboards.recorder import record_card
from hassle.compiler.spans import capture_span


def _simple_energy_card(
    type_: str,
    builder_name: str,
    declared: frozenset[str],
    *,
    collection_key: Any,
    visibility: VisibilityArg | None,
    extra: Mapping[str, Any] | None,
) -> None:
    """Shared body for the plain ``{type, collection_key?, visibility?}`` shape.

    Every builder in this module except ``energy_distribution`` (extra
    ``link_dashboard=``) and ``energy_sankey`` (extra ``title=``) is exactly
    this shape; factored once so the eventual review reads the ten identical
    bodies as one rule, not ten hand-copies that could drift.
    """
    span = capture_span(depth=0)
    body: dict[str, Any] = {"type": type_}
    put(body, "collection_key", collection_key)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder=builder_name, declared=declared, span=span)
    record_card(body, span=span, what=f"`{builder_name}()`")


# ---------------------------------------------------------------------------
# energy_date_selection
# ---------------------------------------------------------------------------
_ENERGY_DATE_SELECTION_DECLARED = frozenset({"type", "collection_key", "visibility"})


def energy_date_selection(
    *,
    collection_key: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.energy_date_selection(...)`` -- the Energy dashboard's date picker."""
    _simple_energy_card(
        "energy-date-selection",
        "c.energy_date_selection",
        _ENERGY_DATE_SELECTION_DECLARED,
        collection_key=collection_key,
        visibility=visibility,
        extra=extra,
    )


register_card(
    CardSpec(
        type="energy-date-selection",
        declared=frozenset({"type", "collection_key", "visibility"}),
        builder="c.energy_date_selection",
    )
)


# ---------------------------------------------------------------------------
# energy_usage_graph
# ---------------------------------------------------------------------------
_ENERGY_USAGE_GRAPH_DECLARED = frozenset({"type", "collection_key", "visibility"})


def energy_usage_graph(
    *,
    collection_key: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.energy_usage_graph(...)`` -- grid consumption/return bar chart."""
    _simple_energy_card(
        "energy-usage-graph",
        "c.energy_usage_graph",
        _ENERGY_USAGE_GRAPH_DECLARED,
        collection_key=collection_key,
        visibility=visibility,
        extra=extra,
    )


register_card(
    CardSpec(
        type="energy-usage-graph",
        declared=frozenset({"type", "collection_key", "visibility"}),
        builder="c.energy_usage_graph",
    )
)


# ---------------------------------------------------------------------------
# energy_solar_graph
# ---------------------------------------------------------------------------
_ENERGY_SOLAR_GRAPH_DECLARED = frozenset({"type", "collection_key", "visibility"})


def energy_solar_graph(
    *,
    collection_key: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.energy_solar_graph(...)`` -- solar production bar chart."""
    _simple_energy_card(
        "energy-solar-graph",
        "c.energy_solar_graph",
        _ENERGY_SOLAR_GRAPH_DECLARED,
        collection_key=collection_key,
        visibility=visibility,
        extra=extra,
    )


register_card(
    CardSpec(
        type="energy-solar-graph",
        declared=frozenset({"type", "collection_key", "visibility"}),
        builder="c.energy_solar_graph",
    )
)


# ---------------------------------------------------------------------------
# energy_gas_graph
# ---------------------------------------------------------------------------
_ENERGY_GAS_GRAPH_DECLARED = frozenset({"type", "collection_key", "visibility"})


def energy_gas_graph(
    *,
    collection_key: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.energy_gas_graph(...)`` -- gas consumption bar chart."""
    _simple_energy_card(
        "energy-gas-graph",
        "c.energy_gas_graph",
        _ENERGY_GAS_GRAPH_DECLARED,
        collection_key=collection_key,
        visibility=visibility,
        extra=extra,
    )


register_card(
    CardSpec(
        type="energy-gas-graph",
        declared=frozenset({"type", "collection_key", "visibility"}),
        builder="c.energy_gas_graph",
    )
)


# ---------------------------------------------------------------------------
# energy_water_graph
# ---------------------------------------------------------------------------
_ENERGY_WATER_GRAPH_DECLARED = frozenset({"type", "collection_key", "visibility"})


def energy_water_graph(
    *,
    collection_key: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.energy_water_graph(...)`` -- water consumption bar chart."""
    _simple_energy_card(
        "energy-water-graph",
        "c.energy_water_graph",
        _ENERGY_WATER_GRAPH_DECLARED,
        collection_key=collection_key,
        visibility=visibility,
        extra=extra,
    )


register_card(
    CardSpec(
        type="energy-water-graph",
        declared=frozenset({"type", "collection_key", "visibility"}),
        builder="c.energy_water_graph",
    )
)


# ---------------------------------------------------------------------------
# energy_distribution -- the one card with an extra `link_dashboard=` option
# ---------------------------------------------------------------------------
_ENERGY_DISTRIBUTION_DECLARED = frozenset(
    {"type", "collection_key", "link_dashboard", "visibility"}
)


def energy_distribution(
    *,
    collection_key: Any = None,
    link_dashboard: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.energy_distribution(...)`` -- the grid/solar/battery/home flow diagram.

    ``link_dashboard`` shows a link back to the built-in Energy dashboard when
    true -- the one option this family's other eleven cards do not have.
    """
    span = capture_span(depth=0)
    body: dict[str, Any] = {"type": "energy-distribution"}
    put(body, "collection_key", collection_key)
    put(body, "link_dashboard", link_dashboard)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(
        body,
        extra,
        builder="c.energy_distribution",
        declared=_ENERGY_DISTRIBUTION_DECLARED,
        span=span,
    )
    record_card(body, span=span, what="`c.energy_distribution()`")


register_card(
    CardSpec(
        type="energy-distribution",
        declared=frozenset({"type", "collection_key", "link_dashboard", "visibility"}),
        builder="c.energy_distribution",
    )
)


# ---------------------------------------------------------------------------
# energy_sources_table
# ---------------------------------------------------------------------------
_ENERGY_SOURCES_TABLE_DECLARED = frozenset({"type", "collection_key", "visibility"})


def energy_sources_table(
    *,
    collection_key: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.energy_sources_table(...)`` -- the per-source cost/usage breakdown table."""
    _simple_energy_card(
        "energy-sources-table",
        "c.energy_sources_table",
        _ENERGY_SOURCES_TABLE_DECLARED,
        collection_key=collection_key,
        visibility=visibility,
        extra=extra,
    )


register_card(
    CardSpec(
        type="energy-sources-table",
        declared=frozenset({"type", "collection_key", "visibility"}),
        builder="c.energy_sources_table",
    )
)


# ---------------------------------------------------------------------------
# energy_grid_neutrality_gauge
# ---------------------------------------------------------------------------
_ENERGY_GRID_NEUTRALITY_GAUGE_DECLARED = frozenset({"type", "collection_key", "visibility"})


def energy_grid_neutrality_gauge(
    *,
    collection_key: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.energy_grid_neutrality_gauge(...)`` -- grid-independence percentage gauge."""
    _simple_energy_card(
        "energy-grid-neutrality-gauge",
        "c.energy_grid_neutrality_gauge",
        _ENERGY_GRID_NEUTRALITY_GAUGE_DECLARED,
        collection_key=collection_key,
        visibility=visibility,
        extra=extra,
    )


register_card(
    CardSpec(
        type="energy-grid-neutrality-gauge",
        declared=frozenset({"type", "collection_key", "visibility"}),
        builder="c.energy_grid_neutrality_gauge",
    )
)


# ---------------------------------------------------------------------------
# energy_solar_consumed_gauge
# ---------------------------------------------------------------------------
_ENERGY_SOLAR_CONSUMED_GAUGE_DECLARED = frozenset({"type", "collection_key", "visibility"})


def energy_solar_consumed_gauge(
    *,
    collection_key: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.energy_solar_consumed_gauge(...)`` -- solar self-consumption percentage gauge."""
    _simple_energy_card(
        "energy-solar-consumed-gauge",
        "c.energy_solar_consumed_gauge",
        _ENERGY_SOLAR_CONSUMED_GAUGE_DECLARED,
        collection_key=collection_key,
        visibility=visibility,
        extra=extra,
    )


register_card(
    CardSpec(
        type="energy-solar-consumed-gauge",
        declared=frozenset({"type", "collection_key", "visibility"}),
        builder="c.energy_solar_consumed_gauge",
    )
)


# ---------------------------------------------------------------------------
# energy_carbon_consumed_gauge
# ---------------------------------------------------------------------------
_ENERGY_CARBON_CONSUMED_GAUGE_DECLARED = frozenset({"type", "collection_key", "visibility"})


def energy_carbon_consumed_gauge(
    *,
    collection_key: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.energy_carbon_consumed_gauge(...)`` -- non-fossil consumption percentage gauge."""
    _simple_energy_card(
        "energy-carbon-consumed-gauge",
        "c.energy_carbon_consumed_gauge",
        _ENERGY_CARBON_CONSUMED_GAUGE_DECLARED,
        collection_key=collection_key,
        visibility=visibility,
        extra=extra,
    )


register_card(
    CardSpec(
        type="energy-carbon-consumed-gauge",
        declared=frozenset({"type", "collection_key", "visibility"}),
        builder="c.energy_carbon_consumed_gauge",
    )
)


# ---------------------------------------------------------------------------
# energy_self_sufficiency_gauge
# ---------------------------------------------------------------------------
_ENERGY_SELF_SUFFICIENCY_GAUGE_DECLARED = frozenset({"type", "collection_key", "visibility"})


def energy_self_sufficiency_gauge(
    *,
    collection_key: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.energy_self_sufficiency_gauge(...)`` -- home-energy self-sufficiency percentage gauge."""
    _simple_energy_card(
        "energy-self-sufficiency-gauge",
        "c.energy_self_sufficiency_gauge",
        _ENERGY_SELF_SUFFICIENCY_GAUGE_DECLARED,
        collection_key=collection_key,
        visibility=visibility,
        extra=extra,
    )


register_card(
    CardSpec(
        type="energy-self-sufficiency-gauge",
        declared=frozenset({"type", "collection_key", "visibility"}),
        builder="c.energy_self_sufficiency_gauge",
    )
)


# ---------------------------------------------------------------------------
# energy_sankey -- the one card with an extra `title=` option (see module note)
# ---------------------------------------------------------------------------
_ENERGY_SANKEY_DECLARED = frozenset({"type", "collection_key", "title", "visibility"})


def energy_sankey(
    *,
    collection_key: Any = None,
    title: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.energy_sankey(...)`` -- the grid/solar/battery/device Sankey flow diagram.

    ``title=`` is this batch's one unverified assumption -- see the module
    docstring's DB0 note.
    """
    span = capture_span(depth=0)
    body: dict[str, Any] = {"type": "energy-sankey"}
    put(body, "collection_key", collection_key)
    put(body, "title", title)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.energy_sankey", declared=_ENERGY_SANKEY_DECLARED, span=span)
    record_card(body, span=span, what="`c.energy_sankey()`")


register_card(
    CardSpec(
        type="energy-sankey",
        declared=frozenset({"type", "collection_key", "title", "visibility"}),
        builder="c.energy_sankey",
    )
)
