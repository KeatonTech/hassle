"""``hassle.cards`` — the Lovelace card-builder namespace (§5.1).

::

    from hassle import *                  # dashboard, view, section, badge, raw_* …
    from hassle import cards as c         # c.tile(...), with c.vertical_stack(): …
    from hassle.cards import cond         # cond.state(...), cond.screen(...)
    from hassle.registry import entities as e

A **non-star module** (not part of ``from hassle import *``), and the third
dedicated entry point beside ``hassle.registry`` and ``hassle.services`` — but
for a different reason than those two. They are instance-dynamic (what domains
and services exist depends on the HA install). This one is **namespace
hygiene**: card type names collide head-on with the frozen DSL surface
(``area``, ``calendar``, ``button``, ``light``, ``sensor`` are already DSL
names, and ``map`` is a Python builtin), so renaming ~35 cards away from their
own HA names would be 35 permanent warts. Attribute access on a dedicated
namespace costs one import line and keeps every builder named exactly what HA
calls it.

The card vocabulary is a CLOSED, versioned set (it ships in HA frontend
releases rather than being enumerable from an instance), so unlike
``hassle.services`` this module has **no** ``__getattr__`` dynamism: every
builder is a real typed function and pyright checks every keyword. A card type
Hassle does not know is never an error either — it round-trips through
``raw_card`` and shows up in the decompile-coverage metric.

This module is a thin re-export; the builders themselves live in
``hassle.compiler.dashboards`` (mirroring how the frozen top-level surface is
assembled). ``__all__`` is frozen under the same additive-only rule as
``hassle.__all__`` (docs/internals/dsl-extensions.md).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Builder registration point.
#
# DB3's card families land here, one append-only import + one `__all__` entry
# per builder, e.g.:
#
#     from hassle.compiler.dashboards.cards.layout import (
#         conditional, entity_filter, grid, horizontal_stack, vertical_stack,
#     )
#
# Each builder is implemented on the `record_card` / `push_container` seam
# (hassle.compiler.dashboards.recorder) and uses the shared `merge_extra` /
# `normalize_visibility` helpers (hassle.compiler.dashboards.builders), so all
# of them share one `extra=`/`visibility=` contract by construction. Every
# builder also registers a `CardSpec` in
# `hassle.compiler.dashboards.card_registry` (freeze F5), which is what the
# decompiler and the entity-extraction validator read.
# ---------------------------------------------------------------------------
from hassle.compiler.dashboards.cards.domain import (
    alarm_panel,
    area,
    humidifier,
    light,
    media_control,
    plant_status,
    shopping_list,
    thermostat,
    todo_list,
    weather_forecast,
)
from hassle.compiler.dashboards.cards.energy import (
    energy_carbon_consumed_gauge,
    energy_date_selection,
    energy_distribution,
    energy_gas_graph,
    energy_grid_neutrality_gauge,
    energy_sankey,
    energy_self_sufficiency_gauge,
    energy_solar_consumed_gauge,
    energy_solar_graph,
    energy_sources_table,
    energy_usage_graph,
    energy_water_graph,
)
from hassle.compiler.dashboards.cards.media import (
    iframe,
    map,
    picture,
    picture_elements,
    picture_glance,
)
from hassle.compiler.dashboards.cards.visual import (
    calendar,
    clock,
    gauge,
    history_graph,
    logbook,
    markdown,
    sensor,
    statistic,
    statistics_graph,
)
from hassle.compiler.dashboards.conditions import cond

__all__ = [
    "alarm_panel",
    "area",
    "calendar",
    "clock",
    "cond",
    "energy_carbon_consumed_gauge",
    "energy_date_selection",
    "energy_distribution",
    "energy_gas_graph",
    "energy_grid_neutrality_gauge",
    "energy_sankey",
    "energy_self_sufficiency_gauge",
    "energy_solar_consumed_gauge",
    "energy_solar_graph",
    "energy_sources_table",
    "energy_usage_graph",
    "energy_water_graph",
    "gauge",
    "history_graph",
    "humidifier",
    "iframe",
    "light",
    "logbook",
    "map",
    "markdown",
    "media_control",
    "picture",
    "picture_elements",
    "picture_glance",
    "plant_status",
    "sensor",
    "shopping_list",
    "statistic",
    "statistics_graph",
    "thermostat",
    "todo_list",
    "weather_forecast",
]
